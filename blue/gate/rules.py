"""Pure, mode-independent controls. Evidence failures are not fraud findings."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from agentkit.models import GATED_ACTIONS, GateRequest

Effect = Literal["note", "review", "block", "unavailable"]
INVOICE_ACTIONS = {"invoices.approve", "invoices.pay"}
EXPENSE_ACTIONS = {"expenses.approve", "expenses.pay"}
BANK_FIELDS = {"bank_account", "bank_routing"}


def money(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("invalid monetary evidence")
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("invalid monetary evidence") from None
    if not result.is_finite() or result < 0:
        raise ValueError("invalid monetary evidence")
    return result


def approval_threshold() -> Decimal:
    value = money(os.environ.get("APPROVAL_THRESHOLD", "5000"))
    if value <= 0:
        raise ValueError("invalid approval threshold")
    return value


@dataclass(frozen=True)
class RuleHit:
    id: str
    severity: int
    detail: str
    effect: Effect = "note"
    family: str = "diagnostic"


Rule = Callable[[GateRequest], RuleHit | None]


def _row(req: GateRequest, key: str) -> dict[str, Any]:
    row = req.context.get(key)
    if not isinstance(row, dict) or not row:
        raise ValueError("missing entity evidence")
    _scope(req, row)
    return row


def _scope(req: GateRequest, row: dict[str, Any]) -> None:
    if row.get("episode_id", req.episode_id) != req.episode_id:
        raise ValueError("cross-episode evidence")


def _rows(req: GateRequest, key: str) -> list[dict[str, Any]]:
    rows = req.context.get(key)
    if not isinstance(rows, list) or len(rows) > 2000:
        raise ValueError("missing or oversized evidence list")
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("malformed evidence list")
        _scope(req, row)
    return rows


def _day(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("invalid day")
    return value


def _id(row: dict[str, Any], field: str = "id") -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError("missing entity identifier")
    return value


def _invoice(req: GateRequest) -> dict[str, Any]:
    return _row(req, "invoice")


def _vendor_age(req: GateRequest) -> int:
    return req.day - _day(_row(req, "vendor").get("created_day"))


def _paid(req: GateRequest) -> list[dict[str, Any]]:
    return _rows(req, "vendor_paid_invoices")


def _po(req: GateRequest) -> dict[str, Any] | None:
    return req.context.get("proposed_po") if req.action == "invoices.match" else req.context.get("po")


def _actual_bank_change(ch: dict[str, Any]) -> bool:
    if ch.get("field") not in BANK_FIELDS:
        return False
    old, new = ch.get("old_value"), ch.get("new_value")
    if not isinstance(old, str) or not isinstance(new, str) or not old.strip() or not new.strip():
        raise ValueError("missing destination evidence")
    return old.strip() != new.strip()


def validate(req: GateRequest) -> None:
    """Validate applicable controls before interpreting any risk evidence."""
    if req.action not in GATED_ACTIONS or req.agent != "green":
        raise ValueError("unsupported action or actor")
    if req.action.endswith(".reject"):
        return
    if req.action == "gl.post":
        if not isinstance(req.args.get("account"), str) or not req.args["account"].strip():
            raise ValueError("missing GL account")
        debit, credit = money(req.args.get("debit", 0)), money(req.args.get("credit", 0))
        if (debit > 0) == (credit > 0):
            raise ValueError("invalid individual GL entry")
        return
    key = "invoice" if req.action.startswith("invoices.") else "expense" if req.action in EXPENSE_ACTIONS else "vendor_change"
    entity = _row(req, key)
    _id(entity)
    if req.entity_id is not None and _id(entity) != req.entity_id:
        raise ValueError("entity mismatch")
    if req.entity_type is not None and req.entity_type != key:
        raise ValueError("entity type mismatch")
    if key in {"invoice", "expense"}:
        amount = money(req.amount)
        if amount <= 0 or money(entity.get("amount")) != amount:
            raise ValueError("amount mismatch")
    if key == "vendor_change" or req.action in INVOICE_ACTIONS:
        vendor = _row(req, "vendor")
        if _id(entity, "vendor_id") != _id(vendor):
            raise ValueError("vendor mismatch")
        if vendor.get("status") not in {"active", "frozen"}:
            raise ValueError("missing vendor status")
        if key == "vendor_change" and entity.get("field") not in BANK_FIELDS | {"address", "name"}:
            raise ValueError("missing change field")
    if key == "invoice":
        _id(entity, "vendor_id")
        if req.action != "invoices.match" and ("po_id" not in entity or (entity["po_id"] is not None and not _id(entity, "po_id"))):
            raise ValueError("missing PO association evidence")
        po = _po(req)
        expected = req.args.get("po_id") if req.action == "invoices.match" else entity.get("po_id")
        if expected or req.action == "invoices.match":
            if not isinstance(po, dict) or not po:
                raise ValueError("missing associated PO")
            _scope(req, po)
            if _id(po) != expected:
                raise ValueError("PO mismatch")
            _id(po, "vendor_id")
            money(po.get("amount"))
            if po.get("status") not in {"open", "approved", "fulfilled", "closed", "cancelled"}:
                raise ValueError("missing PO status")
        elif po is not None:
            raise ValueError("unassociated PO evidence")
        if req.action == "invoices.match":
            return
        age = _vendor_age(req)
        if age < 0:
            raise ValueError("future vendor creation")
        _id(entity, "invoice_number")
        for paid in _paid(req):
            if _id(paid, "vendor_id") != _id(vendor) or paid.get("status") != "paid":
                raise ValueError("unrelated paid evidence")
            _id(paid)
            _id(paid, "invoice_number")
            money(paid.get("amount"))
        if req.action == "invoices.pay":
            for change in _rows(req, "vendor_recent_changes"):
                if _id(change, "vendor_id") != _id(vendor):
                    raise ValueError("unrelated bank change")
                if change.get("field") not in BANK_FIELDS | {"address", "name"} or change.get("status") not in {"pending", "approved", "rejected", "blocked"}:
                    raise ValueError("invalid change evidence")
                if _actual_bank_change(change) and change.get("status") == "approved":
                    when = change.get("resolved_day")
                    if _day(change.get("requested_day") if when is None else when) > req.day:
                        raise ValueError("future destination change")
        approval_threshold()
    elif key == "expense":
        employee = _row(req, "employee")
        if _id(entity, "employee_id") != _id(employee):
            raise ValueError("employee mismatch")
        if not isinstance(employee.get("hr_record"), bool) or employee.get("status") not in {"active", "inactive", "terminated", "frozen"}:
            raise ValueError("missing HR evidence")
        for vendor_match in _rows(req, "vendors_sharing_bank_account"):
            _id(vendor_match)
    else:
        if _actual_bank_change(entity):
            for inv in _rows(req, "vendor_open_invoices"):
                if _id(inv, "vendor_id") != _id(vendor) or inv.get("status") not in {"pending", "matched", "approved"}:
                    raise ValueError("unrelated open exposure")
                money(inv.get("amount"))
    if "flags" in req.context:
        for flag in _rows(req, "flags"):
            if not isinstance(flag.get("entity_type"), str) or not isinstance(flag.get("entity_id"), str):
                raise ValueError("malformed hold evidence")


def vendor_age_lt_7d(req: GateRequest) -> RuleHit | None:
    if req.action in INVOICE_ACTIONS and 0 <= _vendor_age(req) < 7 and money(req.amount) > 1000:
        return RuleHit("vendor_age_lt_7d", 1, "Vendor has fewer than seven days of history.", family="tenure")
    return None


def near_threshold(req: GateRequest) -> RuleHit | None:
    if req.action in INVOICE_ACTIONS and approval_threshold() * Decimal(".95") <= money(req.amount) < approval_threshold():
        return RuleHit("near_threshold", 1, "Amount is within five percent below the approval threshold.", family="amount")
    return None


def unverified_vendor_exposure(req: GateRequest) -> RuleHit | None:
    if req.action not in INVOICE_ACTIONS:
        return None
    if 0 <= _vendor_age(req) < 7 and _paid(req) == [] and not _invoice(req).get("po_id") and money(req.amount) >= approval_threshold() * Decimal(".95"):
        return RuleHit(
            "unverified_vendor_exposure",
            3,
            "Near-threshold or larger exposure to a new vendor has neither paid history nor an associated PO; verify onboarding before approval or payment.",
            "block",
            "authorization",
        )
    return None


def duplicate_pair(current: dict[str, Any], paid: dict[str, Any]) -> bool:
    """Exact vendor/number, or one appended letter + same PO + five-cent tolerance."""
    if current.get("id") == paid.get("id") or current.get("vendor_id") != paid.get("vendor_id"):
        return False
    a, b = current.get("invoice_number"), paid.get("invoice_number")
    if not isinstance(a, str) or not isinstance(b, str) or not a.strip() or not b.strip():
        return False
    a, b = a.strip().casefold(), b.strip().casefold()
    if a == b:
        return True
    suffix = (len(a) == len(b) + 1 and a.startswith(b) and a[-1].isalpha()) or (len(b) == len(a) + 1 and b.startswith(a) and b[-1].isalpha())
    return bool(
        suffix
        and current.get("po_id")
        and current.get("po_id") == paid.get("po_id")
        and abs(money(current.get("amount")) - money(paid.get("amount"))) <= Decimal(".05")
    )


def duplicate_invoice(req: GateRequest) -> RuleHit | None:
    if req.action in INVOICE_ACTIONS and any(duplicate_pair(_invoice(req), p) for p in _paid(req)):
        return RuleHit("duplicate_invoice", 3, "Invoice identity duplicates a paid invoice for this vendor.", "block", "integrity")
    return None


def recent_bank_change(req: GateRequest) -> RuleHit | None:
    if req.action != "invoices.pay" or money(req.amount) <= 2500:
        return None
    for ch in _rows(req, "vendor_recent_changes"):
        when = ch.get("resolved_day") if ch.get("resolved_day") is not None else ch.get("requested_day")
        if ch.get("status") == "approved" and _actual_bank_change(ch) and 0 <= req.day - _day(when) <= 14:
            return RuleHit(
                "recent_bank_change",
                2,
                "A material payment follows a recent destination change; independently verify the destination.",
                "review",
                "destination",
            )
    return None


def bank_change_with_open_invoices(req: GateRequest) -> RuleHit | None:
    if req.action == "vendor_changes.approve" and _actual_bank_change(_row(req, "vendor_change")):
        if sum((money(i.get("amount")) for i in _rows(req, "vendor_open_invoices")), Decimal(0)) > 0:
            return RuleHit(
                "bank_change_with_open_invoices", 2, "Destination change overlaps open invoices; independently verify before approval.", "review", "destination"
            )
    return None


def no_po_from_po_vendor(req: GateRequest) -> RuleHit | None:
    if req.action in INVOICE_ACTIONS:
        paid = _paid(req)
        if (
            not _invoice(req).get("po_id")
            and len(paid) >= 5
            and all(p.get("po_id") for p in paid)
            and money(req.amount) > max(money(p["amount"]) for p in paid)
        ):
            # Legit traffic routinely sends small ad-hoc invoices without a PO to vendors whose
            # history is all-PO (#133: 28 prod fires, all legit). Only a no-PO invoice larger than
            # anything the vendor has ever been paid is a separation signal worth a review note.
            return RuleHit(
                "no_po_from_po_vendor",
                1,
                "Invoice lacks the PO customary in this vendor's paid history and exceeds every prior paid amount.",
                family="authorization",
            )
    return None


def over_po_amount(req: GateRequest) -> RuleHit | None:
    if req.action not in INVOICE_ACTIONS | {"invoices.match"}:
        return None
    po = _po(req)
    if po:
        if po["vendor_id"] != _invoice(req)["vendor_id"]:
            return RuleHit("po_vendor_mismatch", 3, "Associated PO belongs to another vendor.", "block", "authorization")
        if po["status"] == "cancelled":
            return RuleHit("invalid_po", 3, "Associated PO is cancelled.", "block", "authorization")
        if money(req.amount) > money(po["amount"]) * Decimal("1.10"):
            return RuleHit("over_po_amount", 3, "Invoice exceeds its associated PO by more than ten percent.", "block", "authorization")
    return None


def recurring_drift(req: GateRequest) -> RuleHit | None:
    if req.action not in INVOICE_ACTIONS:
        return None
    paid = [money(p["amount"]) for p in _paid(req)]
    if len(paid) >= 3:
        mean = sum(paid) / len(paid)
        if mean > 0 and max(paid) - min(paid) <= mean * Decimal(".05") and money(req.amount) > mean * Decimal("1.15"):
            return RuleHit("recurring_drift", 1, "Amount exceeds a stable historical baseline by more than fifteen percent.", family="amount")
    return None


def threshold_split(req: GateRequest) -> RuleHit | None:
    """One expense split into same-day, same-category parts that each stay under the approval threshold."""
    if req.action not in EXPENSE_ACTIONS:
        return None
    threshold = approval_threshold()
    amount = money(req.amount)
    if amount >= threshold:
        return None
    current = _row(req, "expense")
    category = current.get("category")
    submitted_day = _day(current.get("submitted_day", req.day))
    if req.context.get("employee_expense_history") is None:
        return None
    parts = [
        money(other.get("amount"))
        for other in _rows(req, "employee_expense_history")
        if other.get("status") in {"pending", "approved", "paid"}
        and _day(other.get("submitted_day")) == submitted_day
        and isinstance(category, str)
        and other.get("category") == category
    ]
    if not parts:
        return None
    involved = len(parts) + 1
    total = amount + sum(parts, Decimal(0))
    if total >= threshold:
        return RuleHit(
            "threshold_split",
            3,
            f"{involved} same-day expenses of one category for this employee total {total} against an approval threshold of {threshold}; each part stays below it.",
            "block",
            "amount",
        )
    if involved >= 3 and total >= threshold * Decimal(".95"):
        return RuleHit(
            "threshold_split",
            2,
            f"{involved} same-day expenses of one category for this employee total {total}, within five percent below the approval threshold of {threshold}.",
            "review",
            "amount",
        )
    return None


SPLIT_SIBLING_STATUSES = {"pending", "matched", "approved", "paid"}
SPLIT_WINDOW_DAYS = 1


def _split_siblings(req: GateRequest, current: dict[str, Any], threshold: Decimal) -> list[dict[str, Any]]:
    """Same-vendor, near-same-day, sub-threshold invoices from the open and paid lists.

    Sibling evidence is advisory: validate() does not vouch for vendor_open_invoices, so a row
    that is malformed, out of scope, rejected/blocked, or the judged invoice itself is skipped
    rather than raised. Rows are deduplicated by id across both lists.
    """
    vendor_id = _id(current, "vendor_id")
    received = _day(current.get("received_day", req.day))
    seen = {_id(current)}
    out: list[dict[str, Any]] = []
    for key in ("vendor_open_invoices", "vendor_paid_invoices"):
        rows = req.context.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows[:2000]:
            try:
                if not isinstance(row, dict):
                    continue
                _scope(req, row)
                row_id = _id(row)
                if row_id in seen or _id(row, "vendor_id") != vendor_id or row.get("status") not in SPLIT_SIBLING_STATUSES:
                    continue
                if abs(_day(row.get("received_day")) - received) > SPLIT_WINDOW_DAYS:
                    continue
                amount = money(row.get("amount"))
                po_id = row.get("po_id")
                if not 0 < amount < threshold or (po_id is not None and not isinstance(po_id, str)):
                    continue
            except ValueError:
                continue
            seen.add(row_id)
            out.append({"amount": amount, "po_id": po_id or None})
    return out


def invoice_threshold_split(req: GateRequest) -> RuleHit | None:
    """One vendor bill split into near-same-day invoices that each stay under the approval threshold.

    Parts are the judged invoice plus same-vendor invoices received within a day of it that are
    open (pending, matched, approved) or already paid. An invoice billed against its own PO (no
    other involved invoice shares it) is a separately authorized engagement and does not count:
    legit traffic bills each PO once, so it routinely lands several PO-backed invoices for one
    vendor on the same day, while a split bill shares one PO or has none.
    """
    if req.action not in INVOICE_ACTIONS:
        return None
    threshold = approval_threshold()
    amount = money(req.amount)
    if amount >= threshold:
        return None
    current = _invoice(req)
    current_po = current.get("po_id") or None
    parts = [{"amount": amount, "po_id": current_po}, *_split_siblings(req, current, threshold)]
    po_uses: dict[str, int] = {}
    for part in parts:
        if part["po_id"]:
            po_uses[part["po_id"]] = po_uses.get(part["po_id"], 0) + 1
    if current_po and po_uses[current_po] < 2:
        return None
    parts = [p for p in parts if not p["po_id"] or po_uses[p["po_id"]] >= 2]
    involved = len(parts)
    if involved < 2:
        return None
    total = sum((p["amount"] for p in parts), Decimal(0))
    if total >= threshold:
        return RuleHit(
            "invoice_threshold_split",
            3,
            f"{involved} invoices from this vendor received within a day of each other total {total} against an approval threshold of {threshold}; "
            "each part stays below it.",
            "block",
            "amount",
        )
    if involved >= 3 and total >= threshold * Decimal(".95"):
        return RuleHit(
            "invoice_threshold_split",
            2,
            f"{involved} invoices from this vendor received within a day of each other total {total}, within five percent below the approval threshold of {threshold}.",
            "review",
            "amount",
        )
    return None


def employee_bank_matches_vendor(req: GateRequest) -> RuleHit | None:
    if req.action in EXPENSE_ACTIONS and _rows(req, "vendors_sharing_bank_account"):
        return RuleHit("employee_bank_matches_vendor", 2, "Employee and vendor share a payment account; verify ownership.", "review", "identity")
    return None


def employee_eligibility(req: GateRequest) -> RuleHit | None:
    if req.action not in EXPENSE_ACTIONS:
        return None
    emp = _row(req, "employee")
    if emp["hr_record"] is False:
        return RuleHit("no_hr_record", 3, "Employee explicitly lacks an HR onboarding record.", "block", "identity")
    if emp["status"] != "active":
        return RuleHit("inactive_employee", 3, "Employee is not active.", "block", "identity")
    return None


def already_flagged(req: GateRequest) -> RuleHit | None:
    if req.action not in INVOICE_ACTIONS | EXPENSE_ACTIONS:
        return None
    relevant = {(req.entity_type, req.entity_id)}
    if req.action in INVOICE_ACTIONS:
        relevant |= {("invoice", _invoice(req).get("id")), ("vendor", _row(req, "vendor").get("id"))}
        if _row(req, "vendor")["status"] == "frozen":
            return RuleHit("vendor_frozen", 3, "Vendor is frozen; an authorized human must release the hold.", "block", "hold")
    else:
        relevant |= {("expense", _row(req, "expense").get("id")), ("employee", _row(req, "employee").get("id"))}
    for f in req.context.get("flags", []):
        if f.get("severity") == "high" and (f.get("entity_type"), f.get("entity_id")) in relevant:
            return RuleHit("already_flagged_high", 3, "A high-severity hold applies to this entity.", "block", "hold")
    return None


RULES: list[Rule] = [
    vendor_age_lt_7d,
    near_threshold,
    threshold_split,
    invoice_threshold_split,
    duplicate_invoice,
    recent_bank_change,
    bank_change_with_open_invoices,
    no_po_from_po_vendor,
    over_po_amount,
    recurring_drift,
    employee_bank_matches_vendor,
    employee_eligibility,
    already_flagged,
    unverified_vendor_exposure,
]


# Baseline rule ids reflection may retire for a lineage after sustained legit-only fire (#133).
# Only note-effect rules qualify: their hits never block or escalate, so retiring one only drops
# a diagnostic note. Block, review (hold) and unavailable rules are never retireable, whatever the
# statistics say; verification_unavailable and rule_error:* are diagnostics, never retireable.
RETIREABLE_RULE_IDS: frozenset[str] = frozenset(
    {
        "near_threshold",
        "no_po_from_po_vendor",
        "recurring_drift",
        "vendor_age_lt_7d",
    }
)


def evaluate(req: GateRequest) -> list[RuleHit]:
    try:
        validate(req)
    except Exception:
        return [
            RuleHit(
                "verification_unavailable", 0, "Applicable control evidence is missing, malformed, or unsupported; verification is unavailable.", "unavailable"
            )
        ]
    if req.action.endswith(".reject") or req.action == "gl.post":
        return []
    hits = []
    for rule in RULES:
        try:
            hit = rule(req)
            if hit:
                hits.append(hit)
        except Exception:
            hits.append(RuleHit(f"rule_error:{rule.__name__}", 0, "An applicable control could not be evaluated; verification is unavailable.", "unavailable"))
    return hits
