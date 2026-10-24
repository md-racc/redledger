"""Bounded public ledger collection; this layer makes no control or mutation decisions."""

from __future__ import annotations

import asyncio
import re
from decimal import Decimal
from typing import Any

from agentkit.ledger_client import LedgerClient
from gate.rules import BANK_FIELDS, money

from .models import Coverage, Snapshot

MAX_ROWS = 2000
COLLECTION_TIMEOUT = 25.0
READ_TIMEOUT = 10.0
ID = re.compile(r"[A-Za-z0-9_-]{1,100}\Z")
ALLOWED = {
    "vendors": {"id", "status", "created_day", "bank_account", "bank_routing", "name"},
    "employees": {"id", "status", "start_day", "hr_record", "bank_account"},
    "invoices": {"id", "vendor_id", "po_id", "amount", "invoice_number", "received_day", "due_day", "status"},
    "purchase_orders": {"id", "vendor_id", "amount", "status"},
    "payments": {"id", "invoice_id", "expense_id", "amount", "paid_day"},
    "changes": {"id", "vendor_id", "field", "old_value", "new_value", "requested_day", "resolved_day", "status"},
    "flags": {"id", "entity_type", "entity_id", "severity", "reason"},
    "activity": {"action", "http_status", "day"},
}
ACTIONS = {
    "invoices.match",
    "invoices.approve",
    "invoices.reject",
    "invoices.pay",
    "vendor_changes.approve",
    "vendor_changes.reject",
    "expenses.approve",
    "expenses.pay",
    "gl.post",
}
STATUSES = {
    "vendors": {"active", "frozen"},
    "employees": {"active", "inactive", "terminated", "frozen"},
    "invoices": {"pending", "matched", "approved", "paid", "rejected", "blocked"},
    "purchase_orders": {"open", "approved", "fulfilled", "closed", "cancelled"},
    "changes": {"pending", "approved", "rejected", "blocked"},
}


def valid_id(value: Any) -> bool:
    return isinstance(value, str) and ID.fullmatch(value) is not None


def _normalize(dataset: str, row: Any, episode_id: str, day: int) -> dict[str, Any] | None:
    if not isinstance(row, dict) or row.get("episode_id", episode_id) != episode_id:
        return None
    if dataset == "activity":
        if row.get("agent", "green") != "green" or row.get("day", day) != day or row.get("action") not in ACTIONS:
            return None
        status = row.get("http_status")
        if isinstance(status, bool) or not isinstance(status, int) or not 100 <= status < 600:
            return None
        return {"action": row["action"], "http_status": status, "day": day}
    if not valid_id(row.get("id")):
        return None
    out = {k: row[k] for k in ALLOWED[dataset] if k in row}
    for key in ("vendor_id", "entity_id"):
        if key in out and not valid_id(out[key]):
            return None
    for key in ("po_id", "invoice_id", "expense_id"):
        if out.get(key) is not None and not valid_id(out[key]):
            return None
    if dataset in STATUSES and out.get("status") not in STATUSES[dataset]:
        return None
    if dataset in {"invoices", "purchase_orders", "payments"}:
        try:
            out["amount"] = money(out.get("amount"))
        except ValueError:
            return None
    for key in ("created_day", "start_day", "received_day", "requested_day", "paid_day"):
        if dataset == {"created_day": "vendors", "start_day": "employees", "received_day": "invoices", "requested_day": "changes", "paid_day": "payments"}.get(
            key
        ):
            value = out.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value > day:
                return None
    if dataset in {"invoices", "purchase_orders", "changes"} and not valid_id(out.get("vendor_id")):
        return None
    if dataset == "invoices":
        number = out.get("invoice_number")
        if not isinstance(number, str) or not number.strip() or len(number) > 160 or "po_id" not in out:
            return None
    if dataset == "employees" and not isinstance(out.get("hr_record"), bool):
        return None
    if dataset == "changes" and out.get("field") not in BANK_FIELDS | {"name", "address"}:
        return None
    # Keep only bounded scalar source facts internally. No nested log args/results or provenance.
    for value in out.values():
        if not isinstance(value, (str, int, bool, Decimal, type(None))) or (isinstance(value, str) and len(value) > 800):
            return None
    return out


async def collect_snapshot(ledger: LedgerClient, episode_id: str, day: int, inputs: Any = None) -> Snapshot:
    snapshot = Snapshot(episode_id, day)
    reads = {
        "vendors": ledger.list_vendors,
        "employees": ledger.list_employees,
        "invoices": ledger.list_invoices,
        "purchase_orders": ledger.list_purchase_orders,
        "payments": lambda: ledger.list_payments(day=day),
        "changes": ledger.list_vendor_changes,
        "flags": ledger.list_flags,
        "activity": lambda: ledger.list_audit_log(agent="green", day=day),
    }
    semaphore = asyncio.Semaphore(4)

    async def read(name: str) -> None:
        try:
            async with semaphore:
                async with asyncio.timeout(READ_TIMEOUT):
                    rows = await reads[name]()
            if not isinstance(rows, list):
                raise ValueError("invalid dataset")
            kept = []
            omitted = max(0, len(rows) - MAX_ROWS)
            rejected = 0
            seen_ids: set[str] = set()
            for row in rows[:MAX_ROWS]:
                if (len(kept) + rejected) % 128 == 0:
                    await asyncio.sleep(0)
                if name == "activity" and isinstance(row, dict) and row.get("action") not in ACTIONS:
                    continue
                clean = _normalize(name, row, episode_id, day)
                if clean is None:
                    rejected += 1
                elif name != "activity" and clean["id"] in seen_ids:
                    rejected += 1
                else:
                    kept.append(clean)
                    if name != "activity":
                        seen_ids.add(clean["id"])
            snapshot.datasets[name] = kept
            snapshot.coverage.append(
                Coverage(
                    dataset=name,
                    status="truncated" if omitted else "partial" if rejected else "complete",
                    processed=len(kept),
                    omitted=omitted + rejected,
                    detail="Local row cap exceeded." if omitted else "Malformed or out-of-scope rows excluded." if rejected else "",
                )
            )
        except asyncio.CancelledError:
            snapshot.datasets.setdefault(name, [])
            snapshot.coverage.append(Coverage(dataset=name, status="unavailable", detail="Collection deadline exceeded."))
            raise
        except Exception:
            snapshot.datasets[name] = []
            snapshot.coverage.append(Coverage(dataset=name, status="unavailable", detail="Public ledger read unavailable."))

    tasks = [asyncio.create_task(read(name)) for name in reads]
    try:
        async with asyncio.timeout(COLLECTION_TIMEOUT):
            await asyncio.gather(*tasks)
    except TimeoutError:
        pass
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    snapshot.coverage.sort(key=lambda c: c.dataset)
    # Inputs are bounded leads, never instructions or extra evidence. Corroboration is solely in the snapshot.
    entities = {
        (kind, row["id"])
        for name, kind in [("vendors", "vendor"), ("employees", "employee"), ("invoices", "invoice"), ("changes", "vendor_change")]
        for row in snapshot.datasets.get(name, [])
    }
    if isinstance(inputs, list):
        for lead in inputs[:20]:
            if not isinstance(lead, dict):
                continue
            payload = lead.get("payload")
            if not isinstance(payload, dict) or payload.get("episode_id", episode_id) != episode_id:
                continue
            kind, entity_id = payload.get("entity_type"), payload.get("entity_id")
            if isinstance(kind, str) and valid_id(entity_id) and (kind, entity_id) in entities:
                snapshot.leads_reviewed += 1
    return snapshot
