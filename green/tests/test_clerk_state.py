"""Clerk primitives can be reviewed before wiring them into Green's tools."""

import json
from decimal import Decimal

import httpx
import pytest
from conftest import expense, invoice, tool_turn
from workflow import ClerkState, clerk_scope, money, operation, ordered, state

from agentkit import GateBlocked


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1", "not-money"])
def test_money_rejects_invalid_values(value):
    with pytest.raises(ValueError, match="monetary"):
        money(value)


def test_money_totals_and_turn_scope_are_exact_and_isolated():
    with clerk_scope() as first:
        first.confirm("invoice.pay", ("invoice", "a"), money("0.10"))
        first.confirm("expense.pay", ("expense", "b"), money("0.20"))
        assert "paid $0.30" in first.summary()
        with clerk_scope(reuse=True):
            assert state() is first
        with clerk_scope() as second:
            assert second is not first and not second.confirmed
        assert state() is first
    with pytest.raises(RuntimeError, match="turn-local"):
        state()


def test_ordering_is_stable_and_outcome_counts_do_not_overlap():
    assert [r["id"] for r in ordered([{"id": "b", "day": 1}, {"id": "a", "day": 1}], "day")] == ["a", "b"]
    clerk = ClerkState()
    clerk.blocked.add(("invoice", "held"))
    clerk.deferred.add(("invoice", "held"))
    clerk.confirm("invoice.pay", ("invoice", "paid"), Decimal("1.25"))
    assert "blocked 1, deferred 0" in clerk.summary()


async def test_direct_clerk_operations_confirm_reads_and_suppress_blocked_entity(book):
    book.add("invoices", invoice("blocked"), invoice("good"))
    book.faults["POST", "invoices/blocked/approve"] = httpx.Response(403, json={"verdict": "block", "reason": "rule"})
    async with tool_turn() as clerk:
        with pytest.raises(GateBlocked):
            await operation("approve", "invoice", "blocked")
        assert json.loads(await operation("pay", "invoice", "blocked"))["outcome"] == "deferred"
        assert json.loads(await operation("approve", "invoice", "good"))["outcome"] == "confirmed"
        assert json.loads(await operation("pay", "invoice", "good"))["outcome"] == "confirmed"
        assert "paid $1200.00" in clerk.summary()
    assert book.writes == ["invoices/blocked/approve", "invoices/good/approve", "invoices/good/pay"]


async def test_direct_clerk_defers_above_limit_but_does_not_limit_expenses(book):
    book.add("invoices", invoice("above", amount="5000.01", status="approved"))
    book.add("expenses", expense("backlog", status="approved"))
    async with tool_turn():
        assert json.loads(await operation("pay", "invoice", "above"))["outcome"] == "deferred"
        assert json.loads(await operation("pay", "expense", "backlog"))["outcome"] == "confirmed"
    assert book.writes == ["expenses/backlog/pay"]
