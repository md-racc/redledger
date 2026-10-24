"""Mock HTTP contract evidence only: no SDK, database, or live integration claims."""

import asyncio
import copy
import json
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from preparation import MUTATIONS, decide_preparation, preparation_for

import tools
from agentkit import AgentSettings, LedgerClient, collect_tools
from agentkit.invocation import Invocation, ToolUse, UnverifiedInvocation, bind_invocation, bind_strict

MODES = ("off", "shadow", "enforce")
CASES = [
    ("match_invoice", {"invoice_id": "i", "po_id": "p"}, "invoices.match", "i", {"po_id": "p"}),
    ("approve_invoice", {"invoice_id": "i"}, "invoices.approve", "i", {}),
    ("reject_invoice", {"invoice_id": "i", "reason": "duplicate"}, "invoices.reject", "i", {"reason": "duplicate"}),
    ("pay_invoice", {"invoice_id": "i"}, "invoices.pay", "i", {}),
    ("approve_vendor_change", {"change_id": "c"}, "vendor_changes.approve", "c", {}),
    ("reject_vendor_change", {"change_id": "c", "reason": "obsolete"}, "vendor_changes.reject", "c", {"reason": "obsolete"}),
    ("approve_expense", {"expense_id": "e"}, "expenses.approve", "e", {}),
    ("pay_expense", {"expense_id": "e"}, "expenses.pay", "e", {}),
]
USE = ToolUse("sdk-id", "pay_invoice", {"invoice_id": "i"}, "permission")
SETTINGS = AgentSettings(_env_file=None, AGENT_NAME="green", BATTLEFIELD_URL="http://bf", AGENT_TOKEN="fixture", DRY_RUN=False)


def body(mode="enforce", **updates):
    result = {
        "preparation_id": "prep",
        "idempotency_key": USE.tool_use_id,
        "action": "invoices.pay",
        "entity_id": "i",
        "day": 3,
        "controller_mode": mode,
        "effective": "allow",
        "decided_by": "mode",
        "consumed": False,
        "expires_at": "2000-01-01T00:00:00Z",  # expiry is Battlefield's decision, not ours
    }
    result.update(updates)
    return result


async def decision(response, mode="enforce", use=USE):
    with respx.mock as router:
        route = router.post("http://bf/api/preparations")
        if isinstance(response, BaseException):
            route.mock(side_effect=response)
        else:
            route.mock(return_value=response)
        async with LedgerClient(SETTINGS, episode_id="ep", day=3) as ledger:
            result = await decide_preparation(ledger, use, mode)
        assert route.call_count == len(router.calls) == 1  # no reads, retries, execution, or Blue
        request = route.calls[0].request
        assert request.headers["X-Tool-Use-Id"] == use.tool_use_id
        assert request.headers["X-Agent"] == "green"
        assert request.headers["X-Episode"] == "ep" and request.headers["X-Day"] == "3"
        return result, request


@pytest.mark.parametrize(("tool", "args", "action", "entity", "payload"), CASES)
async def test_exact_mapping_and_single_prepare(tool, args, action, entity, payload):
    before = copy.deepcopy(args)
    mapped = preparation_for(tool, args)
    assert mapped.model_dump() == {"action": action, "entity_id": entity, "args": payload}
    use = ToolUse("sdk-id", tool, args, "stream")
    result, request = await decision(httpx.Response(200, json=body(action=action, entity_id=entity)), use=use)
    assert result.proceed and result.cause is None
    assert json.loads(request.content) == mapped.model_dump()
    assert args == before


def test_mapping_matches_registered_surface_exactly():
    assert {name for name, _, _ in collect_tools(tools)} == {*MUTATIONS, "ap_queue"}
    assert {row[0] for row in CASES} == set(MUTATIONS)
    assert preparation_for("ap_queue", {}) is None


