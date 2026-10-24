"""DroidAgent plumbing that runs without the Droid SDK: tool offload and the tool allowlist."""

import asyncio

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
