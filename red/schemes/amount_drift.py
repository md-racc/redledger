"""Scheme: Amount Drift. Owner: Dev Al."""

from __future__ import annotations

import math
from typing import Any

from agentkit import LedgerClient

from .base import SchemeBase
from .duplicate_invoice import _bump_invoice_number, _scale_line_items


class AmountDrift(SchemeBase):
    id = "amount_drift"
    display_name = "Amount Drift"
    story = "A recurring vendor's invoices climb a little every month."
    params_schema = {
        "type": "object",
        "properties": {
            "vendor_id": {"type": "string", "description": "Optional eligible target override; otherwise pick the first eligible id."},
            "step_pct": {
                "type": "number",
                "default": 0.03,
                "minimum": 0.001,
                "maximum": 0.15,
                "description": "Fractional increase above the target's trailing baseline.",
            },
        },
    }
    # Typical scenario range, not a cap on ledger-derived amounts.
    expected_impact = {"min": 300, "max": 15000}

    async def viable(self, ledger: LedgerClient) -> bool:
        return bool(await self._candidates(ledger))

    async def plan(self, ledger: LedgerClient, params: dict[str, Any]) -> dict[str, Any]:
        try:
            pct = float(params.get("step_pct", 0.03))
        except (TypeError, ValueError):
            raise ValueError("amount_drift: step_pct must be a finite number")
        if not math.isfinite(pct):
            raise ValueError("amount_drift: step_pct must be a finite number")
        pct = min(max(pct, 0.001), 0.15)
        candidates = await self._candidates(ledger)
        if "vendor_id" in params:
            candidates = [row for row in candidates if row["vendor_id"] == params["vendor_id"]]
        if not candidates:
            raise ValueError("amount_drift: no eligible target for the requested parameters")
        plan = dict(candidates[0])
        plan["step_pct"] = pct
        plan["target_amount"] = round(plan["baseline"] * (1 + pct), 2)
        source = plan.pop("source")
        plan["line_items"] = _scale_line_items(source.get("line_items"), float(source["amount"]), plan["target_amount"])
        return plan

    async def _candidates(self, ledger: LedgerClient) -> list[dict[str, Any]]:
        vendors = await ledger.list_vendors(status="active")
        invoices = await ledger.list_invoices(status="paid")
        candidates = []
        for vendor in sorted(vendors, key=lambda row: str(row["id"])):
            history = sorted(
                [row for row in invoices if row["vendor_id"] == vendor["id"] and row["status"] == "paid"],
                key=lambda row: (-int(row["received_day"]), str(row["id"])),
            )[:3]
            if vendor["status"] != "active" or len(history) < 3:
                continue
            mean = sum(float(row["amount"]) for row in history) / len(history)
            if mean <= 0 or any(abs(float(row["amount"]) - mean) > mean * 0.1 for row in history):
                continue
            source = history[0]
            number = _bump_invoice_number(str(source["invoice_number"]))
            existing = {row["invoice_number"] for row in invoices if row["vendor_id"] == vendor["id"]}
            while number in existing:
                number = _bump_invoice_number(number)
            candidates.append({"vendor_id": vendor["id"], "baseline": mean, "source": source, "invoice_number": number, "po_id": source.get("po_id")})
        return candidates

    async def execute(self, ledger: LedgerClient, plan: dict[str, Any]) -> str:
        body = {"vendor_id": plan["vendor_id"], "amount": plan["target_amount"], "invoice_number": plan["invoice_number"], "line_items": plan["line_items"]}
        if plan.get("po_id"):
            body["po_id"] = plan["po_id"]
        await ledger.submit_invoice(body)
        return f"Vendor {plan['vendor_id']} billed ${plan['target_amount']:,.2f} above trailing mean ${plan['baseline']:,.2f}"
