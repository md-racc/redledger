"""Guarded permission adapter units; fake enums/HTTP are not live SDK evidence."""

import asyncio
import json
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from conftest import REQ, invoice
from test_invocation_adapter import adapter_turn, permission

import tools
from agentkit import ctx
from agentkit.invocation import bind_strict

MODES = ("off", "shadow", "enforce")
KEY = ("invoice", "i")


def prepared(mode, **updates):
    body = {
        "preparation_id": "prep",
        "idempotency_key": "sdk-id",
        "controller_mode": mode,
        "day": 3,
        "action": "invoices.pay",
        "entity_id": "i",
        "effective": "allow",
        "decided_by": "mode",
        "expires_at": "2100-01-01T00:00:00Z",
        "consumed": False,
    }
    body.update(updates)
    return httpx.Response(200, json=body)


@asynccontextmanager
async def permission_turn(monkeypatch, mode="enforce"):
    events = []

    def capture(request):
        events.extend(json.loads(request.content))
        return httpx.Response(202, json={"accepted": 1})

    with respx.mock as router:
        router.post("http://bf/api/events").mock(side_effect=capture)
        async with adapter_turn(monkeypatch) as (agent, registry, clerk):
            monkeypatch.setitem(
                sys.modules,
                "droid_sdk",
                SimpleNamespace(
                    ToolConfirmationOutcome=SimpleNamespace(CANCEL="cancel", PROCEED_ONCE="proceed_once"),
                ),
            )
            tokens = ctx.bind(ctx.ledger(), ctx.emitter(), REQ.model_copy(update={"controller_mode": mode}))
            try:
                yield agent, registry, clerk, router, events
            finally:
                ctx.unbind(tokens)


def cancelled(events, ids, cause):
    assert [(event["type"], event["payload"]["tool_use_id"]) for event in events] == [
        (kind, identity) for identity in ids for kind in ("agent.tool_call", "agent.tool_result")
    ]
    for event in events[1::2]:
        assert event["payload"]["ok"] is False
        summary = json.loads(event["payload"]["summary"])
        assert summary["cancelled"] is True
        assert json.loads(summary["reason"])["cause"] == cause


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("entry", [False, True])
@pytest.mark.parametrize("case", ["allow", "block", "timeout", "invalid", "conflict", "auth", "network", "malformed", "pending", "infra"])
async def test_permission_decision_table_and_cancel_pairs(monkeypatch, mode, entry, case):
    async with permission_turn(monkeypatch, mode) as (agent, registry, clerk, router, events):
        route = router.post("http://bf/api/preparations")
        if case == "network":
            route.mock(side_effect=httpx.ConnectError("private credential"))
        else:
            responses = {
                "allow": prepared(mode, verdict="block" if mode == "shadow" else None),
                "block": prepared(mode, effective="block", decided_by="gate", reason="stored hold"),
                "timeout": prepared(mode, effective="block", decided_by="timeout", reason="stored timeout"),
                "invalid": httpx.Response(409, json={"error": "invalid_state", "detail": "private account"}),
                "conflict": httpx.Response(409, json={"error": "idempotency key reused for a different action", "detail": "private account"}),
                "auth": httpx.Response(401, json={"detail": "private credential"}),
                "malformed": httpx.Response(200, text="private credential"),
                "pending": prepared(mode, effective="pending", decided_by=None),
                "infra": prepared(mode, effective="block", decided_by="timeout", cause="gate_unavailable", reason="stored unavailable"),
            }
            route.mock(return_value=responses[case])
        request = permission("pay_invoice", "sdk-id", {"invoice_id": "i"})
        agent.tool_uses(request)  # direct handler calls also use the real bound registry
        response = await (agent._permission_entry(registry, request) if entry else agent.on_permission(request))
        cause = {
            "block": "control_hold",
            "timeout": "escalation_timeout",
            "invalid": "invalid_state",
            "conflict": "integration_failure",
            "infra": "escalation_timeout",
        }.get(case)
        if case in ("auth", "network", "malformed", "pending") and mode == "enforce":
            cause = "integration_failure"
        assert response.selected_option == ("cancel" if cause else "proceed_once")
        assert route.call_count == 1 and len(router.calls) == 1  # no execution, retries, reads or Blue
        assert route.calls[0].request.headers["X-Tool-Use-Id"] == "sdk-id"
        assert not clerk.confirmed and not clerk.attempted
        if cause:
            assert json.loads(response.comment)["cause"] == cause and "private" not in response.comment
            assert clerk.cancellations == {cause: {KEY}}
            assert bool(clerk.blocked) == (case in ("block", "timeout"))
            assert bool(clerk.failures) == (cause == "integration_failure" or case == "infra")
            assert bool(clerk.deferred) == (cause == "invalid_state")
            assert "paid $0.00" in clerk.summary()
            if case == "infra":
                assert json.loads(response.comment)["verdict_cause"] == "gate_unavailable"
                assert "blocked 0" in clerk.summary() and "gate_unavailable 1" in clerk.summary()
        else:
            assert not clerk.cancellations and "cancellations" not in clerk.summary()
    if entry and cause:
        cancelled(events, ["sdk-id"], cause)


