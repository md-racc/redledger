"""Scheme: Threshold Splitting. Owner: Dev Al.

One large job is billed as several smaller invoices that each stay under the auto-approval line.
Mirrors the ghost_vendor reference: plan() resolves params + ledger state into concrete amounts and
invoice numbers; execute() performs the writes (<=4). The caller declares the attack between the two.
"""

from __future__ import annotations

import hashlib
import os
import re
from typing import Any

from agentkit import LedgerClient

from .base import SchemeBase

_VENDOR_NAMES = [
    "Summit Facilities Group LLC",
    "Meridian Professional Services LLC",
    "Keystone Facility Partners LLC",
    "Vanguard Advisory Group LLC",
    "Cornerstone Building Services LLC",
    "Ironwood Professional Group LLC",
]


def _digits(seed: str, n: int) -> str:
    """Deterministic n-digit string from a seed (first digit never 0)."""
    digits = ""
    h = seed
    while len(digits) < n:
        h = hashlib.sha256(h.encode()).hexdigest()
        digits += "".join(c for c in h if c.isdigit())
    d = digits[:n]
    return ("1" + d[1:]) if d[0] == "0" else d


def _split_number(s: str) -> tuple[str, str] | None:
    """Split an invoice number into (prefix, trailing-integer-as-string)."""
    m = re.match(r"^(.*?)(\d+)$", s or "")
    return (m.group(1), m.group(2)) if m else None


def _latest_number(paids: list[dict]) -> str | None:
    """The paid invoice number with the largest trailing integer (proxy for latest)."""
    best: str | None = None
    best_val = -1
    for inv in paids:
        num = inv.get("invoice_number")
        sp = _split_number(num) if num else None
        if sp and int(sp[1]) > best_val:
            best_val = int(sp[1])
            best = num
    return best


def _invoice_numbers(latest: str | None, parts: int, seed: str) -> list[str]:
    """Continue the vendor's numbering (+2, +3, +4 ...), else deterministic INV-NNNNN."""
    sp = _split_number(latest) if latest else None
    if sp:
        prefix, digits = sp
        width = len(digits)
        start = int(digits)
        return [f"{prefix}{str(start + k + 2).zfill(width)}" for k in range(parts)]
    base = int(_digits(seed + "invnum", 5))
    return [f"INV-{(base + k + 2) % 100000:05d}" for k in range(parts)]


def _new_vendor(seed: str) -> tuple[dict[str, Any], str]:
    """Deterministic facilities/professional-services vendor body + its name."""
    h = int(hashlib.sha256(seed.encode()).hexdigest(), 16)
    name = _VENDOR_NAMES[h % len(_VENDOR_NAMES)]
    ein_d = _digits(seed + "ein", 9)
    body = {
        "name": name,
        "ein": f"{ein_d[:2]}-{ein_d[2:]}",
        "bank_account": _digits(seed + "acct", 10),
        "bank_routing": _digits(seed + "rout", 9),
        "category": "facilities" if h % 2 == 0 else "professional",
    }
    return body, name


def _resolve(total: float, parts: int, threshold: float, max_parts: int) -> tuple[float, int]:
    """Keep the per-part mean under 0.93*threshold: raise parts first, then lower total."""
    cap = 0.93 * threshold
    parts = max(2, min(parts, max_parts))
    while total / parts >= cap and parts < max_parts:
        parts += 1
    if total / parts >= cap:
        parts = max_parts
        total = parts * 0.9 * threshold
    return total, parts


def _collides(amount: float, others: list[float]) -> bool:
    """True if `amount` is within max($0.05, 1%) of any value in `others` (blue's duplicate rule)."""
    return any(abs(amount - o) <= max(0.05, 0.01 * min(amount, o)) for o in others if o > 0)


