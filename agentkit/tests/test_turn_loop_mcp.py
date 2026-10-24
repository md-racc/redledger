"""The turn loop with the real droid-sdk in-process MCP server and a real MCP `call_tool` (no CLI, no
model, no keys). Skipped when droid-sdk[mcp] isn't installed."""

import asyncio
import json
import threading
import time

import pytest

pytest.importorskip("droid_sdk.mcp")
pytest.importorskip("mcp")

from droid_sdk.mcp import close_sdk_server, start_sdk_server  # noqa: E402
from mcp import ClientSession  # noqa: E402
from mcp.client.streamable_http import streamablehttp_client  # noqa: E402
from test_invocation import FakeRequest, mcp_action  # noqa: E402

from agentkit import AgentSettings, DroidAgent, EventEmitter, LedgerClient, TurnRequest, ctx, ledger_tool  # noqa: E402
from agentkit.invocation import bind_registry  # noqa: E402
from agentkit.sync import run_on_turn_loop  # noqa: E402

S = AgentSettings(AGENT_NAME="red", BATTLEFIELD_URL="http://127.0.0.1:9", INTERNAL_TOKEN="t", HTTP_TIMEOUT_SEC=1)
TURN = TurnRequest(episode_id="ep", day=1, controller_mode="enforce")
FREEZE_SEC = 1.0
seen: dict = {}


@ledger_tool("probe", "probe", redact=lambda a: {k: v for k, v in a.items() if k != "secret"})
async def probe(x: str, secret: str = "") -> str:
    seen["tool_thread"] = threading.current_thread().name
    seen["tool_got_secret"] = secret
    ctx.emitter().custom("probe_note", {"x": x})  # narration from the worker
    time.sleep(FREEZE_SEC)  # freezes the turn loop, as the SDK's sync handler does
    return json.dumps({"ok": True, "x": x})


class _Agent(DroidAgent):
    name = "red"
    autonomy = "high"

    def tools(self):
        return [("probe", "probe", probe)]

    async def build_prompt(self, req):
        return ""

    async def dry_run_turn(self, req):
        return ""


async def _turn(agent: _Agent, events: list) -> str:
    async with (
        LedgerClient(S, episode_id="ep", day=1) as ledger,
        EventEmitter(S, episode_id="ep", day=1, flush_budget_sec=0.2) as em,
    ):
        real_emit = em.emit

        def recording_emit(type_, payload):
            events.append((type_, threading.current_thread().name, payload))
            real_emit(type_, payload)

        em.emit = recording_emit  # type: ignore[method-assign]
        tokens = ctx.bind(ledger, em, TURN)
        try:
            reg = agent._new_registry(em)
            server = agent._mcp_server(reg)
            with bind_registry(reg):
                cfg = await start_sdk_server(server)
                try:
                    use = mcp_action("toolu_L", "probe", {"x": "a", "secret": "s3"}, server="red-ledger")
                    await agent._permission_entry(reg, FakeRequest(actions=(use,)))
                    headers = {h.name: h.value for h in cfg.headers}
                    async with streamablehttp_client(cfg.url, headers=headers) as (r, w, _):
                        async with ClientSession(r, w) as cs:
                            await cs.initialize()
                            res = await cs.call_tool("probe", {"x": "a", "secret": "s3"})
                            seen["result"] = res.content[0].text
                    reg.close()
                finally:
                    await close_sdk_server(server)
            seen["turn_thread"] = threading.current_thread().name
        finally:
            ctx.unbind(tokens)
    return "done"


async def test_real_mcp_call_on_the_turn_loop_keeps_the_service_loop_free(caplog):
    caplog.set_level("ERROR", logger="asyncio")
    seen.clear()
    events: list = []
    gaps: list[float] = []
    stop = asyncio.Event()

    async def heartbeat():
        last = time.monotonic()
        while not stop.is_set():
            await asyncio.sleep(0.01)
            now = time.monotonic()
            gaps.append(now - last)
            last = now

    beat = asyncio.create_task(heartbeat())
    out = await run_on_turn_loop(lambda: _turn(_Agent(S), events), name="mcp-turn", ceiling_sec=30)
    stop.set()
    await beat

    assert out == "done" and json.loads(seen["result"]) == {"ok": True, "x": "a"}
    assert seen["turn_thread"] == "mcp-turn"
    assert seen["tool_thread"].startswith("droid-tool")  # the body ran on a worker, not the turn loop
    assert seen["tool_got_secret"] == "s3"  # the tool still gets its real arguments
    # every emit (incl. the worker's replayed narration) happened on the turn thread; the registry's own
    # owner check would have raised otherwise
    assert events and {t for _, t, _ in events} == {"mcp-turn"}
    kinds = [k for k, _, _ in events]
    assert kinds == ["agent.tool_call", "x.red.probe_note", "agent.tool_result"]
    call = events[0][2]
    assert call["tool_use_id"] == "toolu_L" and call["args"] == {"x": "a"}  # SDK id, redacted on the wire
    assert events[2][2]["tool_use_id"] == "toolu_L" and events[2][2]["ok"] is True
    assert max(gaps) - 0.01 <= 0.05, f"service loop stalled {max(gaps):.3f}s"
    # the SDK server's leftover tasks (sse_starlette's _shutdown_watcher) are cancelled at teardown, not
    # destroyed while pending when the turn loop closes (seen on prod red before this fix)
    import gc

    await asyncio.sleep(0.05)
    gc.collect()
    assert not [r for r in caplog.records if "Task was destroyed but it is pending" in r.getMessage()]
