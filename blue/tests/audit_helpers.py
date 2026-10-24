from __future__ import annotations

import asyncio
import copy
import time
from contextlib import asynccontextmanager

from agentkit import ctx
from agentkit.models import TurnRequest
from audit.models import AuditSession


def vendor(id="v", **overrides):
    return {
        "id": id,
        "episode_id": "ep",
        "name": "Ordinary Supplier",
        "bank_account": f"private-account-{id}",
        "bank_routing": "private-routing",
        "created_day": -100,
        "status": "active",
    } | overrides


def invoice(id="i", **overrides):
    return {
        "id": id,
        "episode_id": "ep",
        "vendor_id": "v",
        "po_id": None,
        "amount": 1200,
        "invoice_number": f"PRIVATE-INV-{id}",
        "received_day": 5,
        "due_day": 10,
        "status": "pending",
    } | overrides


class FakeEmitter:
    def __init__(self):
        self.calls = []
        self.results = []
        self.thoughts = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    def tool_call(self, name, args, invocation):
        self.calls.append((name, args, invocation))

    def tool_result(self, invocation, ok, summary):
        self.results.append((invocation, ok, summary))

    def thinking(self, text):
        self.thoughts.append(text)


class FakeLedger:
    def __init__(self, **datasets):
        self.datasets = {
            "vendors": [vendor()],
            "employees": [],
            "invoices": [invoice()],
            "purchase_orders": [],
            "payments": [],
            "changes": [],
            "flags": [],
            "activity": [],
        } | copy.deepcopy(datasets)
        self.read_counts = {}
        self.writes = []
        self.fail_reads = set()
        self.write_failures = {}
        self.read_active = 0
        self.max_read_active = 0
        self.read_block = None
        self.fresh_override = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def read(self, name):
        self.read_counts[name] = self.read_counts.get(name, 0) + 1
        self.read_active += 1
        self.max_read_active = max(self.max_read_active, self.read_active)
        try:
            await asyncio.sleep(0)
            # Tests release this flag from the service loop; never await a foreign-loop Event.
            async with asyncio.timeout(5):
                while self.read_block is not None and not self.read_block.is_set():
                    await asyncio.sleep(0.001)
            if name in self.fail_reads:
                raise RuntimeError("private-provider-error")
            return copy.deepcopy(self.datasets[name])
        finally:
            self.read_active -= 1

    async def list_vendors(self):
        return await self.read("vendors")

    async def list_employees(self):
        return await self.read("employees")

    async def list_invoices(self):
        return await self.read("invoices")

    async def list_purchase_orders(self):
        return await self.read("purchase_orders")

    async def list_payments(self, day=None):
        assert isinstance(day, int)
        return await self.read("payments")

    async def list_vendor_changes(self):
        return await self.read("changes")

    async def list_flags(self):
        return await self.read("flags")

    async def list_audit_log(self, agent=None, day=None):
        assert agent == "green" and isinstance(day, int)
        return await self.read("activity")

    async def get_vendor(self, id):
        self.read_counts["fresh_vendor"] = self.read_counts.get("fresh_vendor", 0) + 1
        return self.fresh_override or copy.deepcopy(next(v for v in self.datasets["vendors"] if v["id"] == id))

    async def write(self, kind, args, invocation):
        assert invocation
        self.writes.append((kind, args, invocation))
        failure = self.write_failures.get(kind)
        if isinstance(failure, Exception):
            raise failure
        if failure == "hang":
            await asyncio.Event().wait()
        if failure == "invalid":
            return {"success": "not a receipt"}
        if kind == "freeze":
            return {"ok": True, "status": "frozen"}
        return {"id": f"receipt_{len(self.writes)}"}

    async def raise_flag(self, entity_type, entity_id, severity, reason, *, tool_use_id=None):
        return await self.write("flag", [entity_type, entity_id, severity, reason], tool_use_id)

    async def freeze_vendor(self, vendor_id, reason, *, tool_use_id=None):
        return await self.write("freeze", [vendor_id, reason], tool_use_id)

    async def post_report(self, day, markdown, *, tool_use_id=None):
        return await self.write("report", [day, markdown], tool_use_id)


def turn(**overrides):
    return TurnRequest(**({"episode_id": "ep", "day": 5, "controller_mode": "enforce", "options": {"inputs": []}} | overrides))


@asynccontextmanager
async def bound_session(ledger, *, dry_run=True, inputs=None):
    from audit import evidence, tools

    snapshot = await evidence.collect_snapshot(ledger, "ep", 5, inputs)
    session = AuditSession("ep", 5, dry_run, time.monotonic() + 170, snapshot=snapshot)
    emitter = FakeEmitter()
    token = tools.SESSION.set(session)
    bindings = ctx.bind(ledger, emitter, turn())
    try:
        yield session, emitter
    finally:
        ctx.unbind(bindings)
        tools.SESSION.reset(token)
