"""Scheme: Duplicate Invoice. Owner: Dev Al.

Resubmit an already-paid invoice under a follow-on invoice number with the amount nudged by a
small drift so blue's exact-match duplicate rule (within max($0.05, 1%) of a paid invoice from
the same vendor) does not fire. drift_pct=0 is the crude, exact-cents variant a judge can pick
to show the rule catching it.
"""

from __future__ import annotations

import re
from typing import Any

from agentkit import LedgerClient

from .base import SchemeBase

DEFAULT_DRIFT_PCT = 0.018
MIN_DRIFT_PCT = 0.0
MAX_DRIFT_PCT = 0.08
NUMBER_BUMP = 3  # INV-54321 -> INV-54324: looks like the vendor's next-but-two invoice
RECENT_WINDOW = 20  # pick the richest target among the vendor-agnostic last N paid invoices
THRESHOLD_LO, THRESHOLD_HI = 4750.0, 5000.0  # blue's near_threshold band
THRESHOLD_ESCAPE = 300.0

_TRAILING_INT = re.compile(r"^(.*?)(\d+)$")


def _bump_invoice_number(number: str) -> str:
    """Derive a plausible follow-on number: bump the trailing integer (zero-padding preserved) or append -R1."""
    m = _TRAILING_INT.match(number)
    if not m:
        return f"{number}-R1"
    prefix, digits = m.groups()
    return f"{prefix}{int(digits) + NUMBER_BUMP:0{len(digits)}d}"


def _scale_line_items(items: list[dict[str, Any]] | None, source_amount: float, target_amount: float) -> list[dict[str, Any]]:
    """Scale the source's line items so they sum to target_amount (last line absorbs rounding)."""
    if not items or source_amount <= 0:
        return [{"desc": "services", "amount": target_amount}]
    factor = target_amount / source_amount
    scaled = [{"desc": str(it.get("desc", "services")), "amount": round(float(it.get("amount", 0.0)) * factor, 2)} for it in items]
    scaled[-1]["amount"] = round(scaled[-1]["amount"] + (target_amount - sum(it["amount"] for it in scaled)), 2)
    return scaled


class DuplicateInvoice(SchemeBase):
    id = "duplicate_invoice"
    display_name = "Duplicate Invoice"
    story = "A paid invoice is resubmitted under a new number with the amount nudged so it no longer matches exactly."
    params_schema = {
        "type": "object",
        "properties": {
            "invoice_id": {"type": "string", "description": "Paid invoice to duplicate; defaults to the largest of the 20 most recent paid invoices."},
            "drift_pct": {
                "type": "number",
                "default": DEFAULT_DRIFT_PCT,
                "minimum": MIN_DRIFT_PCT,
                "maximum": MAX_DRIFT_PCT,
                "description": "Fractional change applied to the amount. 0 = exact duplicate (crude; blue catches it).",
            },
            "reuse_po": {"type": "boolean", "default": True, "description": "Reference the source invoice's PO so the copy looks PO-backed."},
        },
    }
    expected_impact = {"min": 300, "max": 9000}

    async def viable(self, ledger: LedgerClient) -> bool:
        return bool(await ledger.list_invoices(status="paid"))

    async def _pick_source(self, ledger: LedgerClient, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("invoice_id"):
            return await ledger.get_invoice(str(params["invoice_id"]))
        paid = await ledger.list_invoices(status="paid")
        if not paid:
            raise ValueError("duplicate_invoice: no paid invoices to duplicate")
        recent = sorted(paid, key=lambda inv: (-int(inv.get("received_day", 0)), str(inv.get("id", ""))))[:RECENT_WINDOW]
        return max(recent, key=lambda inv: float(inv["amount"]))

    async def plan(self, ledger: LedgerClient, params: dict[str, Any]) -> dict[str, Any]:
        source = await self._pick_source(ledger, params)
        drift_pct = min(max(float(params.get("drift_pct", DEFAULT_DRIFT_PCT)), MIN_DRIFT_PCT), MAX_DRIFT_PCT)
        reuse_po = bool(params.get("reuse_po", True))

        source_amount = float(source["amount"])
        target_amount = round(source_amount * (1.0 + drift_pct), 2)
        if THRESHOLD_LO <= target_amount < THRESHOLD_HI:
            target_amount = round(target_amount + THRESHOLD_ESCAPE, 2)

        source_number = str(source["invoice_number"])
        return {
            "target_amount": target_amount,
            "vendor_id": source["vendor_id"],
            "source_invoice_id": source["id"],
            "source_invoice_number": source_number,
            "invoice_number": _bump_invoice_number(source_number),
            "po_id": source.get("po_id") if reuse_po else None,
            "drift_pct": drift_pct,
            "line_items": _scale_line_items(source.get("line_items"), source_amount, target_amount),
        }

    async def execute(self, ledger: LedgerClient, plan: dict[str, Any]) -> str:
        body: dict[str, Any] = {
            "vendor_id": plan["vendor_id"],
            "amount": plan["target_amount"],
            "invoice_number": plan["invoice_number"],
            "line_items": plan["line_items"],
        }
        if plan.get("po_id"):
            body["po_id"] = plan["po_id"]
        await ledger.submit_invoice(body)
        return f"resubmitted {plan['source_invoice_number']} as {plan['invoice_number']} for ${plan['target_amount']:,.2f}"
