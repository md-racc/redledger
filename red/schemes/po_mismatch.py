"""Scheme: PO Mismatch. Owner: Dev Al."""

from __future__ import annotations

import math
from typing import Any

from agentkit import LedgerClient

from .base import SchemeBase
from .duplicate_invoice import _bump_invoice_number


class PoMismatch(SchemeBase):
    id = "po_mismatch"
    display_name = "PO Mismatch"
    story = "An invoice is billed well above its purchase order."
    params_schema = {
        "type": "object",
        "properties": {
            "po_id": {"type": "string", "description": "Optional eligible target override; otherwise pick the first eligible id."},
            "overage_pct": {
                "type": "number",
                "default": 0.2,
                "minimum": 0.01,
                "maximum": 1.0,
                "description": "Fractional increase above the target's trailing baseline.",
            },
        },
    }
    # Typical scenario range, not a cap on ledger-derived amounts.
    expected_impact = {"min": 300, "max": 30000}

    async def viable(self, ledger: LedgerClient) -> bool:
        return bool(await self._candidates(ledger))

    async def plan(self, ledger: LedgerClient, params: dict[str, Any]) -> dict[str, Any]:
        try:
            pct = float(params.get("overage_pct", 0.2))
        except (TypeError, ValueError):
            raise ValueError("po_mismatch: overage_pct must be a finite number")
        if not math.isfinite(pct):
            raise ValueError("po_mismatch: overage_pct must be a finite number")
        pct = min(max(pct, 0.01), 1.0)
        candidates = await self._candidates(ledger)
        if "po_id" in params:
            candidates = [row for row in candidates if row["po_id"] == params["po_id"]]
        if not candidates:
            raise ValueError("po_mismatch: no eligible target for the requested parameters")
        plan = dict(candidates[0])
        plan["overage_pct"] = pct
        plan["target_amount"] = round(plan["baseline"] * (1 + pct), 2)
        plan["line_items"] = [{"desc": plan.pop("description"), "amount": plan["target_amount"]}]
        return plan

    async def _candidates(self, ledger: LedgerClient) -> list[dict[str, Any]]:
        pos = await ledger.list_purchase_orders(status="open")
        vendors = await ledger.list_vendors(status="active")
        invoices = await ledger.list_invoices()
        active = {row["id"] for row in vendors if row["status"] == "active"}
        used = {row.get("po_id") for row in invoices}
        candidates = []
        for po in sorted(pos, key=lambda row: str(row["id"])):
            if po["status"] != "open" or po["vendor_id"] not in active or po["id"] in used or float(po["amount"]) <= 0:
                continue
            history = sorted([row for row in invoices if row["vendor_id"] == po["vendor_id"]], key=lambda row: (-int(row["received_day"]), str(row["id"])))
            number = _bump_invoice_number(str(history[0]["invoice_number"])) if history else f"INV-{po['id']}-1"
            existing = {row["invoice_number"] for row in history}
            while number in existing:
                number = _bump_invoice_number(number)
            candidates.append(
                {
                    "po_id": po["id"],
                    "vendor_id": po["vendor_id"],
                    "baseline": float(po["amount"]),
                    "po_amount": float(po["amount"]),
                    "description": po.get("description") or "services",
                    "invoice_number": number,
                }
            )
        return candidates

    async def execute(self, ledger: LedgerClient, plan: dict[str, Any]) -> str:
        await ledger.submit_invoice(
            {
                "vendor_id": plan["vendor_id"],
                "amount": plan["target_amount"],
                "invoice_number": plan["invoice_number"],
                "po_id": plan["po_id"],
                "line_items": plan["line_items"],
            }
        )
        return f"PO {plan['po_id']} billed ${plan['target_amount']:,.2f} against ${plan['po_amount']:,.2f}"
