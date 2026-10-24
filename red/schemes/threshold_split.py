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


CAP_RATIO = 0.93  # every part stays under this fraction of the approval line (blue's near_threshold band starts at 0.95)
GAP = 0.0101  # pairwise spacing, just over blue's 1% duplicate tolerance


def _max_total(parts: int, cap: float) -> float:
    """Largest total for which `parts` amounts can all sit under `cap` while staying >1% apart.

    The spread is symmetric around the mean with half-width h = (parts-1)/2 steps, so the top part is
    mean + h*step and the pairwise rule needs step >= GAP*top. Solving leaves mean <= cap*(1 - GAP*h);
    the extra 0.0005 is rounding margin.
    """
    h = (parts - 1) / 2
    return float(int(parts * cap * (1 - GAP * h - 0.0005) * 100) / 100)


def _resolve(total: float, parts: int, threshold: float, max_parts: int) -> tuple[float, int]:
    """Keep the per-part mean under the cap: raise parts first, then clamp the total."""
    cap = CAP_RATIO * threshold
    parts = max(2, min(parts, max_parts))
    while total > _max_total(parts, cap) and parts < max_parts:
        parts += 1
    return min(total, _max_total(parts, cap)), parts


def _collides(amount: float, others: list[float]) -> bool:
    """True if `amount` is within max($0.05, 1%) of any value in `others` (blue's duplicate rule, conservative)."""
    return any(abs(amount - o) <= max(0.05, 0.01 * max(amount, o)) for o in others if o > 0)


def _ok(amount: float, cap: float, paid: list[float], others: list[float]) -> bool:
    return 0 < amount < cap and not _collides(amount, paid) and not _collides(amount, others)


def _dodge(amounts: list[float], total: float, cap: float, paid: list[float]) -> list[float] | None:
    """Move any part that sits within 1% of a paid invoice, keeping every part under the cap, >1% from the
    others, and the total exact. Returns None when no arrangement is found (caller lowers the total)."""
    amounts = list(amounts)
    for _ in range(len(amounts) * 2):
        bad = [i for i, a in enumerate(amounts) if _collides(a, paid)]
        if not bad:
            break
        i = bad[0]
        others = [a for j, a in enumerate(amounts) if j != i]
        moved = False
        for delta in (37, -37, 74, -74, 111, -111, 148, -148):
            cand = round(amounts[i] + delta, 2)
            if not _ok(cand, cap, paid, others):
                continue
            # rebalance the residual onto a different part that still passes every check
            residual = round(total - (sum(others) + cand), 2)
            for j in range(len(amounts)):
                if j == i:
                    continue
                fixed = round(amounts[j] + residual, 2)
                rest = [cand] + [a for k, a in enumerate(amounts) if k not in (i, j)]
                if _ok(fixed, cap, paid, rest):
                    amounts[i], amounts[j] = cand, fixed
                    moved = True
                    break
            if moved:
                break
        if not moved:
            return None
    if any(_collides(a, paid) for a in amounts) or abs(sum(amounts) - total) > 0.011:
        return None
    return amounts


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
    expected_impact = {"min": 6000, "max": 15000}

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

            # Blue's no_po_from_po_vendor rule flags a no-PO invoice from a vendor whose >=3 paid invoices all
            # carry a PO. Prefer vendors already paid without a PO, then thin histories, then the biggest bills.
            def _rank(v: dict) -> tuple[int, float, str]:
                paids = by_vendor.get(v["id"], [])
                amts = [float(i["amount"]) for i in paids]
                tier = 0 if any(not i.get("po_id") for i in paids) else (1 if len(paids) < 3 else 2)
                return (tier, -(sum(amts) / len(amts)), str(v["id"]))

            candidates = [v for v in actives if by_vendor.get(v["id"])]
            best = min(candidates, key=_rank) if candidates else None
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

        # Avoid blue's duplicate_invoice rule; if no arrangement works at this total, lower it and retry.
        cap = CAP_RATIO * threshold
        amounts: list[float] | None = None
        for _ in range(15):
            amounts = _dodge(self._amounts(total, parts, threshold), total, cap, paid_amounts)
            if amounts is not None:
                break
            total = float(int(total * 0.985 * 100) / 100)
        if amounts is None:  # pathological ledger; fall back to the clean spread and let the dice roll
            amounts = self._amounts(total, parts, threshold)

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
        """Uneven amounts summing to `total`, each < CAP_RATIO*threshold, pairwise >1% apart.

        `total` must already be <= _max_total(parts, cap) (see _resolve), which guarantees a step exists.
        """
        mean = total / parts
        cap = CAP_RATIO * threshold
        h = (parts - 1) / 2
        step_lo = GAP * mean / (1 - GAP * h)  # pairwise gap measured against the largest part
        step_hi = (cap - mean) / h * 0.999  # keep the largest part under the cap
        step = min(step_lo * 1.3, step_hi) if step_lo <= step_hi else step_lo
        amounts = [round(mean + step * (i - h), 2) for i in range(parts)]
        # Restore the exact sum on the smallest part: the residue is rounding noise, so the gap and cap hold.
        amounts[0] = round(amounts[0] + round(total - sum(amounts), 2), 2)
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
