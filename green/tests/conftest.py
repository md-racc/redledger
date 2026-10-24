"""Stateful HTTP fixtures, not a database or evidence about the Droid SDK."""

import json
import re
from contextlib import asynccontextmanager

import httpx
import pytest
import respx
from workflow import clerk_scope

from agentkit import AgentSettings, LedgerClient, TurnRequest, ctx

S = AgentSettings(AGENT_NAME="green", BATTLEFIELD_URL="http://bf", INTERNAL_TOKEN="test-token", DRY_RUN=True)
REQ = TurnRequest(episode_id="ep", day=3, controller_mode="enforce")


def invoice(entity_id, *, amount="1200.00", status="pending", po_id=None, day=1, vendor="v"):
    return {"id": entity_id, "vendor_id": vendor, "amount": amount, "po_id": po_id, "received_day": day, "due_day": day + 1, "status": status}


def expense(entity_id, *, amount="7500.00", status="pending", day=1):
    return {"id": entity_id, "employee_id": "emp", "amount": amount, "submitted_day": day, "status": status}


def change(entity_id, *, day=1):
    return {"id": entity_id, "vendor_id": "v", "requested_day": day, "status": "pending", "new_value": "private-bank-value"}


class Book:
    def __init__(self):
        self.rows = {"invoices": {}, "expenses": {}, "vendor_changes": {}, "purchase_orders": {}, "payments": {}}
        self.events, self.calls, self.writes = [], [], []
        self.faults, self.stale = {}, {}

    def add(self, table, *rows):
        self.rows[table].update({row["id"]: row for row in rows})

    def respond(self, request):
        path = request.url.path.removeprefix("/api/")
        self.calls.append((request.method, path, dict(request.url.params)))
        if path == "events":
            self.events.extend(json.loads(request.content))
            return httpx.Response(202, json={"accepted": 1})
        parts = path.split("/")
        table = parts[0]
        assert table in self.rows, f"unexpected/investigative route: {path}"
        if request.method == "GET":
            fault = self.faults.get(("GET", path))
            if fault:
                if isinstance(fault, Exception):
                    raise fault
                return fault
            if len(parts) == 2:
                return httpx.Response(200, json=self.rows[table][parts[1]])
            rows = self.stale.get((table, request.url.params.get("status")))
            if rows is None:
                rows = list(self.rows[table].values())
                rows = [row for row in rows if all(row.get(k) == v for k, v in request.url.params.items())]
            return httpx.Response(200, json=rows)
        assert request.method == "POST" and len(parts) == 3
        self.writes.append(path)
        assert request.headers["X-Agent"] == "green"
        assert request.headers["X-Episode"] == "ep"
        assert request.headers["X-Day"] == str(REQ.day)
        assert request.headers["X-Tool-Use-Id"]
        # A tuple means the server commits before losing the response.
        fault = self.faults.get(("POST", path))
        commit = isinstance(fault, tuple)
        if fault and not commit:
            if isinstance(fault, Exception):
                raise fault
            return fault
        row, action = self.rows[table][parts[1]], parts[2]
        if action == "pay":
            row["status"] = "paid"
            payment = {
                "id": f"pay_{len(self.rows['payments'])}",
                "invoice_id" if table == "invoices" else "expense_id": row["id"],
                "amount": row["amount"],
                "to_account": "private-account",
                "paid_day": REQ.day,
                "paid_by": "green",
            }
            self.add("payments", payment)
            result = payment
        else:
            row["status"] = {"match": "matched", "approve": "approved", "reject": "rejected"}[action]
            result = {"ok": True}  # No undocumented entity body for match/approve.
        if commit:
            raise fault[0]
        return httpx.Response(200, json=result)


@pytest.fixture
def book(monkeypatch):
    monkeypatch.setenv("APPROVAL_THRESHOLD", "5000")
    with respx.mock as router:
        ledger = Book()
        router.route(url=re.compile(r"http://bf/api/.*")).mock(side_effect=ledger.respond)
        yield ledger


@asynccontextmanager
async def tool_turn():
    async with LedgerClient(S, episode_id=REQ.episode_id, day=REQ.day) as ledger:
        tokens = ctx.bind(ledger, None, REQ)
        try:
            with clerk_scope() as clerk:
                yield clerk
        finally:
            ctx.unbind(tokens)
