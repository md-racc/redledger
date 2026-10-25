"""Streamed tool arguments (CLI 0.249.0 + gpt-5.x): the CLI reports a call at detection with the input
known so far (`{}`), then again with the full input, both as ToolCallDelta under one id, and the permission
request carries the full input. Identity must bind to the full arguments, never to the first sighting."""

from __future__ import annotations

import json

import respx
from test_invocation import FakeRequest, Recorder, keys, ledger_routes, mcp_action, offloaded, pay_invoice
from test_strict_identity import LIVE, _Strict

from agentkit.invocation import (
    REFUSE_AMBIGUOUS,
    REFUSE_CONFLICTING,
    REFUSE_UNVERIFIED,
    SOURCE_PERMISSION,
    SOURCE_STREAM,
    InvocationRegistry,
)


def t(a: int) -> str:  # a tool with a required argument (like blue's raise_flag(finding_id))
    return ""


def n() -> str:  # a no-argument tool (like blue's post_report)
    return ""


def _reg(*, strict_off: bool = True, emitter=None) -> InvocationRegistry:
    return InvocationRegistry("x-ledger", [("t", t), ("n", n)], emitter, require_permission=strict_off)


def _ask(reg: InvocationRegistry, tool_use_id: str, tool: str, args: dict, approve: bool = True):
    (use,) = reg.observe_permission(FakeRequest(actions=(mcp_action(tool_use_id, tool, args, server="x-ledger"),)))
    reg.permission_resolved(use.tool_use_id, approved=approve)
    return use


def _stream(reg: InvocationRegistry, tool_use_id: str, tool: str, args: dict):
    return reg.observe(tool_use_id, f"x-ledger___{tool}", args, SOURCE_STREAM)


# (1) the prod failure: start `{}`, progress with the full input, permission with the full input
def test_streamed_empty_start_then_full_args_links_under_the_permission_args():
    reg = _reg()
    _stream(reg, "id1", "t", {})
    assert reg.claim_checked("t", {}) == (None, REFUSE_UNVERIFIED)  # tentative: never claimable under None
    _stream(reg, "id1", "t", {"a": 1})
    assert reg.claim_checked("t", {"a": 1}) == (None, REFUSE_UNVERIFIED)  # not yet approved (Autonomy.OFF)
    use = _ask(reg, "id1", "t", {"a": 1})
    assert use.args == {"a": 1}  # what a mirror handler (tool_uses) sees: the full arguments, not `{}`
    got, reason = reg.claim_checked("t", {"a": 1})
    assert reason is None and got.tool_use_id == "id1" and got.args == {"a": 1}


def test_permission_alone_completes_a_streamed_empty_start():
    reg = _reg()
    _stream(reg, "id1", "t", {})
    _ask(reg, "id1", "t", {"a": 1})
    got, reason = reg.claim_checked("t", {"a": 1})
    assert reason is None and got.tool_use_id == "id1"


# (2) no-argument control
def test_no_arg_tool_is_unchanged():
    reg = _reg()
    _stream(reg, "id1", "n", {})
    _stream(reg, "id1", "n", {})
    _ask(reg, "id1", "n", {})
    got, reason = reg.claim_checked("n", {})
    assert reason is None and got.tool_use_id == "id1"
    assert reg.claim_checked("n", {}) == (None, REFUSE_UNVERIFIED)  # claimed once


# (3) Gemini-style: complete input at detection
def test_full_args_at_detection_still_link():
    reg = _reg()
    _stream(reg, "id1", "t", {"a": 1})
    _ask(reg, "id1", "t", {"a": 1})
    got, reason = reg.claim_checked("t", {"a": 1})
    assert reason is None and got.tool_use_id == "id1"


# (4) after approval or claim, other arguments never re-key the call
def test_other_args_after_approval_are_a_conflict_and_the_call_is_refused():
    reg = _reg()
    _stream(reg, "id1", "t", {})
    _ask(reg, "id1", "t", {"a": 1})
    use = _stream(reg, "id1", "t", {"a": 2})
    assert use.args == {"a": 1}  # not re-keyed
    assert reg.claim_checked("t", {"a": 2}) == (None, REFUSE_CONFLICTING)
    assert reg.claim_checked("t", {"a": 1}) == (None, REFUSE_CONFLICTING)  # which one would run is unknown: refuse
    _stream(reg, "id1", "t", {})  # a partial (invalid) sighting is never authoritative, conflict or not
    assert reg.claim_checked("t", {"a": 1}) == (None, REFUSE_CONFLICTING)


def test_other_args_after_claim_never_re_key_and_keep_one_pair():
    rec = Recorder()
    reg = _reg(emitter=rec)
    _ask(reg, "id1", "t", {"a": 1})
    assert reg.claim_checked("t", {"a": 1})[0].tool_use_id == "id1"
    assert _stream(reg, "id1", "t", {"a": 2}).args == {"a": 1}
    assert reg.claim_checked("t", {"a": 2}) == (None, REFUSE_UNVERIFIED)
    reg.finished("id1", True)
    reg.close()
    assert rec.events == []  # the execution narrates id1; the late sighting adds nothing


