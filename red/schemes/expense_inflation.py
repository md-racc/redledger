"""Scheme: Expense Inflation. Owner: Dev Al."""

from __future__ import annotations

import math
from typing import Any

from agentkit import LedgerClient

from .base import SchemeBase


class ExpenseInflation(SchemeBase):
    id = "expense_inflation"
    display_name = "Expense Inflation"
    story = "Reimbursements creep above what was actually spent."
    params_schema = {
        "type": "object",
        "properties": {
            "employee_id": {"type": "string", "description": "Optional eligible target override; otherwise pick the first eligible id."},
            "inflation_pct": {
                "type": "number",
                "default": 0.2,
                "minimum": 0.01,
                "maximum": 1.0,
                "description": "Fractional increase above the target's trailing baseline.",
            },
            "category": {"type": "string", "description": "Optional nonempty expense category; defaults to the most frequent trailing category."},
        },
    }
    # Typical scenario range, not a cap on ledger-derived amounts.
    expected_impact = {"min": 50, "max": 3000}

    async def viable(self, ledger: LedgerClient) -> bool:
        return bool(await self._candidates(ledger))

    async def plan(self, ledger: LedgerClient, params: dict[str, Any]) -> dict[str, Any]:
        try:
            pct = float(params.get("inflation_pct", 0.2))
        except (TypeError, ValueError):
            raise ValueError("expense_inflation: inflation_pct must be a finite number")
        if not math.isfinite(pct):
            raise ValueError("expense_inflation: inflation_pct must be a finite number")
        pct = min(max(pct, 0.01), 1.0)
        candidates = await self._candidates(ledger)
        if "employee_id" in params:
            candidates = [row for row in candidates if row["employee_id"] == params["employee_id"]]
        if not candidates:
            raise ValueError("expense_inflation: no eligible target for the requested parameters")
        plan = dict(candidates[0])
        plan["inflation_pct"] = pct
        plan["target_amount"] = round(plan["baseline"] * (1 + pct), 2)
        if "category" in params:
            if not isinstance(params["category"], str) or not params["category"].strip():
                raise ValueError("expense_inflation: category must be a nonempty string")
            plan["category"] = params["category"].strip()
        plan["memo"] = f"{plan['category']} reimbursement"
        return plan

    async def _candidates(self, ledger: LedgerClient) -> list[dict[str, Any]]:
        employees = await ledger.list_employees()
        expenses = await ledger.list_expenses()
        candidates = []
        for employee in sorted(employees, key=lambda row: str(row["id"])):
            history = sorted(
                [row for row in expenses if row["employee_id"] == employee["id"] and float(row["amount"]) > 0],
                key=lambda row: (-int(row["submitted_day"]), str(row["id"])),
            )[:10]
            if employee["status"] != "active" or not history:
                continue
            categories = [str(row["category"]) for row in history]
            category = min(set(categories), key=lambda value: (-categories.count(value), value))
            candidates.append({"employee_id": employee["id"], "baseline": sum(float(row["amount"]) for row in history) / len(history), "category": category})
        return candidates

    async def execute(self, ledger: LedgerClient, plan: dict[str, Any]) -> str:
        await ledger.submit_expense({"employee_id": plan["employee_id"], "amount": plan["target_amount"], "category": plan["category"], "memo": plan["memo"]})
        return f"Employee {plan['employee_id']} submitted {plan['category']} reimbursement for ${plan['target_amount']:,.2f}"
