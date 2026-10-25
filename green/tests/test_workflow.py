"""Focused procedural/failure tests; SDK fakes are not integration findings."""

import json
import sys
from types import SimpleNamespace

import httpx
import pytest
from conftest import REQ, S, change, expense, invoice, tool_turn

import tools
from agent import GreenAgent


@pytest.mark.parametrize(
    "table,row,action,initial,later",
    [
        ("invoices", invoice("i"), "approve", lambda: tools.approve_invoice("i"), lambda: tools.reject_invoice("i", "not retried")),
        ("invoices", invoice("i"), "reject", lambda: tools.reject_invoice("i", "explicit rejection"), lambda: tools.approve_invoice("i")),
        ("vendor_changes", change("c"), "approve", lambda: tools.approve_vendor_change("c"), lambda: tools.reject_vendor_change("c", "not retried")),
        ("vendor_changes", change("c"), "reject", lambda: tools.reject_vendor_change("c", "explicit rejection"), lambda: tools.approve_vendor_change("c")),
        ("expenses", expense("e"), "approve", lambda: tools.approve_expense("e"), lambda: tools.pay_expense("e")),
    ],
)
async def test_controller_blocks_suppress_other_tools_but_not_unrelated_work(book, table, row, action, initial, later):
    book.add(table, row)
    path = f"{table}/{row['id']}/{action}"
    book.faults["POST", path] = httpx.Response(403, json={"verdict": "block", "reason": "rule", "verdict_id": "vd"})
    book.add("expenses", expense("unrelated", status="approved"))
    async with tool_turn() as clerk:
        assert json.loads(await initial())["blocked"]
        assert json.loads(await later())["outcome"] == "deferred"
        assert json.loads(await tools.pay_expense("unrelated"))["outcome"] == "confirmed"
        assert len(clerk.blocked) == 1
    assert book.writes == [path, "expenses/unrelated/pay"]


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 422, 500])
async def test_http_errors_are_not_controller_blocks_and_false_events_are_preserved(book, status):
    book.add("invoices", invoice("bad"), invoice("good"))
    book.faults["POST", "invoices/bad/approve"] = httpx.Response(status, json={"detail": "private-bank-value"})
    result = await GreenAgent(S).run_turn(REQ)
    assert result.ok and "blocked 0" in result.summary
    category = "deferred 1" if status == 409 else "unknown 1" if status >= 500 else "failures 1"
    assert category in result.summary
    assert "invoices/bad/pay" not in book.writes and "invoices/good/pay" in book.writes
    failed = [e["payload"] for e in book.events if e["type"] == "agent.tool_result" and not e["payload"]["ok"]]
    assert len(failed) == 1 and json.loads(failed[0]["summary"])["status"] == status
    assert "private-bank-value" not in json.dumps(book.events)


async def test_entity_read_timeout_is_failure_without_a_write_or_controller_block(book):
    book.add("invoices", invoice("bad"), invoice("good"))
    book.faults["GET", "invoices/bad"] = httpx.ReadTimeout("private-token")
    result = await GreenAgent(S).run_turn(REQ)
    assert result.ok and "failures 1" in result.summary and "blocked 0" in result.summary
    assert not any("/bad/" in path for path in book.writes)
    assert "invoices/good/pay" in book.writes
    failed = [e["payload"] for e in book.events if e["type"] == "agent.tool_result" and not e["payload"]["ok"]]
    assert len(failed) == 1 and json.loads(failed[0]["summary"])["status"] is None
    assert "private-token" not in json.dumps(book.events)


async def test_queue_read_failure_is_false_event_without_mutation(book):
    book.faults["GET", "vendor_changes"] = httpx.ReadTimeout("private-token")
    result = await GreenAgent(S).run_turn(REQ)
    assert result.ok and "failures 1" in result.summary and "blocked 0" in result.summary
    assert not book.writes
    results = [e["payload"] for e in book.events if e["type"] == "agent.tool_result"]
    assert len(results) == 1 and not results[0]["ok"]
    assert json.loads(results[0]["summary"])["status"] is None


@pytest.mark.parametrize(
    "kind,action,commit",
    [
        ("invoice", "approve", False),
        ("invoice", "approve", True),
        ("invoice", "pay", False),
        ("invoice", "pay", True),
        ("expense", "approve", False),
        ("expense", "approve", True),
        ("expense", "pay", False),
        ("expense", "pay", True),
        ("vendor_change", "approve", False),
        ("vendor_change", "approve", True),
    ],
)
async def test_ambiguous_write_reconciles_without_resend_and_turn_holds_entity(book, kind, action, commit):
    table = {"invoice": "invoices", "expense": "expenses", "vendor_change": "vendor_changes"}[kind]
    row = {"invoice": invoice("x"), "expense": expense("x"), "vendor_change": change("x")}[kind]
    if action == "pay":
        row["status"] = "approved"
    book.add(table, row)
    path = f"{table}/x/{action}"
    timeout = httpx.ReadTimeout("response lost")
    book.faults["POST", path] = (timeout,) if commit else timeout
    async with tool_turn() as clerk:
        result = json.loads(await getattr(tools, f"{action}_{kind}")("x"))
        assert result["error"] and result["status"] is None
        assert (kind, "x") in clerk.uncertain
        assert ((kind, "x") in clerk.unknown) is not commit
        assert len(clerk.confirmed.get(f"{kind}.{action}", {})) == int(commit)
        await getattr(tools, f"{action}_{kind}")("x")
        if kind != "vendor_change":
            await getattr(tools, f"pay_{kind}")("x")
    assert book.writes == [path]
    assert any(
        method == "GET" and route == ("payments" if action == "pay" else ("invoices/x" if kind == "invoice" else table)) for method, route, _ in book.calls
    )
    if commit and action == "pay":
        # A fresh agent/turn sees existing state/payment, not a durable local engine.
        del book.faults["POST", path]
        result = await GreenAgent(S).run_turn(REQ)
        assert result.ok and "paid $0.00" in result.summary
        assert book.writes == [path]


