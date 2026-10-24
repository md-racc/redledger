"""Owner: Dev M. Keyless decorated AP clerk against a fake Ledger API."""

import builtins
import json
from decimal import Decimal

import httpx
import pytest
from conftest import REQ, S, change, expense, invoice
from workflow import ClerkState, state

from agent import GreenAgent
from agentkit import LedgerClient, ctx


async def test_dry_run_pays_small_invoice_and_skips_blocked(book):
    book.add("purchase_orders", {"id": "po_1", "vendor_id": "v", "amount": "1200", "created_day": 1, "status": "open"})
    book.add("invoices", invoice("inv_1", po_id="po_1"), invoice("inv_2", amount="4900"))
    book.faults["POST", "invoices/inv_2/approve"] = httpx.Response(403, json={"verdict": "block", "reason": "vendor_age_lt_7d", "verdict_id": "vd_1"})
    result = await GreenAgent(S).run_turn(REQ)
    assert result.ok
    assert "invoices/inv_1/pay" in book.writes
    assert "blocked 1" in result.summary
    assert "invoice.match 1" in result.summary and "invoice.pay 1" in result.summary
    assert "paid $1200.00" in result.summary
    failed = [event for event in book.events if event["type"] == "agent.tool_result" and not event["payload"]["ok"]]
    assert len(failed) == 1
    assert json.loads(failed[0]["payload"]["summary"])["verdict_id"] == "vd_1"


async def test_keyless_decorated_events_and_procedural_order(book, monkeypatch):
    original_import = builtins.__import__

    def no_sdk(name, *args, **kwargs):
        assert not name.startswith("droid_sdk"), "DRY_RUN must never import the SDK"
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_sdk)
    monkeypatch.delenv("FACTORY_API_KEY", raising=False)
    book.add("vendor_changes", change("c_late", day=2), change("c_b"), change("c_a"))
    book.add("invoices", invoice("i_b"), invoice("i_a"), invoice("i_late", day=2))
    book.add("expenses", expense("e_pending"), expense("e_backlog", status="approved"))
    result = await GreenAgent(S).run_turn(REQ)
    assert result.ok
    assert book.writes == [
        "vendor_changes/c_a/approve",
        "vendor_changes/c_b/approve",
        "vendor_changes/c_late/approve",
        "invoices/i_a/approve",
        "invoices/i_b/approve",
        "invoices/i_late/approve",
        "invoices/i_a/pay",
        "invoices/i_b/pay",
        "invoices/i_late/pay",
        "expenses/e_pending/approve",
        "expenses/e_backlog/pay",
        "expenses/e_pending/pay",
    ]
    assert {event["type"] for event in book.events} == {"agent.thinking", "agent.tool_call", "agent.tool_result"}
    calls = [e["payload"] for e in book.events if e["type"] == "agent.tool_call"]
    results = [e["payload"] for e in book.events if e["type"] == "agent.tool_result"]
    assert len(calls) == len(results) == len(book.writes) + 3
    assert [e["tool_use_id"] for e in calls] == [e["tool_use_id"] for e in results]
    assert len({e["tool_use_id"] for e in calls}) == len(calls)
    assert all(e["ok"] for e in results)
    assert "private-bank-value" not in json.dumps(book.events)
    assert "private-account" not in json.dumps(book.events)
    # This tests decorator event pairs only, NOT event/header identity or SDK invocation IDs.
    with pytest.raises(RuntimeError, match="turn-local"):
        state()


@pytest.mark.parametrize("po_status,po_vendor", [("closed", "v"), ("fulfilled", "v"), ("open", "other"), (None, "v")])
async def test_referenced_unusable_po_is_deferred_not_no_po(book, po_status, po_vendor):
    book.add("invoices", invoice("i", po_id="po"), invoice("no_po"))
    if po_status:
        book.add("purchase_orders", {"id": "po", "vendor_id": po_vendor, "amount": "1200", "created_day": 1, "status": po_status})
    result = await GreenAgent(S).run_turn(REQ)
    assert result.ok and "deferred 1" in result.summary and "blocked 0" in result.summary
    assert book.writes == ["invoices/no_po/approve", "invoices/no_po/pay"]


async def test_decimal_inclusive_invoice_limit_and_expenses_without_threshold(book):
    book.add("invoices", invoice("equal", amount="5000.00"), invoice("above", amount="5000.01", status="approved"))
    book.add("expenses", expense("new", amount="9000.01"), expense("backlog", status="approved", amount="7000.02"))
    result = await GreenAgent(S).run_turn(REQ)
    assert result.ok
    assert "invoices/equal/pay" in book.writes and "invoices/above/pay" not in book.writes
    assert "expense.approve 1" in result.summary and "expense.pay 2" in result.summary
    assert "paid $21000.03" in result.summary and "deferred 1" in result.summary
    clerk = ClerkState()
    clerk.confirm("invoice.pay", ("invoice", "a"), Decimal("0.10"))
    clerk.confirm("expense.pay", ("expense", "b"), Decimal("0.20"))
    assert "paid $0.30" in clerk.summary()


async def test_current_entities_override_stale_queue_and_restart_recovers_payments(book):
    book.add("invoices", invoice("paid", status="paid"), invoice("rejected", status="rejected"), invoice("recorded", status="approved"))
    book.stale["invoices", "approved"] = [invoice("paid", status="approved"), invoice("rejected", status="approved"), invoice("recorded", status="approved")]
    book.add("payments", {"id": "existing", "invoice_id": "recorded", "amount": "1200", "to_account": "private", "paid_day": 1, "paid_by": "green"})
    for _ in range(2):
        result = await GreenAgent(S).run_turn(REQ)
        assert result.ok and "invoice.pay 0" in result.summary and "paid $0.00" in result.summary
    assert not book.writes


async def test_direct_dry_run_scope_is_reset_and_backlog_is_recovered(book):
    book.add("expenses", expense("e", status="approved"))
    async with LedgerClient(S, episode_id=REQ.episode_id, day=REQ.day) as ledger:
        tokens = ctx.bind(ledger, None, REQ)
        try:
            result = await GreenAgent(S).dry_run_turn(REQ)
            assert "expense.pay 1" in result
            with pytest.raises(RuntimeError, match="turn-local"):
                state()
            book.add("expenses", expense("next", status="approved"))
            result = await GreenAgent(S).dry_run_turn(REQ)
            assert "expense.pay 1" in result
        finally:
            ctx.unbind(tokens)
    assert book.writes == ["expenses/e/pay", "expenses/next/pay"]


async def test_existing_invoice_limit_environment_uses_exact_decimal(book, monkeypatch):
    monkeypatch.setenv("APPROVAL_THRESHOLD", "0.30")
    book.add("invoices", invoice("equal", amount="0.30"), invoice("above", amount="0.31"))
    result = await GreenAgent(S).run_turn(REQ)
    assert result.ok and "paid $0.30" in result.summary and "deferred 1" in result.summary
    assert book.writes == ["invoices/equal/approve", "invoices/equal/pay"]