@pytest.mark.parametrize("mode", MODES)
async def test_readonly_permission_proceeds_without_preparation(monkeypatch, mode):
    async with permission_turn(monkeypatch, mode) as (agent, registry, clerk, router, _):
        response = await agent._permission_entry(registry, permission("ap_queue", "sdk-read", {}))
        assert response.selected_option == "proceed_once" and not router.calls
        assert not clerk.cancellations


async def test_prepared_permission_and_first_execution_share_sdk_id(monkeypatch):
    async with permission_turn(monkeypatch, "off") as (agent, registry, clerk, router, events):
        route = router.post("http://bf/api/preparations").mock(return_value=prepared("off"))
        router.get("http://bf/api/invoices/i").respond(200, json=invoice("i", status="approved"))
        router.get("http://bf/api/payments").mock(
            side_effect=[
                httpx.Response(200, json=[]),
                httpx.Response(200, json=[{"id": "payment", "invoice_id": "i", "amount": "1200.00"}]),
            ]
        )
        execute = router.post("http://bf/api/invoices/i/pay").respond(200, json={"id": "payment"})
        request = permission("pay_invoice", "sdk-id", {"invoice_id": "i"})
        assert (await agent._permission_entry(registry, request)).selected_option == "proceed_once"
        # Shared strict identity is exercised here, but this remains a fake HTTP/SDK adapter unit.
        with bind_strict(True):
            result = json.loads(agent._offload(tools.pay_invoice, registry=registry)(invoice_id="i"))
        assert result["outcome"] == "confirmed" and not clerk.cancellations
        assert route.call_count == execute.call_count == 1
        assert route.calls[0].request.headers["X-Tool-Use-Id"] == execute.calls[0].request.headers["X-Tool-Use-Id"] == "sdk-id"
        assert all(call.request.url.host == "bf" for call in router.calls)
    assert [(event["type"], event["payload"]["tool_use_id"]) for event in events] == [
        ("agent.tool_call", "sdk-id"),
        ("agent.tool_result", "sdk-id"),
    ]
    assert events[1]["payload"]["ok"] is True


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("bad", ["empty", "id", "server", "tool", "batch", "mixed", "local", "explicit"])
async def test_invalid_metadata_and_batches_cancel_before_io(monkeypatch, mode, bad):
    async with permission_turn(monkeypatch, mode) as (agent, registry, clerk, router, events):
        request = permission("pay_invoice", "sdk-id", {"invoice_id": "i"})
        expected = []
        if bad == "empty":
            request.actions = ()
        elif bad == "id":
            request.actions[0].tool_use.id = ""
        elif bad == "server":
            request.actions[0].server_name = "other"
        elif bad == "tool":
            request = permission("unknown", "sdk-id", {})
        elif bad in ("batch", "mixed"):
            other = permission("approve_expense" if bad == "batch" else "unknown", "sdk-other", {"expense_id": "e"})
            request.actions += other.actions
            expected = ["sdk-id", "sdk-other"] if bad == "batch" else ["sdk-id"]
        else:
            registry.observe("sdk-id", "pay_invoice", {"invoice_id": "i"}, bad)
            expected = ["sdk-id"]
        response = await agent._permission_entry(registry, request)
        assert response.selected_option == "cancel" and json.loads(response.comment)["cause"] == "integration_failure"
        assert not router.calls and not clerk.blocked and not clerk.confirmed
        if bad in ("batch", "mixed"):
            assert "separate tool requests" in response.comment
            assert KEY in clerk.failures
            assert (("expense", "e") in clerk.failures) == (bad == "batch")
    cancelled(events, expected, "integration_failure")


