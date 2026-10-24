"""Strict tool-call identity (integration design B-1/B-3/B-7, D7/D8): a strict agent's live execution runs
only under an unambiguous SDK-reported tool_use_id; best_effort (red today) and DRY_RUN are unchanged."""

from __future__ import annotations

import json
import types

import pytest
import respx
from test_invocation import FakeRequest, Recorder, _Agent, keys, ledger_routes, mcp_action, offloaded, pay_invoice

from agentkit import AgentSettings
from agentkit.invocation import SOURCE_MCP_META, SOURCE_STREAM

LIVE = AgentSettings(AGENT_NAME="green", BATTLEFIELD_URL="http://bf", INTERNAL_TOKEN="t")
DRY = AgentSettings(AGENT_NAME="green", BATTLEFIELD_URL="http://bf", INTERNAL_TOKEN="t", DRY_RUN=True)


class _Strict(_Agent):
    identity = "strict"


class _RedLike(_Agent):
    """Red today: Autonomy.HIGH, no identity set, so best_effort."""

    name = "red"
    autonomy = "high"
    identity = None


def _refusal(rec: Recorder) -> tuple[str, dict]:
    (call, result) = rec.events
    assert call[0] == "tool_call" and result[0] == "tool_result" and call[1] == result[1] and result[2] is False
    return result[1], json.loads(result[3])


def test_policy_defaults_strict_at_autonomy_off_and_best_effort_otherwise():
    off = type("Off", (_Agent,), {"identity": None})(LIVE)
    assert off.identity_policy() == "strict"
    assert _RedLike(LIVE).identity_policy() == "best_effort"
    with pytest.raises(ValueError):
        type("Bad", (_Agent,), {"identity": "lenient"})(LIVE).identity_policy()


@respx.mock
async def test_unlinked_execution_never_runs_and_gets_one_pair_under_a_local_id():
    route = ledger_routes()
    agent, rec = _Strict(LIVE), Recorder()
    reg = agent._new_registry(rec)
    out = json.loads(await offloaded(agent, pay_invoice, rec, registry=reg, invoice_id="inv_1"))
    assert out == {"error": True, "identity": "unverified", "not_run": True, "tool": "pay_invoice", "detail": "no verified tool_use_id for this call"}
    local, body = _refusal(rec)
    assert len(local) == 32 and body["not_run"] is True
    assert keys(route) == []  # nothing reached the ledger
    reg.close()
    assert len(rec.events) == 2  # the refusal was not left claimable for a late ToolCall


@respx.mock
async def test_explicit_tool_use_id_is_refused_live():
    route = ledger_routes()
    agent, rec = _Strict(LIVE), Recorder()
    out = json.loads(await offloaded(agent, pay_invoice, rec, registry=agent._new_registry(rec), invoice_id="inv_1", _tool_use_id="mine"))
    assert out["identity"] == "explicit" and out["not_run"] is True
    assert keys(route) == [] and _refusal(rec)[0] != "mine"


@respx.mock
async def test_two_approved_identical_calls_are_both_refused_and_both_ids_closed_not_run():
    route = ledger_routes()
    agent, rec = _Strict(LIVE), Recorder()
    reg = agent._new_registry(rec)
    req = FakeRequest(actions=(mcp_action("t1", "pay_invoice", {"invoice_id": "inv_1"}), mcp_action("t2", "pay_invoice", {"invoice_id": "inv_1"})))
    await agent._permission_entry(reg, req)  # both approved
    for _ in range(2):
        assert json.loads(await offloaded(agent, pay_invoice, rec, registry=reg, invoice_id="inv_1"))["identity"] == "ambiguous"
    assert keys(route) == []
    reg.close()
    closed = {e[1]: json.loads(e[3]) for e in rec.events if e[0] == "tool_result" and e[1] in {"t1", "t2"}}
    assert set(closed) == {"t1", "t2"} and all(b["not_run"] for b in closed.values())


@respx.mock
async def test_one_approved_call_runs_under_its_permission_id():
    route = ledger_routes()
    agent, rec = _Strict(LIVE), Recorder()
    reg = agent._new_registry(rec)
    await agent._permission_entry(reg, FakeRequest(actions=(mcp_action("t1", "pay_invoice", {"invoice_id": "inv_1"}),)))
    await offloaded(agent, pay_invoice, rec, registry=reg, invoice_id="inv_1")
    assert keys(route) == ["t1"]
    assert [e[1] for e in rec.events] == ["t1", "t1"]