BAD_CALLS = [
    ("gl_post", {}),
    ("unknown", {}),
    ("ap_queue", {"extra": "secret"}),
    ("pay_invoice", {}),
    ("pay_invoice", {"invoice_id": "i", "extra": "secret"}),
    ("pay_invoice", {"invoice_id": ""}),
    ("pay_invoice", {"invoice_id": "  "}),
    ("pay_invoice", {"invoice_id": 1}),
    ("pay_invoice", {"invoice_id": None}),
    ("match_invoice", {"invoice_id": "i", "po_id": False}),
    ("reject_invoice", {"invoice_id": "i", "reason": []}),
    ("reject_vendor_change", {"change_id": "c"}),
    ("pay_expense", []),
]


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(("tool", "args"), BAD_CALLS)
async def test_bad_calls_refuse_before_io(mode, tool, args):
    with respx.mock as router:
        async with LedgerClient(SETTINGS, episode_id="ep", day=3) as ledger:
            result = await decide_preparation(ledger, ToolUse("sdk-id", tool, args, "permission"), mode)
        assert not result.proceed and result.cause == "invalid_state"
        assert not router.calls
        assert "secret" not in result.comment


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(("source", "identity"), [("local", "id"), ("explicit", "id"), ("permission", ""), ("stream", " "), ("unknown", "id")])
@pytest.mark.parametrize("readonly", [False, True])
async def test_unverified_identity_refuses_even_reads(mode, source, identity, readonly):
    use = ToolUse(identity, "ap_queue" if readonly else USE.tool, {} if readonly else USE.args, source)
    with respx.mock as router:
        async with LedgerClient(SETTINGS, episode_id="ep", day=3) as ledger:
            result = await decide_preparation(ledger, use, mode)
        assert not result.proceed and result.cause == "integration_failure"
        assert not router.calls


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("source", ["permission", "stream", "mcp_meta"])
async def test_readonly_allows_without_preparing(mode, source):
    with respx.mock as router:
        async with LedgerClient(SETTINGS, episode_id="ep", day=3) as ledger:
            result = await decide_preparation(ledger, ToolUse("sdk-id", "ap_queue", {}, source), mode)
        assert result.proceed and not router.calls


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    ("updates", "cause"),
    [
        ({"effective": "allow", "verdict": "block", "decided_by": "gate"}, None),
        ({"effective": "block", "decided_by": "gate"}, "control_hold"),
        ({"effective": "block", "decided_by": "human"}, "control_hold"),
        ({"effective": "block", "decided_by": "timeout"}, "escalation_timeout"),
        ({"effective": "block", "decided_by": "gate", "cause": "gate_unavailable"}, "control_hold"),
    ],
)
async def test_effective_not_verdict_controls_decision(mode, updates, cause):
    result, _ = await decision(httpx.Response(200, json=body(mode, reason="stored decision", **updates)), mode)
    assert result.proceed == (cause is None)
    assert result.cause == cause
    if cause:
        assert json.loads(result.comment) == {"cause": cause, "reason": "stored decision", "verdict_cause": updates.get("cause")}


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    ("status", "error", "cause"),
    [
        (404, "secret", "invalid_state"),
        (422, "secret", "invalid_state"),
        (409, "invalid_state", "invalid_state"),
        (409, "idempotency key reused for a different action", "integration_failure"),
        (409, "no active turn for this agent", "integration_failure"),
        (409, "other secret", "integration_failure"),
        (400, "secret", "integration_failure"),
    ],
)
async def test_terminal_http_errors_never_allow(mode, status, error, cause):
    result, _ = await decision(httpx.Response(status, json={"error": error, "detail": "secret"}), mode)
    assert not result.proceed and result.cause == cause
    assert "secret" not in result.comment


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("failure", ["401", "403", "500", "503", "timeout", "network", "raw", "null", "missing", "bad_type", "empty"])
async def test_availability_and_malformed_body_fallback(mode, failure):
    if failure.isdigit():
        response = httpx.Response(int(failure), json={"error": "secret"})
    else:
        response = {
            "timeout": httpx.ReadTimeout("secret"),
            "network": httpx.ConnectError("secret"),
            "raw": httpx.Response(200, text="secret"),
            "null": httpx.Response(200, json=None),
            "missing": httpx.Response(200, json={"reason": "secret"}),
            "bad_type": httpx.Response(200, json=body(mode, effective=42)),
            "empty": httpx.Response(200),
        }[failure]
    result, _ = await decision(response, mode)
    assert result.proceed == (mode != "enforce")
    assert result.cause == ("integration_failure" if mode == "enforce" else None)
    assert "secret" not in result.comment


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    "updates",
    [
        {"idempotency_key": "wrong"},
        {"action": "expenses.pay"},
        {"entity_id": "wrong"},
        {"day": 4},
        {"controller_mode": "wrong"},
        {"consumed": True},
        {"effective": "pending", "decided_by": None},
        {"decided_by": None},
        {"effective": "pending", "decided_by": "gate"},
    ],
)
async def test_unusable_or_misbound_preparations_follow_malformed_table(mode, updates):
    if updates == {"controller_mode": "wrong"}:
        updates = {"controller_mode": "off" if mode != "off" else "enforce"}
    result, _ = await decision(httpx.Response(200, json=body(mode, **updates)), mode)
    assert result.proceed == (mode != "enforce")
    assert result.cause == ("integration_failure" if mode == "enforce" else None)


@pytest.mark.parametrize("mode", MODES)
async def test_shared_identity_refusal_is_not_availability_fallback(mode):
    ledger = AsyncMock(spec=LedgerClient)
    ledger.prepare.side_effect = UnverifiedInvocation("secret")
    result = await decide_preparation(ledger, USE, mode)
    assert not result.proceed and result.cause == "integration_failure"
    assert "secret" not in result.comment
    ledger.prepare.assert_awaited_once()


@pytest.mark.parametrize("mode", MODES)
async def test_task_cancellation_propagates(mode):
    ledger = AsyncMock(spec=LedgerClient)
    ledger.prepare.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await decide_preparation(ledger, USE, mode)
    ledger.prepare.assert_awaited_once()


@pytest.mark.parametrize("source", ["permission", "stream", "mcp_meta"])
async def test_prepare_preserves_first_write_key_in_verified_strict_context(source):
    use = ToolUse(USE.tool_use_id, USE.tool, USE.args, source)
    inv = Invocation(use.tool_use_id, use.tool, source=source)
    with respx.mock as router:
        prepare = router.post("http://bf/api/preparations").respond(200, json=body("off"))
        execute = router.post("http://bf/api/invoices/i/pay").respond(200, json={"id": "payment"})
        async with LedgerClient(SETTINGS, episode_id="ep", day=3) as ledger:
            with bind_strict(True), bind_invocation(inv):
                result = await decide_preparation(ledger, use, "off")
                assert result.proceed and inv.keys == []
                assert len(router.calls) == 1
                await ledger.pay_invoice("i")
        assert inv.keys == ["sdk-id"]
        assert prepare.call_count == execute.call_count == 1 and len(router.calls) == 2
        assert prepare.calls[0].request.headers["X-Tool-Use-Id"] == execute.calls[0].request.headers["X-Tool-Use-Id"] == "sdk-id"
