"""Scheme: Ghost Employee. Owner: Dev Al.

A contractor who was never onboarded (battlefield stores every red-created employee with
hr_record=false) appears on the books and files a few ordinary-looking expense claims. Blue's
`no_hr_record` rule should catch the approve/pay; the controller-off baseline should not.
"""

from __future__ import annotations

import hashlib
from typing import Any

from agentkit import LedgerClient

from .base import SchemeBase

# Plausible full names; picked deterministically by headcount so repeated runs vary without randomness.
NAMES = [
    "Daniel Whitfield",
    "Priya Raghunathan",
    "Marcus Delacroix",
    "Elena Sorensen",
    "Tobias Lindqvist",
    "Naomi Okafor",
    "Julian Barros",
    "Harriet Caldwell",
]

# Categories are drawn in order; memos read like real expense lines from the seeded traffic.
LINES = [
    ("travel", "Client site visit — mileage and lodging"),
    ("software", "Annual license renewal"),
    ("meals", "Team dinner, 4 attendees"),
    ("supplies", "Field kit and replacement parts"),
]

# Uneven splits of `total` by claim count, so the lines look like independent expenses.
SPLITS = {1: [1.0], 2: [0.58, 0.42], 3: [0.52, 0.30, 0.18]}

MIN_CLAIMS, MAX_CLAIMS = 1, 3
MIN_TOTAL, MAX_TOTAL = 200.0, 2500.0


def bank_account_for(name: str, taken: set[str]) -> str:
    """Stable 10-digit account derived from the name; bumps the salt until it collides with nothing."""
    salt = 0
    while True:
        digest = hashlib.sha256(f"{name}:{salt}".encode()).digest()
        acct = str(1_000_000_000 + int.from_bytes(digest[:8], "big") % 9_000_000_000)
        if acct not in taken:
            return acct
        salt += 1


def split_total(total: float, claims: int) -> list[float]:
    """Split `total` into `claims` 2dp amounts that sum exactly to `total`."""
    weights = SPLITS[claims]
    amounts = [round(total * w, 2) for w in weights[:-1]]
    amounts.append(round(total - sum(amounts), 2))
    return amounts


class GhostEmployee(SchemeBase):
    id = "ghost_employee"
    display_name = "Ghost Employee"
    story = "A contractor who was never onboarded appears on the books and starts filing expense claims."
    params_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "role": {"type": "string", "default": "Contractor"},
            "department": {"type": "string", "default": "operations"},
            "salary": {"type": "number", "default": 72000},
            "claims": {"type": "integer", "default": 3, "minimum": MIN_CLAIMS, "maximum": MAX_CLAIMS},
            "total": {"type": "number", "default": 1480, "minimum": MIN_TOTAL, "maximum": MAX_TOTAL},
            "bank_account": {"type": "string", "pattern": "^[0-9]{10}$"},
        },
    }
    expected_impact = {"min": 600, "max": 2500}

    async def viable(self, ledger: LedgerClient) -> bool:
        return True

    async def plan(self, ledger: LedgerClient, params: dict[str, Any]) -> dict[str, Any]:
        employees = await ledger.list_employees()
        vendors = await ledger.list_vendors()
        taken = {str(r.get("bank_account")) for r in [*employees, *vendors] if r.get("bank_account")}

        name = params.get("name") or NAMES[len(employees) % len(NAMES)]
        bank_account = params.get("bank_account") or bank_account_for(name, taken)
        claims = max(MIN_CLAIMS, min(MAX_CLAIMS, int(params.get("claims", 3))))
        total = round(max(MIN_TOTAL, min(MAX_TOTAL, float(params.get("total", 1480.0)))), 2)

        expenses = [{"amount": amount, "category": category, "memo": memo} for amount, (category, memo) in zip(split_total(total, claims), LINES, strict=False)]
        return {
            "target_amount": round(sum(e["amount"] for e in expenses), 2),
            "employee": {
                "name": name,
                "role": params.get("role", "Contractor"),
                "department": params.get("department", "operations"),
                "salary": float(params.get("salary", 72000)),
                "bank_account": bank_account,
            },
            "expenses": expenses,
        }

    async def execute(self, ledger: LedgerClient, plan: dict[str, Any]) -> str:
        emp = await ledger.create_employee(plan["employee"])
        for e in plan["expenses"]:
            await ledger.submit_expense({"employee_id": emp["id"], "amount": e["amount"], "category": e["category"], "memo": e["memo"]})
        n = len(plan["expenses"])
        noun = "claim" if n == 1 else "claims"
        return f"added {plan['employee']['name']} ({plan['employee']['role']}) and filed {n} expense {noun} totaling ${plan['target_amount']:,.2f}"
