"""Real AP tools through shared adapter units, with permission-shaped metadata only.

No SDK is loaded or session opened. These fixtures do not prove live prompting,
SDK identity delivery, CANCEL comment delivery, or the canonical Blue protocol.
"""

import json
import sys
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
import respx
from conftest import REQ, change, expense, invoice
from workflow import clerk_scope, state

import tools as green_tools
from agent import GreenAgent
from agentkit import AgentSettings, EventEmitter, LedgerClient, ctx
from agentkit.invocation import bind_registry, current_invocation, current_registry


def permission(tool, tool_use_id, args):
    full_name = f"green-ledger___{tool}"
    return SimpleNamespace(
        actions=(
            SimpleNamespace(
                confirmation_type="mcp_tool",
                server_name="green-ledger",
                tool_name=full_name,
                actual_tool_name=tool,
                tool_use=SimpleNamespace(id=tool_use_id, name=full_name, input=args),
            ),
        ),
        options=(SimpleNamespace(value="cancel"), SimpleNamespace(value="proceed_once")),
        respond=lambda outcome, **kwargs: SimpleNamespace(selected_option=outcome, **kwargs),
    )


def approved(registry, tool, tool_use_id, args):
    (use,) = registry.observe_permission(permission(tool, tool_use_id, args))
    assert (use.tool, use.args, use.source) == (tool, args, "permission")
    registry.permission_resolved(use.tool_use_id, approved=True)
    return use


@asynccontextmanager
async def adapter_turn(monkeypatch):
    # An accidental SDK import fails instead of discovering a locally installed SDK/key.
    monkeypatch.setitem(sys.modules, "droid_sdk", None)
    settings = AgentSettings(
        _env_file=None,
        AGENT_NAME="green",
        AGENT_TOKEN="test-token",
        BATTLEFIELD_URL="http://bf",
        DRY_RUN=True,
        FACTORY_API_KEY=None,
        DROID_MODEL=None,
        DROID_REASONING=None,
        TURN_TIMEOUT_SEC=180,
        HTTP_TIMEOUT_SEC=15,
        ESCALATION_TIMEOUT_SEC=90,
    )
    agent = GreenAgent(settings)
    async with (
        LedgerClient(settings, episode_id=REQ.episode_id, day=REQ.day) as ledger,
        EventEmitter(settings, episode_id=REQ.episode_id, day=REQ.day) as emitter,
    ):
        registry = agent._new_registry(emitter)
        assert registry.require_permission and agent.autonomy == "off"
        tokens = ctx.bind(ledger, emitter, REQ)
        try:
            with clerk_scope() as clerk, bind_registry(registry):
                yield agent, registry, clerk
                registry.close()
                registry.close()  # Completed/cancelled uses must never acquire extra pairs.
        finally:
            ctx.unbind(tokens)
    assert current_invocation() is None and current_registry() is None


def ledger_requests():
    requests = [call.request for call in respx.calls]
    for request in requests:
        assert request.url.host == "bf"
        assert request.headers["Authorization"] == "Bearer test-token"
        assert request.headers["X-Agent"] == "green"
        assert request.headers["X-Episode"] == REQ.episode_id
        assert request.headers["X-Day"] == str(REQ.day)
    return [request for request in requests if request.url.path != "/api/events"]


def paired_results(book, uses):
    assert [(event["type"], event["payload"]["tool_use_id"]) for event in book.events] == [
        (event_type, use.tool_use_id) for use in uses for event_type in ("agent.tool_call", "agent.tool_result")
    ]
    for event, use in zip(book.events[::2], uses, strict=True):
        assert event["payload"] == {"tool": use.tool, "args": use.args, "tool_use_id": use.tool_use_id}
    return [event["payload"] for event in book.events[1::2]]