# (5) permission arguments differ from the last stream arguments: bound to the permission arguments
def test_permission_args_override_earlier_stream_args():
    reg = _reg()
    _stream(reg, "id1", "t", {})
    _stream(reg, "id1", "t", {"a": 1})
    _ask(reg, "id1", "t", {"a": 2})
    assert reg.claim_checked("t", {"a": 1}) == (None, REFUSE_UNVERIFIED)  # the stale stream args lend no id
    got, reason = reg.claim_checked("t", {"a": 2})
    assert reason is None and got.tool_use_id == "id1" and got.args == {"a": 2} and got.source == SOURCE_PERMISSION


def test_stream_args_contradicting_the_permission_afterwards_refuse_it():
    reg = _reg()
    _ask(reg, "id1", "t", {"a": 2})
    _stream(reg, "id1", "t", {"a": 1})
    assert reg.claim_checked("t", {"a": 2}) == (None, REFUSE_CONFLICTING)
    assert reg.claim_checked("t", {"a": 1}) == (None, REFUSE_CONFLICTING)


# (6) two ids, same tool and arguments: still ambiguous (strict) / FIFO (best effort)
def test_identical_streamed_calls_stay_ambiguous_and_are_closed_not_run():
    rec = Recorder()
    reg = _reg(emitter=rec)
    for tid in ("id1", "id2"):
        _stream(reg, tid, "t", {})
        _stream(reg, tid, "t", {"a": 1})
        _ask(reg, tid, "t", {"a": 1})
    assert reg.claim_checked("t", {"a": 1}) == (None, REFUSE_AMBIGUOUS)
    reg.close()
    closed = {e[1]: json.loads(e[3]) for e in rec.events if e[0] == "tool_result"}
    assert set(closed) == {"id1", "id2"} and all(b["not_run"] for b in closed.values())


def test_best_effort_identical_streamed_calls_are_fifo():
    reg = _reg(strict_off=False)
    for tid in ("id1", "id2"):
        _stream(reg, tid, "t", {})
    for tid in ("id1", "id2"):
        _stream(reg, tid, "t", {"a": 1})
    assert reg.claim("t", {"a": 1}).tool_use_id == "id1"
    assert reg.claim("t", {"a": 1}).tool_use_id == "id2"
    assert reg.claim("t", {"a": 1}) is None


# tentative entries in best effort (red: Autonomy.HIGH, the stream is the only source)
def test_best_effort_never_claims_a_tentative_entry_and_links_it_once_complete():
    rec = Recorder()
    reg = _reg(strict_off=False, emitter=rec)
    _stream(reg, "id1", "t", {})
    assert reg.claim("t", {"a": 1}, hints=["id1"]) is None  # not even by hint while its arguments are invalid
    reg.note_unlinked("t", {"a": 1}, "local1")  # so it ran under a local id
    reg.finished("local1", True)
    _stream(reg, "id1", "t", {"a": 1})  # the full input arrives: the late ToolCall links to that run
    reg.close()
    assert [(e[0], e[1]) for e in rec.events] == [("tool_call", "id1"), ("tool_result", "id1")]
    assert json.loads(rec.events[1][3])["ran_as"] == "local1" and rec.events[1][2] is True


def test_unknown_id_is_still_refused():
    reg = _reg()
    _stream(reg, "id1", "t", {})
    _ask(reg, "id1", "t", {"a": 1})
    assert reg.claim_checked("t", {"a": 3}) == (None, REFUSE_UNVERIFIED)


# end to end through the agent: strict live green, streamed start, permission, MCP execution
@respx.mock
async def test_strict_agent_runs_a_streamed_call_under_its_sdk_id():
    route = ledger_routes()
    agent, rec = _Strict(LIVE), Recorder()
    reg = agent._new_registry(rec)
    reg.observe("toolu_1", "green-ledger___pay_invoice", {}, SOURCE_STREAM)  # tool-call-start
    reg.observe("toolu_1", "green-ledger___pay_invoice", {"invoice_id": "inv_1"}, SOURCE_STREAM)  # tool-call-progress
    await agent._permission_entry(reg, FakeRequest(actions=(mcp_action("toolu_1", "pay_invoice", {"invoice_id": "inv_1"}),)))
    out = await offloaded(agent, pay_invoice, rec, registry=reg, invoice_id="inv_1")
    assert "not_run" not in json.loads(out)
    assert keys(route) == ["toolu_1"]
    assert [(e[0], e[1]) for e in rec.events] == [("tool_call", "toolu_1"), ("tool_result", "toolu_1")]