class ThresholdSplit(SchemeBase):
    id = "threshold_split"
    display_name = "Threshold Splitting"
    story = "One large job is billed as several smaller invoices that each stay under the auto-approval line."
    params_schema = {
        "type": "object",
        "properties": {
            "total": {"type": "number", "default": 13800, "minimum": 6000, "maximum": 20000},
            "parts": {"type": "integer", "default": 3, "minimum": 2, "maximum": 4},
            "vendor_id": {"type": "string"},
            "new_vendor": {"type": "boolean", "default": False},
            "threshold": {"type": "number", "default": 5000},
        },
    }
    expected_impact = {"min": 9000, "max": 15000}

    async def viable(self, ledger: LedgerClient) -> bool:
        return True

    async def plan(self, ledger: LedgerClient, params: dict[str, Any]) -> dict[str, Any]:
        threshold = float(params.get("threshold", os.environ.get("APPROVAL_THRESHOLD", "5000")))
        total = float(params.get("total", 13800.0))
        parts = int(params.get("parts", 3))
        new_vendor = bool(params.get("new_vendor", False))
        explicit_vid = params.get("vendor_id")
        description = params.get("description") or "Facility refurbishment project"

        vendor_id: str | None = None
        vendor_name: str | None = None
        paid_amounts: list[float] = []
        latest_number: str | None = None

        if explicit_vid:
            v = await ledger.get_vendor(explicit_vid)
            vendor_id = v["id"]
            vendor_name = v.get("name")
            paids = await ledger.list_invoices(status="paid", vendor_id=vendor_id)
            paid_amounts = [float(i["amount"]) for i in paids]
            latest_number = _latest_number(paids)
        elif not new_vendor:
            actives = await ledger.list_vendors(status="active")
            all_paid = await ledger.list_invoices(status="paid")
            by_vendor: dict[str, list[dict]] = {}
            for inv in all_paid:
                by_vendor.setdefault(inv["vendor_id"], []).append(inv)
            best = None
            best_mean = -1.0
            for v in actives:
                amts = [float(i["amount"]) for i in by_vendor.get(v["id"], [])]
                if amts:
                    m = sum(amts) / len(amts)
                    if m > best_mean:
                        best_mean = m
                        best = v
            if best is not None:
                vendor_id = best["id"]
                vendor_name = best.get("name")
                paid_amounts = [float(i["amount"]) for i in by_vendor[vendor_id]]
                latest_number = _latest_number(by_vendor[vendor_id])

        creating = vendor_id is None
        vendor_body: dict[str, Any] | None = None
        if creating:
            vendor_body, vendor_name = _new_vendor(f"threshold_split:{total}:{parts}")

        max_parts = 3 if creating else 4
        total, parts = _resolve(total, parts, threshold, max_parts)

        amounts = self._amounts(total, parts, threshold)
        # Avoid blue's duplicate_invoice rule: nudge any amount too close to a paid one by $37 steps.
        cap = 0.93 * threshold
        for idx in range(len(amounts)):
            tries = 0
            while tries < 20 and _collides(amounts[idx], paid_amounts):
                cand = round(amounts[idx] + 37, 2)
                others = [a for j, a in enumerate(amounts) if j != idx]
                if cand >= cap or _collides(cand, others):
                    cand = round(amounts[idx] - 37, 2)
                amounts[idx] = cand
                tries += 1

        seed = (vendor_name or vendor_id or "threshold_split") + f":{total}"
        invoice_numbers = _invoice_numbers(latest_number, parts, seed)

        return {
            "target_amount": round(sum(amounts), 2),
            "vendor_id": None if creating else vendor_id,
            "vendor": vendor_body,
            "vendor_name": vendor_name,
            "amounts": amounts,
            "invoice_numbers": invoice_numbers,
            "description": description,
        }

    @staticmethod
    def _amounts(total: float, parts: int, threshold: float) -> list[float]:
        """Uneven amounts summing to `total`, each < 0.93*threshold, pairwise >1% apart."""
        mean = total / parts
        cap = 0.93 * threshold
        step_lo = 0.0101 * mean  # just above the 1% pairwise rule
        step_hi = 2 * (cap - mean) / (parts - 1)  # keep max amount under cap
        step = (step_lo + step_hi) / 2 if step_lo < step_hi else step_lo * 0.999
        offsets = [step * (i - (parts - 1) / 2) for i in range(parts)]
        amounts = [round(mean + off, 2) for off in offsets]
        # Restore exact sum by adjusting an element near the mean (keeps extremes within band).
        mid = parts // 2
        amounts[mid] = round(amounts[mid] + round(total - sum(amounts), 2), 2)
        return amounts

    async def execute(self, ledger: LedgerClient, plan: dict[str, Any]) -> str:
        vendor_id = plan["vendor_id"]
        name = plan.get("vendor_name")
        if plan["vendor"]:
            v = await ledger.create_vendor(plan["vendor"])
            vendor_id = v["id"]
            name = plan["vendor"]["name"]
        n = len(plan["amounts"])
        for k, (amt, num) in enumerate(zip(plan["amounts"], plan["invoice_numbers"], strict=True), start=1):
            await ledger.submit_invoice(
                {
                    "vendor_id": vendor_id,
                    "amount": amt,
                    "invoice_number": num,
                    "line_items": [{"desc": f"{plan['description']} — phase {k} of {n}", "amount": amt}],
                }
            )
        return f"split ${plan['target_amount']:,.2f} across {n} invoices to {name}"
