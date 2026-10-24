"""Deterministic control rules. Owner: Dev M.

Each rule is a pure function (GateRequest) -> RuleHit | None. Rules read only `req.context`
(assembled by battlefield, see contracts/agent-service.md) and `req` fields. No I/O here: this
path has an 8-second budget and runs on every green mutation.

Add a rule: write the function, append to RULES. Each rule's `id` must be a stable snake_case
string; it appears in verdicts.rules_fired and on the frontend.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass

from agentkit.models import GateRequest

THRESHOLD = float(os.environ.get("APPROVAL_THRESHOLD", "5000"))


@dataclass(frozen=True)
class RuleHit:
    id: str
    severity: int  # 1 low, 2 medium, 3 high
    detail: str


Rule = Callable[[GateRequest], RuleHit | None]


def _vendor_age(req: GateRequest) -> int | None:
    v = req.context.get("vendor") or {}
    return None if "created_day" not in v else req.day - int(v["created_day"])


def vendor_age_lt_7d(req: GateRequest) -> RuleHit | None:
    if req.action not in ("invoices.approve", "invoices.pay", "invoices.match"):
        return None
    age = _vendor_age(req)
    if age is not None and age < 7 and (req.amount or 0) > 1000:
        return RuleHit("vendor_age_lt_7d", 2, f"vendor created {age} day(s) ago; invoice ${req.amount:,.2f}")
    return None


def near_threshold(req: GateRequest) -> RuleHit | None:
    if req.action not in ("invoices.approve", "invoices.pay") or not req.amount:
        return None
    if THRESHOLD * 0.95 <= req.amount < THRESHOLD:
        return RuleHit("near_threshold", 1, f"${req.amount:,.2f} is within 5% below the ${THRESHOLD:,.0f} approval line")
    return None


def duplicate_invoice(req: GateRequest) -> RuleHit | None:
    if req.action not in ("invoices.approve", "invoices.pay", "invoices.match") or not req.amount:
        return None
    inv = req.context.get("invoice") or {}
    for p in req.context.get("vendor_paid_invoices", []):
        if abs(float(p["amount"]) - req.amount) <= max(0.05, req.amount * 0.01) and p.get("invoice_number") != inv.get("invoice_number"):
            return RuleHit("duplicate_invoice", 3, f"matches paid {p.get('invoice_number')} (${float(p['amount']):,.2f})")
    return None


def recent_bank_change(req: GateRequest) -> RuleHit | None:
    if req.action != "invoices.pay" or not req.amount or req.amount <= 2500:
        return None
    for ch in req.context.get("vendor_recent_changes", []):
        if ch.get("field") == "bank_account" and ch.get("status") == "approved":
            when = ch.get("resolved_day") if ch.get("resolved_day") is not None else ch.get("requested_day", -999)
            if req.day - int(when) <= 14:
                return RuleHit("recent_bank_change", 3, f"bank account changed {req.day - int(when)} day(s) before a ${req.amount:,.2f} payment")
    return None


def bank_change_with_open_invoices(req: GateRequest) -> RuleHit | None:
    if req.action != "vendor_changes.approve":
        return None
    ch = req.context.get("vendor_change") or {}
    if ch.get("field") == "bank_account" and req.context.get("vendor_open_invoices"):
        total = sum(float(i["amount"]) for i in req.context["vendor_open_invoices"])
        return RuleHit("bank_change_with_open_invoices", 3, f"bank change requested while ${total:,.2f} is open with this vendor")
    return None


def no_po_from_po_vendor(req: GateRequest) -> RuleHit | None:
    if req.action not in ("invoices.approve", "invoices.pay"):
        return None
    inv = req.context.get("invoice") or {}
    paid = req.context.get("vendor_paid_invoices", [])
    if not inv.get("po_id") and len(paid) >= 3 and all(p.get("po_id") for p in paid):
        return RuleHit("no_po_from_po_vendor", 2, "vendor history is 100% PO-backed; this invoice has no PO")
    return None


def over_po_amount(req: GateRequest) -> RuleHit | None:
    if req.action not in ("invoices.match", "invoices.pay") or not req.amount:
        return None
    po = req.context.get("proposed_po") or req.context.get("po")
    if po and req.amount > float(po["amount"]) * 1.10:
        return RuleHit("over_po_amount", 2, f"invoice ${req.amount:,.2f} exceeds PO ${float(po['amount']):,.2f} by >10%")
    return None


def recurring_drift(req: GateRequest) -> RuleHit | None:
    if req.action not in ("invoices.approve", "invoices.pay") or not req.amount:
        return None
    paid = [float(p["amount"]) for p in req.context.get("vendor_paid_invoices", [])][:3]
    if len(paid) == 3:
        mean = sum(paid) / 3
        if req.amount > mean * 1.15:
            return RuleHit("recurring_drift", 1, f"${req.amount:,.2f} vs trailing mean ${mean:,.2f}")
    return None


def employee_bank_matches_vendor(req: GateRequest) -> RuleHit | None:
    if req.action not in ("expenses.approve", "expenses.pay"):
        return None
    if req.context.get("vendors_sharing_bank_account"):
        return RuleHit("employee_bank_matches_vendor", 3, "employee bank account matches a vendor's")
    emp = req.context.get("employee") or {}
    if emp and emp.get("hr_record") is False:
        return RuleHit("no_hr_record", 3, "employee has no HR onboarding record")
    return None


def already_flagged(req: GateRequest) -> RuleHit | None:
    flags = req.context.get("flags") or []
    high = [f for f in flags if f.get("severity") == "high"]
    if high:
        return RuleHit("already_flagged_high", 3, high[0].get("reason", "flagged"))
    return None


RULES: list[Rule] = [
    vendor_age_lt_7d,
    near_threshold,
    duplicate_invoice,
    recent_bank_change,
    bank_change_with_open_invoices,
    no_po_from_po_vendor,
    over_po_amount,
    recurring_drift,
    employee_bank_matches_vendor,
    already_flagged,
]


def evaluate(req: GateRequest) -> list[RuleHit]:
    hits = []
    for rule in RULES:
        try:
            h = rule(req)
            if h:
                hits.append(h)
        except Exception as e:  # a buggy rule must never take the gate down
            hits.append(RuleHit(f"rule_error:{rule.__name__}", 0, str(e)))
    return hits
