"""DroidAgent plumbing that runs without the Droid SDK: tool offload and the tool allowlist."""

import asyncio
import json
import time

from agentkit import AgentSettings, DroidAgent, LedgerClient, TurnRequest, ctx, ledger_tool

S = AgentSettings(AGENT_NAME="red", BATTLEFIELD_URL="http://bf", INTERNAL_TOKEN="t")
TURN = TurnRequest(episode_id="ep_1", day=3, controller_mode="off")


@ledger_tool("probe", "Await, then report what the tool can see.")
async def probe(name: str) -> str:
    await asyncio.sleep(0.01)  # a real await: droid-sdk 0.5.0 stalls the run if this yields on its loop
    L = ctx.ledger()
    return f"{name}|{ctx.turn().episode_id}|{L.day}|{isinstance(L, LedgerClient)}"


class _Agent(DroidAgent):
    name = "red"

    def tools(self):
        return [("probe", "probe", probe)]

    async def build_prompt(self, req):
        return ""

    async def dry_run_turn(self, req):
        return ""


class _Recorder:
    def __init__(self):
        self.calls: list[tuple[str, tuple]] = []

    def tool_call(self, *a):
        self.calls.append(("tool_call", a))

    def tool_result(self, *a):
        self.calls.append(("tool_result", a))


async def test_offload_runs_tool_off_loop_with_turn_context_and_narration():
    agent = _Agent(S)
    sync_tool = agent._offload(probe)
    rec = _Recorder()
    async with LedgerClient(S, episode_id=TURN.episode_id, day=TURN.day) as ledger:
        tokens = ctx.bind(ledger, rec, TURN)  # type: ignore[arg-type]
        try:
            out = sync_tool(name="x")  # sync: returns without yielding to this loop
        finally:
            ctx.unbind(tokens)
        await asyncio.sleep(0)  # let call_soon_threadsafe deliver the narration
    assert not asyncio.iscoroutine(out)
    assert out == "x|ep_1|3|True"
    assert [k for k, _ in rec.calls] == ["tool_call", "tool_result"]


def test_restrict_tools_ids_match_observed_droid_format():
    agent = _Agent(S)
    ids = agent._tool_ids or [f"{agent.name}-ledger___{n}" for (n, _, _) in agent.tools()]
    assert ids == ["red-ledger___probe"]


@ledger_tool("hang", "Never returns on its own.")
async def hang() -> str:
    await asyncio.sleep(3600)
    return "unreachable"


class _HangAgent(_Agent):
    def tools(self):
        return [("hang", "hang", hang)]

    def _tool_timeout_sec(self) -> float:
        return 0.2


async def test_offload_times_out_a_hung_tool_with_an_error_string_and_closes_the_event():
    agent = _HangAgent(S)
    sync_tool = agent._offload(hang)
    rec = _Recorder()
    async with LedgerClient(S, episode_id=TURN.episode_id, day=TURN.day) as ledger:
        tokens = ctx.bind(ledger, rec, TURN)  # type: ignore[arg-type]
        t0 = time.monotonic()
        try:
            out = sync_tool()
        finally:
            ctx.unbind(tokens)
        elapsed = time.monotonic() - t0
        await asyncio.sleep(0)
    body = json.loads(out)
    assert body["error"] is True and body["timeout"] is True and body["tool"] == "hang"
    assert "outcome is unknown" in body["detail"]
    assert elapsed < 0.2 + 1.0  # cancelled in its thread at the deadline, not after the grace period
    kinds = [k for k, _ in rec.calls]
    assert kinds.count("tool_call") == 1 and kinds.count("tool_result") == 1
    (call_id,) = [a[2] for k, a in rec.calls if k == "tool_call"]
    (result,) = [a for k, a in rec.calls if k == "tool_result"]
    assert result[0] == call_id and result[1] is False  # the timeout closes the same tool_use_id


def test_tool_timeout_sits_between_escalation_hold_and_stream_timeout():
    agent = _Agent(S)  # defaults: TURN_TIMEOUT_SEC=180, stream timeout 170, escalation hold 90
    t = agent._tool_timeout_sec()
    assert 90 + S.http_timeout_sec < t
    assert t + 2.0 < S.turn_timeout_sec - 10


@ledger_tool("wedge", "Blocks its thread without yielding, so in-thread cancellation can't land.")
async def wedge() -> str:
    time.sleep(0.6)
    return "late"


async def test_offload_outer_wait_catches_a_wedged_thread(monkeypatch):
    import agentkit.droid_agent as da

    monkeypatch.setattr(da, "_TOOL_GRACE_SEC", 0.1)
    agent = _HangAgent(S)
    sync_tool = agent._offload(wedge)
    async with LedgerClient(S, episode_id=TURN.episode_id, day=TURN.day) as ledger:
        tokens = ctx.bind(ledger, None, TURN)  # type: ignore[arg-type]
        t0 = time.monotonic()
        try:
            out = sync_tool()
        finally:
            ctx.unbind(tokens)
    assert time.monotonic() - t0 < 0.5
    assert json.loads(out)["timeout"] is True


async def test_run_turn_caps_the_final_flush_inside_battlefields_turn_wait(monkeypatch):
    import agentkit.droid_agent as da

    seen: dict = {}
    real = da.EventEmitter

    def spy(*a, **kw):
        seen.update(kw)
        return real(*a, **kw)

    monkeypatch.setattr(da, "EventEmitter", spy)
    s = AgentSettings(AGENT_NAME="red", BATTLEFIELD_URL="http://bf", INTERNAL_TOKEN="t", DRY_RUN=True)
    resp = await _Agent(s).run_turn(TURN)
    assert resp.ok
    budget = seen["flush_budget_sec"]
    assert budget == min(s.http_timeout_sec, 5.0)
    # stream timeout + final flush fits battlefield's TURN_TIMEOUT_SEC + 5 HTTP wait
    assert (s.turn_timeout_sec - 10) + budget <= s.turn_timeout_sec + 5
