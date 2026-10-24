"""Pinned configuration units, not SDK permission or restriction-enforcement evidence."""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from conftest import REQ, S

from agent import AP_TOOL_IDS, GreenAgent
from agentkit import DroidAgent

EXPECTED = (
    "green-ledger___ap_queue",
    "green-ledger___approve_expense",
    "green-ledger___approve_invoice",
    "green-ledger___approve_vendor_change",
    "green-ledger___match_invoice",
    "green-ledger___pay_expense",
    "green-ledger___pay_invoice",
    "green-ledger___reject_invoice",
    "green-ledger___reject_vendor_change",
)


def test_observed_ids_are_immutable_and_each_list_is_fresh(monkeypatch):
    monkeypatch.setitem(sys.modules, "droid_sdk", None)
    first, second = GreenAgent(S), GreenAgent(S)
    assert isinstance(AP_TOOL_IDS, tuple) and AP_TOOL_IDS == EXPECTED
    expected = first._expected_tool_ids()
    assert first._tool_ids == second._tool_ids == expected == list(EXPECTED)
    assert first._tool_ids is not second._tool_ids and expected is not first._tool_ids
    expected.clear()
    first._tool_ids.clear()
    assert second._tool_ids == first._expected_tool_ids() == list(EXPECTED)
    assert first.autonomy == "off" and first.identity_policy() == "strict"


async def test_first_session_receives_pins_before_any_discovery(monkeypatch):
    agent = GreenAgent(S.model_copy(update={"dry_run": False}))
    captured = {}

    class BeforeSession(Exception):
        pass

    def session(**kwargs):
        captured.update(kwargs)
        raise BeforeSession

    fake = SimpleNamespace(
        Session=session,
        SessionConfig=lambda **kwargs: SimpleNamespace(**kwargs),
        InteractionHandlers=lambda **kwargs: SimpleNamespace(**kwargs),
        ReasoningEffort=lambda value: value,
        **dict.fromkeys(("TextDelta", "ThinkingDelta", "ToolCall", "ToolCallDelta", "ToolResult"), object),
    )
    monkeypatch.setitem(sys.modules, "droid_sdk", fake)
    monkeypatch.setattr(agent, "_autonomy", lambda: "off")
    monkeypatch.setattr(agent, "_mcp_server", lambda registry: object())
    monkeypatch.setattr(agent, "tools", lambda: [])  # Never derive guessed IDs from tool names.
    with pytest.raises(BeforeSession):
        # Test shared configuration only; Green's production override remains hard-guarded.
        await DroidAgent._droid_turn(agent, REQ, SimpleNamespace())
    config = captured["config"]
    assert config.restrict_tools == list(EXPECTED) and config.disable_builtin_skills is True
    assert config.autonomy == "off" and agent._strict_live()


@pytest.mark.parametrize("difference", ["none", "missing", "extra"])
async def test_strict_discovery_requires_exact_pinned_ids(difference):
    agent = GreenAgent(S.model_copy(update={"dry_run": False}))
    ids = list(EXPECTED)
    if difference == "missing":
        ids.pop()
    elif difference == "extra":
        ids.append("green-ledger___unapproved")
    session = SimpleNamespace(list_tools=AsyncMock(return_value=[SimpleNamespace(id=value) for value in ids]))
    if difference == "none":
        await agent._learn_tool_ids(session)
        assert agent._tool_ids == list(EXPECTED)
    else:
        with pytest.raises(RuntimeError, match="strict identity: tool IDs differ"):
            await agent._learn_tool_ids(session)