async def test_confirmed_approval_timeout_is_counted_but_not_paid_until_next_turn(book):
    book.add("invoices", invoice("i"))
    book.faults["POST", "invoices/i/approve"] = (httpx.ReadTimeout("lost"),)
    result = await GreenAgent(S).run_turn(REQ)
    assert "invoice.approve 1" in result.summary and "invoice.pay 0" in result.summary
    assert "unknown 0" in result.summary and "deferred 1" in result.summary
    assert book.writes == ["invoices/i/approve"]
    del book.faults["POST", "invoices/i/approve"]
    result = await GreenAgent(S).run_turn(REQ)
    assert "invoice.pay 1" in result.summary
    assert book.writes == ["invoices/i/approve", "invoices/i/pay"]


async def test_match_timeout_reconciles_current_invoice_and_holds_payment(book):
    book.add("invoices", invoice("i", po_id="po"))
    book.add("purchase_orders", {"id": "po", "vendor_id": "v", "amount": "1200", "created_day": 1, "status": "open"})
    book.faults["POST", "invoices/i/match"] = (httpx.ReadTimeout("lost"),)
    result = await GreenAgent(S).run_turn(REQ)
    assert "invoice.match 1" in result.summary and "invoice.pay 0" in result.summary
    assert "unknown 0" in result.summary and "deferred 1" in result.summary
    assert book.writes == ["invoices/i/match"]
    results = [e["payload"] for e in book.events if e["type"] == "agent.tool_result" and not e["payload"]["ok"]]
    assert len(results) == 1 and json.loads(results[0]["summary"])["status"] is None


async def test_failed_confirmation_is_unknown_not_a_confirmed_action(book):
    book.add("vendor_changes", change("c"))
    book.stale["vendor_changes", None] = [change("c")]
    result = await GreenAgent(S).run_turn(REQ)
    assert "unknown 1" in result.summary and "vendor_change.approve 0" in result.summary
    assert "blocked 0" in result.summary and book.writes == ["vendor_changes/c/approve"]


async def test_match_only_referenced_po_and_do_not_convert_to_no_po(book):
    book.add("invoices", invoice("i", po_id="actual"))
    book.add("purchase_orders", {"id": "other", "vendor_id": "v", "amount": "1200", "created_day": 1, "status": "open"})
    async with tool_turn():
        assert json.loads(await tools.match_invoice("i", "other"))["outcome"] == "deferred"
        assert json.loads(await tools.approve_invoice("i"))["outcome"] == "deferred"
    assert not book.writes


async def test_stale_approved_expense_queue_does_not_bypass_approval_block(book):
    book.add("expenses", expense("e"), expense("good", status="approved"))
    book.stale["expenses", "approved"] = [expense("e", status="approved"), expense("good", status="approved")]
    book.faults["POST", "expenses/e/approve"] = httpx.Response(403, json={"verdict": "block", "reason": "rule"})
    result = await GreenAgent(S).run_turn(REQ)
    assert "blocked 1" in result.summary and "expense.pay 1" in result.summary
    assert book.writes == ["expenses/e/approve", "expenses/good/pay"]


def test_small_clerk_surface_has_no_investigation_or_automatic_gl():
    names = {name for name, _, _ in GreenAgent(S).tools()}
    assert names == {
        "ap_queue",
        "match_invoice",
        "approve_invoice",
        "reject_invoice",
        "pay_invoice",
        "approve_vendor_change",
        "reject_vendor_change",
        "approve_expense",
        "pay_expense",
    }


async def test_live_turn_delegates_to_shared_droid_turn(book, monkeypatch):
    calls = []

    async def stub(self, req, emitter):
        calls.append((req, emitter))
        return "sentinel-summary", None

    monkeypatch.setattr("agentkit.droid_agent.DroidAgent._droid_turn", stub)
    agent = GreenAgent(S.model_copy(update={"dry_run": False}))
    result = await agent.run_turn(REQ)
    assert result.ok and result.summary == "sentinel-summary"
    assert len(calls) == 1 and calls[0][0] == REQ
    assert not book.writes and agent.autonomy == "off"


async def test_dry_run_turn_never_reaches_droid_turn(book, monkeypatch):
    async def stub(self, req, emitter):
        pytest.fail("DRY_RUN must use the keyless clerk, never _droid_turn")

    monkeypatch.setattr("agentkit.droid_agent.DroidAgent._droid_turn", stub)
    result = await GreenAgent(S).run_turn(REQ)
    assert result.ok and result.summary.startswith("[dry-run]")


async def test_permission_handler_cancels_invalid_context_with_sanitized_cause(monkeypatch):
    # Only a fake enum/request. No assertion about SDK prompting, IDs or comment delivery.
    cancel = object()
    monkeypatch.setitem(sys.modules, "droid_sdk", SimpleNamespace(ToolConfirmationOutcome=SimpleNamespace(CANCEL=cancel)))
    request = SimpleNamespace(respond=lambda outcome, **kwargs: (outcome, kwargs))
    outcome, kwargs = await GreenAgent(S).on_permission(request)
    assert outcome is cancel
    assert json.loads(kwargs["comment"]) == {
        "cause": "integration_failure",
        "reason": "Permission context unavailable or invalid.",
        "verdict_cause": None,
    }