@respx.mock
async def test_a_hint_naming_another_call_conflicts_with_the_arguments(monkeypatch):
    import agentkit.droid_agent as da

    route = ledger_routes()
    agent, rec = _Strict(LIVE), Recorder()
    reg = agent._new_registry(rec)
    await agent._permission_entry(reg, FakeRequest(actions=(mcp_action("t1", "pay_invoice", {"invoice_id": "inv_1"}),)))
    await agent._permission_entry(reg, FakeRequest(actions=(mcp_action("t2", "pay_invoice", {"invoice_id": "inv_2"}),)))
    monkeypatch.setattr(da, "_mcp_request_hints", lambda agent: ["t1"])  # _meta says t1, arguments say t2
    out = json.loads(await offloaded(agent, pay_invoice, rec, registry=reg, invoice_id="inv_2"))
    assert out["identity"] == "conflicting" and keys(route) == []


def test_a_hint_that_agrees_with_the_arguments_links_with_source_mcp_meta():
    agent = _Strict(LIVE)
    reg = agent._new_registry(None)
    reg.observe("t1", "green-ledger___pay_invoice", {"invoice_id": "inv_1"}, SOURCE_STREAM)
    reg.permission_resolved("t1", approved=True)
    use, reason = reg.claim_checked("pay_invoice", {"invoice_id": "inv_1"}, ["assembly-123", "t1"])
    assert reason is None and use.tool_use_id == "t1" and use.source == SOURCE_MCP_META


@respx.mock
async def test_dry_run_keeps_uuid4_for_a_strict_agent():
    route = ledger_routes()
    agent, rec = _Strict(DRY), Recorder()
    await offloaded(agent, pay_invoice, rec, registry=agent._new_registry(rec), invoice_id="inv_1")
    (key,) = keys(route)
    assert len(key) == 32  # ran, under a UUID4, exactly as before


@respx.mock
async def test_red_best_effort_is_unchanged_an_unlinked_call_still_runs_under_a_uuid4():
    route = ledger_routes()
    agent, rec = _RedLike(LIVE), Recorder()
    reg = agent._new_registry(rec)
    out = await offloaded(agent, pay_invoice, rec, registry=reg, invoice_id="inv_1")
    (key,) = keys(route)
    assert len(key) == 32 and "identity" not in out
    assert [e[0] for e in rec.events] == ["tool_call", "tool_result"] and rec.events[1][2] is True


def test_tool_uses_without_a_turn_registry_raises_live_and_works_in_dry_run():
    req = FakeRequest(actions=(mcp_action("t1", "pay_invoice", {"invoice_id": "inv_1"}),))
    with pytest.raises(RuntimeError):
        _Strict(LIVE).tool_uses(req)
    assert [u.tool_use_id for u in _Strict(DRY).tool_uses(req)] == ["t1"]


class _Session:
    def __init__(self, ids):
        self.ids = ids

    async def list_tools(self):
        return [types.SimpleNamespace(id=i) for i in self.ids]


def _expected(agent):
    return [f"{agent.name}-ledger___{n}" for (n, _, _) in agent.tools()]


async def test_strict_fails_the_turn_on_a_missing_or_extra_tool_id():
    agent = _Strict(LIVE)
    exact = _expected(agent)
    await agent._learn_tool_ids(_Session(exact + ["other-ledger___x", "Read"]))  # other servers' tools are not ours
    assert agent._tool_ids == exact
    with pytest.raises(RuntimeError, match="missing"):
        await agent._learn_tool_ids(_Session(exact[1:]))
    with pytest.raises(RuntimeError, match="extra"):
        await agent._learn_tool_ids(_Session(exact + ["green-ledger___pay_invoice_v2"]))  # a suffix match is not a match


async def test_best_effort_keeps_exact_ids_and_only_logs_a_mismatch():
    agent = _RedLike(LIVE)
    exact = _expected(agent)
    await agent._learn_tool_ids(_Session(exact))
    assert agent._tool_ids == exact  # the observed `<server>___<tool>` IDs: identical restrict_tools to before
    agent._tool_ids = None
    await agent._learn_tool_ids(_Session(exact + ["red-ledger___xpay_invoice"]))  # suffix-only: no longer adopted
    assert agent._tool_ids == exact


def test_approval_threshold_defaults_and_reads_the_env(monkeypatch):
    from decimal import Decimal

    assert AgentSettings(AGENT_NAME="red").approval_threshold == Decimal("5000")
    monkeypatch.setenv("APPROVAL_THRESHOLD", "7500.50")
    assert AgentSettings(AGENT_NAME="red").approval_threshold == Decimal("7500.50")


async def test_best_effort_survives_an_unreadable_listing_and_strict_fails_on_it():
    bad = types.SimpleNamespace(list_tools=None)

    async def listing():
        return [types.SimpleNamespace(name="no id attribute")]

    bad.list_tools = listing
    red = _RedLike(LIVE)
    await red._learn_tool_ids(bad)  # logged list_tools_failed, turn continues
    assert red._tool_ids is None
    with pytest.raises(RuntimeError, match="list_tools failed"):
        await _Strict(LIVE)._learn_tool_ids(bad)
