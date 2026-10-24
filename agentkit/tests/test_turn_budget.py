"""Timeouts around a held escalation: LedgerClient's read timeout and the turn-wide tool budget."""

import asyncio
import json
import time

import structlog

import agentkit.droid_agent as da
from agentkit import AgentSettings, DroidAgent, LedgerClient, TurnRequest, ctx, ledger_tool

S = AgentSettings(AGENT_NAME="green", BATTLEFIELD_URL="http://bf", INTERNAL_TOKEN="t")
TURN = TurnRequest(episode_id="ep_1", day=3, controller_mode="enforce")


@ledger_tool("held", "Stands in for a gated write battlefield holds for a human.")
async def held() -> str:
    await asyncio.sleep(3600)
    return "unreachable"


class _Agent(DroidAgent):
    name = "green"
    seen_deadline: float | None = None

    def tools(self):
        return [("held", "held", held)]

    async def build_prompt(self, req):
        return ""

    async def dry_run_turn(self, req):
        type(self).seen_deadline = da._tool_deadline.get()
        return ""


# ---------- LedgerClient read timeout ----------


def test_read_timeout_outlasts_the_escalation_hold_plus_the_gate():
    assert LedgerClient.read_timeout_sec(S) == 90 + 8 + 15  # defaults
    slow_judge = AgentSettings(AGENT_NAME="green", ESCALATION_TIMEOUT_SEC=300, GATE_TIMEOUT_SEC=8)
    assert LedgerClient.read_timeout_sec(slow_judge) == 323  # follows the hold; the old fixed 120 s did not
    fast = AgentSettings(AGENT_NAME="green", ESCALATION_TIMEOUT_SEC=1, GATE_TIMEOUT_SEC=1, HTTP_TIMEOUT_SEC=60)
    assert LedgerClient.read_timeout_sec(fast) == 60  # never below the plain HTTP timeout


async def test_client_uses_it():
    s = AgentSettings(AGENT_NAME="green", ESCALATION_TIMEOUT_SEC=200)
    async with LedgerClient(s, episode_id="ep_1", day=0) as L:
        assert L.c.timeout.read == 200 + 8 + 15 and L.c.timeout.connect == s.http_timeout_sec


# ---------- tool budget clamped to the turn ----------


def test_budget_outside_a_turn_is_the_per_call_cap():
    agent = _Agent(S)
    assert agent._tool_budget_sec("held") == agent._tool_timeout_sec() == 160


def test_budget_is_clamped_to_the_turn_and_warns_below_the_hold():
    agent = _Agent(S)
    tok = da._tool_deadline.set(time.monotonic() + 1000)
    try:
        assert agent._tool_budget_sec("held") == 160  # plenty left: the cap
    finally:
        da._tool_deadline.reset(tok)
    tok = da._tool_deadline.set(time.monotonic() + 40)
    try:
        with structlog.testing.capture_logs() as logs:
            b = agent._tool_budget_sec("held")
    finally:
        da._tool_deadline.reset(tok)
    assert 39 < b <= 40
    assert [e["event"] for e in logs] == ["tool_budget_below_escalation_hold"] and logs[0]["tool"] == "held"
    tok = da._tool_deadline.set(time.monotonic() - 5)  # already spent: still gets the floor
    try:
        assert agent._tool_budget_sec("held") == da._MIN_TOOL_SEC
    finally:
        da._tool_deadline.reset(tok)


async def test_run_turn_sets_the_deadline_to_turn_start_plus_the_cap():
    s = AgentSettings(AGENT_NAME="green", BATTLEFIELD_URL="http://bf", INTERNAL_TOKEN="t", DRY_RUN=True)
    agent = _Agent(s)
    t0 = time.monotonic()
    assert (await agent.run_turn(TURN)).ok
    assert agent.seen_deadline is not None and t0 + 160 <= agent.seen_deadline <= time.monotonic() + 160
    assert da._tool_deadline.get() is None  # reset after the turn


async def test_a_second_held_call_cannot_push_the_turn_past_its_window(monkeypatch):
    """Two calls that each hang until cut off: the first spends the turn's tool window, the second gets
    only what is left (the floor), so together they end near the window, not at 2x the per-call cap."""
    monkeypatch.setattr(da, "_MIN_TOOL_SEC", 0.05)
    monkeypatch.setattr(_Agent, "_tool_timeout_sec", lambda self: 0.6)
    agent = _Agent(S)
    sync_tool = agent._offload(held)
    async with LedgerClient(S, episode_id=TURN.episode_id, day=TURN.day) as ledger:
        tokens = ctx.bind(ledger, None, TURN)
        dtok = da._tool_deadline.set(time.monotonic() + 0.6)
        t0 = time.monotonic()
        try:
            first = json.loads(sync_tool())
            second = json.loads(sync_tool())
        finally:
            da._tool_deadline.reset(dtok)
            ctx.unbind(tokens)
        elapsed = time.monotonic() - t0
    assert first["timeout"] and second["timeout"]
    assert elapsed < 0.6 + 0.4  # unclamped this would be 1.2 s
    assert first["detail"].startswith("tool timed out after 0.6s") and second["detail"].startswith("tool timed out after 0.")
