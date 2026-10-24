"""Turn-local clerk procedure, not a durable engine or a fraud controller."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
import structlog
from preparation import PreparationDecision

from agentkit import GateBlocked, LedgerError, ctx
from agentkit.models import CancelCause

Key = tuple[str, str]
log = structlog.get_logger(__name__)
CAPABILITIES = {
    ("match", "invoice"),
    ("approve", "invoice"),
    ("reject", "invoice"),
    ("pay", "invoice"),
    ("approve", "expense"),
    ("pay", "expense"),
    ("approve", "vendor_change"),
    ("reject", "vendor_change"),
}


def money(value: Any) -> Decimal:
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("invalid monetary amount") from None
    if not amount.is_finite() or amount < 0:
        raise ValueError("invalid monetary amount")
    return amount


def ordered(rows: list[dict], day: str) -> list[dict]:
    return sorted(rows, key=lambda row: (row[day], row["id"]))


@dataclass
class ClerkState:
    blocked: set[Key] = field(default_factory=set)
    deferred: set[Key] = field(default_factory=set)
    failures: set[Key] = field(default_factory=set)
    uncertain: set[Key] = field(default_factory=set)
    unknown: set[Key] = field(default_factory=set)
    attempted: set[tuple[str, Key]] = field(default_factory=set)
    confirmed: dict[str, dict[Key, Decimal]] = field(default_factory=dict)
    cancellations: dict[CancelCause, set[Key]] = field(default_factory=dict)
    cancellation_decisions: dict[Key, PreparationDecision] = field(default_factory=dict)
    gate_unavailable: set[Key] = field(default_factory=set)

    def held_decision(self, key: Key) -> PreparationDecision | None:
        if key in self.cancellation_decisions:
            return self.cancellation_decisions[key]
        if key in self.blocked:
            return PreparationDecision(False, "control_hold", "Entity already held this turn.")
        if key in self.failures | self.uncertain | self.unknown:
            return PreparationDecision(False, "integration_failure", "Entity already failed or uncertain this turn.")
        if key in self.deferred:
            return PreparationDecision(False, "invalid_state", "Entity already deferred this turn.")
        return None

    def cancel(self, key: Key, decision: PreparationDecision) -> None:
        """Unique entity causes, preserving the first hold across tools and repeated callbacks."""
        if decision.proceed or decision.cause is None or key in self.cancellation_decisions:
            return
        self.cancellation_decisions[key] = decision
        self.cancellations.setdefault(decision.cause, set()).add(key)
        if decision.verdict_cause == "gate_unavailable":
            self.gate_unavailable.add(key)
            self.failures.add(key)
        elif decision.cause in ("control_hold", "escalation_timeout"):
            self.blocked.add(key)
        elif decision.cause == "integration_failure":
            self.failures.add(key)
        else:
            self.deferred.add(key)

    def confirm(self, action: str, key: Key, amount: Decimal = Decimal("0")) -> None:
        self.confirmed.setdefault(action, {})[key] = amount
        self.unknown.discard(key)

    def summary(self) -> str:
        labels = ("vendor_change.approve", "invoice.match", "invoice.approve", "invoice.pay", "expense.approve", "expense.pay")
        counts = ", ".join(f"{label} {len(self.confirmed.get(label, {}))}" for label in labels)
        total = sum((sum(self.confirmed.get(label, {}).values(), Decimal("0")) for label in ("invoice.pay", "expense.pay")), Decimal("0"))
        summary = (
            f"confirmed {counts}; paid ${total:.2f}; blocked {len(self.blocked)}, "
            f"deferred {len(self.deferred - self.blocked - self.failures - self.unknown)}, "
            f"failures {len(self.failures - self.blocked - self.unknown)}, unknown {len(self.unknown)}"
        )
        if self.cancellations:
            causes = ("control_hold", "escalation_timeout", "integration_failure", "invalid_state")
            summary += "; cancellations " + ", ".join(f"{cause} {len(self.cancellations.get(cause, set()))}" for cause in causes)
            if self.gate_unavailable:
                summary += f"; gate_unavailable {len(self.gate_unavailable)}"
        return summary


_state: ContextVar[ClerkState | None] = ContextVar("green_clerk", default=None)


@contextmanager
def clerk_scope(*, reuse: bool = False) -> Iterator[ClerkState]:
    if reuse and _state.get() is not None:
        yield state()
        return
    token = _state.set(ClerkState())
    try:
        yield state()
    finally:
        _state.reset(token)


def state() -> ClerkState:
    current = _state.get()
    if current is None:
        raise RuntimeError("Green tools require a turn-local clerk scope")
    return current


class ClerkFailure(LedgerError):
    """Non-HTTP failure carried through ledger_tool's existing false-result path.

    status=None explicitly means no HTTP status, never a fabricated server response.
    Messages are static and sanitized; the shared decorator emits ok=false.
    """

    def __init__(self, kind: str):
        super().__init__(None, kind)  # type: ignore[arg-type]


def record(action: str, key: Key, outcome: str) -> None:
    turn = ctx.turn()
    # No verified invocation ID is available here. Do not invent one.
    log.info("clerk_action", episode_id=turn.episode_id, day=turn.day, agent="green", action=action, entity_type=key[0], entity_id=key[1], outcome=outcome)


def defer(key: Key, reason: str) -> str:
    state().deferred.add(key)
    record("hold", key, reason)
    return json.dumps({"outcome": "deferred", "reason": reason})


async def current(kind: str, entity_id: str) -> dict | None:
    ledger = ctx.ledger()
    if kind == "invoice":
        return await ledger.get_invoice(entity_id)
    rows = await (ledger.list_expenses() if kind == "expense" else ledger.list_vendor_changes())
    return next((row for row in rows if row["id"] == entity_id), None)


async def confirmation(action: str, key: Key) -> bool:
    kind, entity_id = key
    row = await current(kind, entity_id)
    if action == "pay":
        rows = await ctx.ledger().list_payments()
        payment = next((row for row in rows if row.get(f"{kind}_id") == entity_id), None)
        if payment is None:
            return False
        state().confirm(f"{kind}.pay", key, money(payment["amount"]))
        return True
    target = {"approve": "approved", "match": "matched", "reject": "rejected"}[action]
    if row is not None and row["status"] == target:
        state().confirm(f"{kind}.{action}", key)
        return True
    return False


async def reconcile(action: str, key: Key) -> bool:
    """One read-only reconciliation; no retry even when the write is confirmed."""
    state().uncertain.add(key)
    state().deferred.add(key)
    try:
        confirmed = await confirmation(action, key)
    except (LedgerError, httpx.HTTPError, ValueError, KeyError, TypeError):
        confirmed = False
    if not confirmed:
        state().unknown.add(key)
    record(f"{key[0]}.{action}", key, "reconciled" if confirmed else "unknown_write")
    return confirmed


async def operation(action: str, kind: str, entity_id: str, *, po_id: str | None = None, reason: str = "") -> str:
    clerk, key = state(), (kind, entity_id)
    label = f"{kind}.{action}"
    if key in clerk.blocked | clerk.deferred | clerk.failures | clerk.uncertain or (action, key) in clerk.attempted:
        return defer(key, "entity already handled or held this turn")
    if (action, kind) not in CAPABILITIES:
        clerk.failures.add(key)
        record(label, key, "unsupported_operation")
        raise ClerkFailure("unsupported_operation: no mutation sent")
    writing = False
    try:
        row = await current(kind, entity_id)
        if row is None:
            return defer(key, "entity no longer in queue")
        status = row["status"]
        if status == "blocked":
            clerk.blocked.add(key)
            return defer(key, "entity is blocked")
        eligible = {"pending"}
        if action == "pay":
            eligible = {"matched", "approved"} if kind == "invoice" else {"approved"}
        elif action == "reject" and kind == "invoice":
            eligible = {"pending", "matched", "approved"}
        if status not in eligible:
            return defer(key, "current status is not eligible")
        if kind == "invoice" and action != "reject" and money(row["amount"]) > money(os.environ.get("APPROVAL_THRESHOLD", "5000")):
            return defer(key, "above invoice auto-approval limit")
        if kind == "invoice" and action == "approve" and row.get("po_id") is not None:
            return defer(key, "referenced PO requires matching, not no-PO approval")
        if action == "match":
            if row.get("po_id") is None or row["po_id"] != po_id:
                return defer(key, "only the referenced PO may be matched")
            pos = await ctx.ledger().list_purchase_orders(status="open", vendor_id=row["vendor_id"])
            if not any(p["id"] == po_id and p["status"] == "open" and p["vendor_id"] == row["vendor_id"] for p in pos):
                return defer(key, "referenced PO is missing or unusable")
        if action == "pay":
            payments = await ctx.ledger().list_payments()
            if any(p.get(f"{kind}_id") == entity_id for p in payments):
                return defer(key, "payment already recorded")
        clerk.attempted.add((action, key))
        record(label, key, "attempt")
        method = getattr(ctx.ledger(), f"{action}_{kind}")
        args = [entity_id]
        if action == "match":
            args.append(po_id)
        elif action == "reject":
            args.append(reason)
        writing = True
        await method(*args)
    except GateBlocked as exc:
        clerk.blocked.add(key)
        record(label, key, "blocked")
        raise GateBlocked({"verdict": "block", "reason": "controller blocked this entity; do not retry", "verdict_id": exc.verdict_id}) from None
    except LedgerError as exc:
        if writing and exc.status >= 500:
            await reconcile(action, key)
        elif exc.status == 409:
            clerk.deferred.add(key)
            record(label, key, "stale_conflict")
        else:
            clerk.failures.add(key)
            record(label, key, "ledger_failure")
        raise LedgerError(exc.status, "stale conflict; deferred" if exc.status == 409 else "ledger request failed") from None
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        if not writing:
            clerk.failures.add(key)
            record(label, key, "read_or_contract_failure")
            raise ClerkFailure("read_or_contract_failure: no mutation sent") from None
        confirmed = await reconcile(action, key)
        raise ClerkFailure("write_transport_or_contract_failure: reconciled" if confirmed else "unknown_write: deferred without retry") from None
    # Mutation response bodies for match/approval are intentionally not relied on.
    try:
        confirmed = await confirmation(action, key)
    except (LedgerError, httpx.HTTPError, ValueError, KeyError, TypeError):
        confirmed = False
    if not confirmed:
        clerk.uncertain.add(key)
        clerk.unknown.add(key)
        record(label, key, "unconfirmed_write")
        raise ClerkFailure("unknown_write: confirmation unavailable; deferred without retry")
    record(label, key, "confirmed")
    return json.dumps({"outcome": "confirmed", "action": label, "entity_id": entity_id})


async def queue() -> str:
    ledger = ctx.ledger()
    try:
        out = {
            "vendor_changes": ordered(await ledger.list_vendor_changes(status="pending"), "requested_day"),
            "pending": ordered(await ledger.list_invoices(status="pending"), "received_day"),
            "payable": ordered(await ledger.list_invoices(status="matched") + await ledger.list_invoices(status="approved"), "due_day"),
            "open_pos": ordered(await ledger.list_purchase_orders(status="open"), "created_day"),
            "pending_expenses": ordered(await ledger.list_expenses(status="pending"), "submitted_day"),
            "approved_expenses": ordered(await ledger.list_expenses(status="approved"), "submitted_day"),
        }
        # Only procedural fields; do not narrate bank details, accounts or response bodies.
        fields = {"id", "vendor_id", "po_id", "amount", "status", "requested_day", "received_day", "due_day", "created_day", "submitted_day"}
        return json.dumps({name: [{k: v for k, v in row.items() if k in fields} for row in rows] for name, rows in out.items()})
    except LedgerError as exc:
        state().failures.add(("queue", "ap"))
        raise LedgerError(exc.status, "AP queue read failed") from None
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        state().failures.add(("queue", "ap"))
        raise ClerkFailure("read_or_contract_failure: AP queue unavailable") from None


async def run_clerk(tools: Any) -> str:
    if emitter := ctx.emitter():
        emitter.thinking("Working vendor changes, invoice matching and payments, then employee expenses. Held items will not be retried.")
    first = json.loads(await tools.ap_queue())
    if first.get("error"):
        return state().summary()
    for change in first["vendor_changes"]:
        await tools.approve_vendor_change(change["id"])
    for invoice in first["pending"]:
        if invoice.get("po_id") is not None:
            await tools.match_invoice(invoice["id"], invoice["po_id"])
        else:
            await tools.approve_invoice(invoice["id"])
    # Refresh lists after approvals; operations independently re-read current entities.
    second = json.loads(await tools.ap_queue())
    if second.get("error"):
        return state().summary()
    for invoice in second["payable"]:
        await tools.pay_invoice(invoice["id"])
    for expense in second["pending_expenses"]:
        await tools.approve_expense(expense["id"])
    third = json.loads(await tools.ap_queue())
    if not third.get("error"):
        for expense in third["approved_expenses"]:
            await tools.pay_expense(expense["id"])
    return state().summary()