@pytest.mark.parametrize(
    "tool",
    [
        "match_invoice",
        "approve_invoice",
        "reject_invoice",
        "pay_invoice",
        "approve_vendor_change",
        "reject_vendor_change",
        "approve_expense",
        "pay_expense",
    ],
)
async def test_ap_mutation_links_registered_identity_headers_events_and_parent_state(book, monkeypatch, tool):
    action, kind = tool.split("_", 1)
    table = {"invoice": "invoices", "vendor_change": "vendor_changes", "expense": "expenses"}[kind]
    entity_id = f"fixture-{kind}"
    row = {"invoice": invoice, "vendor_change": change, "expense": expense}[kind](entity_id)
    if action == "pay":
        row["status"] = "approved"
    args = {"change_id" if kind == "vendor_change" else f"{kind}_id": entity_id}
    if action == "match":
        row["po_id"] = args["po_id"] = "fixture-po"
        book.add("purchase_orders", {"id": "fixture-po", "vendor_id": "v", "amount": "1200.00", "created_day": 1, "status": "open"})
    if action == "reject":
        args["reason"] = "fixture explicit rejection"
    book.add(table, row)
    async with adapter_turn(monkeypatch) as (agent, registry, clerk):
        use = approved(registry, tool, f"sdk-{tool}-{entity_id}", args)
        # Sync call on the running loop, exactly as the shared adapter expects.
        out = agent._offload(getattr(green_tools, tool), registry=registry)(**args)
        assert json.loads(out) == {"outcome": "confirmed", "action": f"{kind}.{action}", "entity_id": entity_id}
        assert state() is clerk
        amount = Decimal(row["amount"]) if action == "pay" else Decimal("0")
        assert clerk.confirmed == {f"{kind}.{action}": {(kind, entity_id): amount}}
        assert clerk.attempted == {(action, (kind, entity_id))}
        assert not (clerk.blocked | clerk.deferred | clerk.failures | clerk.uncertain | clerk.unknown)
        assert f"paid ${amount:.2f}" in clerk.summary()
        assert current_invocation() is None
    assert book.rows[table][entity_id]["status"] == {"match": "matched", "approve": "approved", "reject": "rejected", "pay": "paid"}[action]
    assert book.writes == [f"{table}/{entity_id}/{action}"]
    writes = [request for request in ledger_requests() if request.method != "GET"]
    assert [(request.method, request.url.path, request.headers["X-Tool-Use-Id"]) for request in writes] == [
        ("POST", f"/api/{table}/{entity_id}/{action}", use.tool_use_id)
    ]
    (result,) = paired_results(book, [use])
    assert result["ok"] is True and json.loads(result["summary"]) == json.loads(out)
    assert len(book.rows["payments"]) == int(action == "pay")


async def test_blocked_entity_is_suppressed_across_worker_invocations_in_one_parent_scope(book, monkeypatch):
    book.add("invoices", invoice("held"))
    path = "invoices/held/approve"
    book.faults["POST", path] = httpx.Response(403, json={"verdict": "block", "reason": "fixture block", "verdict_id": "fixture-verdict"})
    uses, outputs = [], []
    async with adapter_turn(monkeypatch) as (agent, registry, clerk):
        for tool, args in (
            ("approve_invoice", {"invoice_id": "held"}),
            ("pay_invoice", {"invoice_id": "held"}),
            ("reject_invoice", {"invoice_id": "held", "reason": "not retried"}),
        ):
            uses.append(approved(registry, tool, f"sdk-{tool}-held", args))
            outputs.append(json.loads(agent._offload(getattr(green_tools, tool), registry=registry)(**args)))
            assert state() is clerk and clerk.blocked == {("invoice", "held")}
            assert current_invocation() is None
            # Neither subsequent worker may even re-read the held entity.
            assert book.calls == [("GET", "invoices/held", {}), ("POST", path, {})]
        assert outputs[0]["blocked"] is True
        assert [out["outcome"] for out in outputs[1:]] == ["deferred", "deferred"]
        assert not clerk.confirmed and not book.rows["payments"]
        assert clerk.attempted == {("approve", ("invoice", "held"))}
        assert "paid $0.00; blocked 1, deferred 0, failures 0, unknown 0" in clerk.summary()
    assert book.writes == [path] and book.rows["invoices"]["held"]["status"] == "pending"
    requests = ledger_requests()
    assert [(request.method, request.url.path) for request in requests] == [("GET", "/api/invoices/held"), ("POST", f"/api/{path}")]
    assert requests[1].headers["X-Tool-Use-Id"] == uses[0].tool_use_id
    results = paired_results(book, uses)
    assert results[0]["ok"] is False and json.loads(results[0]["summary"]) == outputs[0]
    assert [json.loads(result["summary"]) for result in results[1:]] == outputs[1:]
    # Deferred outcomes and zero follow-on Ledger I/O prove suppression,
    # independently of the result's tool-execution ok flag.


async def test_real_green_cancel_through_shared_entry_emits_one_false_pair_without_ledger_io(book, monkeypatch):
    async with adapter_turn(monkeypatch) as (agent, registry, clerk):
        # Minimal adapter-unit fake only; no SDK code, prompting or session experiment.
        monkeypatch.setitem(sys.modules, "droid_sdk", SimpleNamespace(ToolConfirmationOutcome=SimpleNamespace(CANCEL="cancel")))
        request = permission("pay_invoice", "sdk-cancel-pay", {"invoice_id": "never-read"})
        monkeypatch.setattr(ctx, "turn", lambda: (_ for _ in ()).throw(RuntimeError("private missing context")))
        (use,) = agent.tool_uses(request)
        for _ in range(2):
            response = await agent._permission_entry(registry, request)
            assert response.selected_option == "cancel" and json.loads(response.comment)["cause"] == "integration_failure"
            assert "private" not in response.comment
            agent.record_cancelled(use, response.comment, registry=registry)
        assert not book.calls and not book.writes
        assert not clerk.blocked and not clerk.attempted and not clerk.confirmed
        assert current_invocation() is None
    assert ledger_requests() == [] and not book.writes
    assert all(method == "POST" and path == "events" for method, path, _ in book.calls)
    (result,) = paired_results(book, [use])
    assert result["ok"] is False
    summary = json.loads(result["summary"])
    assert summary == {"cancelled": True, "tool": "pay_invoice", "reason": response.comment}
    assert json.loads(summary["reason"])["cause"] == "integration_failure"