@pytest.mark.parametrize("initial", ["control_hold", "escalation_timeout", "integration_failure", "invalid_state", "infra"])
async def test_cross_tool_hold_preserves_original_cause_and_never_reprepares(monkeypatch, initial):
    async with permission_turn(monkeypatch) as (agent, registry, clerk, router, events):
        response = {
            "control_hold": prepared("enforce", effective="block", decided_by="gate", reason="original"),
            "escalation_timeout": prepared("enforce", effective="block", decided_by="timeout", reason="original"),
            "integration_failure": httpx.Response(503),
            "invalid_state": httpx.Response(422),
            "infra": prepared("enforce", effective="block", decided_by="gate", cause="gate_unavailable", reason="original"),
        }[initial]
        route = router.post("http://bf/api/preparations").mock(return_value=response)
        comments, ids = [], []
        for index, (tool, args) in enumerate(
            [
                ("pay_invoice", {"invoice_id": "i"}),
                ("approve_invoice", {"invoice_id": "i"}),
                ("reject_invoice", {"invoice_id": "i", "reason": "no retry"}),
                ("pay_invoice", {"invoice_id": "i"}),
            ]
        ):
            identity = "sdk-id" if index == 0 else f"sdk-{index}"
            ids.append(identity)
            response = await agent._permission_entry(registry, permission(tool, identity, args))
            assert response.selected_option == "cancel"
            comments.append(response.comment)
        assert len(set(comments)) == 1 and route.call_count == 1 and len(router.calls) == 1
        cause = "control_hold" if initial == "infra" else initial
        assert clerk.cancellations == {cause: {KEY}} and not clerk.confirmed and not clerk.attempted
        assert bool(clerk.failures) == (initial in ("infra", "integration_failure"))
    cancelled(events, ids, cause)


@pytest.mark.parametrize("held", ["blocked", "deferred", "failures", "uncertain", "unknown"])
async def test_existing_procedural_holds_cancel_without_preparation(monkeypatch, held):
    async with permission_turn(monkeypatch) as (agent, registry, clerk, router, _):
        getattr(clerk, held).add(KEY)
        response = await agent._permission_entry(registry, permission("reject_invoice", "sdk-id", {"invoice_id": "i", "reason": "no retry"}))
        assert response.selected_option == "cancel" and not router.calls
        assert KEY in clerk.cancellation_decisions


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("entry", [False, True])
async def test_unexpected_exception_sanitized_and_cancellation_propagates(monkeypatch, mode, entry):
    async with permission_turn(monkeypatch, mode) as (agent, registry, clerk, router, events):
        mock = AsyncMock(side_effect=RuntimeError("private credential"))
        monkeypatch.setattr(ctx.ledger(), "prepare", mock)
        request = permission("pay_invoice", "sdk-id", {"invoice_id": "i"})
        agent.tool_uses(request)
        response = await (agent._permission_entry(registry, request) if entry else agent.on_permission(request))
        assert response.selected_option == "cancel" and "private" not in response.comment
        assert json.loads(response.comment)["cause"] == "integration_failure" and KEY in clerk.failures
        assert not router.calls and mock.await_count == 1
        mock.side_effect = asyncio.CancelledError()
        request = permission("pay_invoice", "sdk-cancel", {"invoice_id": "other"})
        agent.tool_uses(request)
        with pytest.raises(asyncio.CancelledError):
            await (agent._permission_entry(registry, request) if entry else agent.on_permission(request))
        assert mock.await_count == 2 and ("invoice", "other") not in clerk.cancellation_decisions
    if entry:
        cancelled(events[:2], ["sdk-id"], "integration_failure")
