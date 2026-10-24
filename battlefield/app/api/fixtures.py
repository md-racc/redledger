"""Operator fixtures: seed legit employees and expenses into an episode. Owner: Dev Ad.

contracts/ledger-api.yaml `POST /episodes/{id}/fixtures`. For acceptance runs that need specific,
ordinary data in the books (blue's CRS persona checks, #102). Operator only, one transaction, rows are
legit (`origin='sim'`, never an attack_id), so scoring treats them like seeded data. A bank_account that
collides with any account already in the episode (or another fixture's) is a 409 and nothing is
written, so replaying the same request is refused rather than duplicated.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .. import db
from ..auth import bearer
from ..events import bus

router = APIRouter(dependencies=[Depends(bearer)])


class FixtureEmployee(BaseModel):
    name: str = Field(min_length=1)
    role: str = Field(min_length=1)
    department: str | None = None
    salary: float = Field(ge=0)
    bank_account: str = Field(min_length=1)
    start_day: int = Field(ge=0)
    hr_record: bool = True
    status: Literal["active", "terminated", "frozen"] = "active"


class FixtureExpense(BaseModel):
    employee_ref: int | str
    amount: float = Field(gt=0)
    category: str = Field(min_length=1)
    submitted_day: int = Field(ge=0)
    memo: str | None = None


class FixturesCreate(BaseModel):
    employees: list[FixtureEmployee] = Field(default_factory=list, max_length=50)
    expenses: list[FixtureExpense] = Field(default_factory=list, max_length=200)


_ACCOUNTS_SQL = (
    "SELECT bank_account AS a FROM vendors WHERE episode_id=$1 "
    "UNION SELECT bank_account FROM employees WHERE episode_id=$1 "
    "UNION SELECT to_account FROM payments WHERE episode_id=$1"
)


def _collision(i: int) -> JSONResponse:
    return JSONResponse({"error": "bank_account collides", "bank_account_index": i}, status_code=409)


@router.post("/episodes/{episode_id}/fixtures", status_code=201)
async def create_fixtures(episode_id: str, body: FixturesCreate) -> Any:
    if not body.employees and not body.expenses:
        raise HTTPException(422, "nothing to create")
    for e in body.expenses:
        if isinstance(e.employee_ref, int) and not 0 <= e.employee_ref < len(body.employees):
            raise HTTPException(422, f"employee_ref {e.employee_ref} is not an index into employees")
    accounts = [e.bank_account for e in body.employees]
    for i, a in enumerate(accounts):
        if a in accounts[:i]:
            return _collision(i)

    async with db.pool().acquire() as conn, conn.transaction():
        ep = await conn.fetchrow("SELECT current_day FROM episodes WHERE id=$1 FOR SHARE", episode_id)
        if ep is None:
            raise HTTPException(404, "unknown episode")
        day = ep["current_day"]
        taken = {r["a"] for r in await conn.fetch(_ACCOUNTS_SQL, episode_id) if r["a"]}
        for i, a in enumerate(accounts):
            if a in taken:
                return _collision(i)  # nothing written yet; the transaction commits empty

        employees: list[dict[str, Any]] = []
        for e in body.employees:
            eid = db.new_id("emp")
            row = await conn.fetchrow(
                "INSERT INTO employees (id, episode_id, name, role, department, salary, bank_account, start_day, status, hr_record, origin) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,'sim') RETURNING *",
                eid,
                episode_id,
                e.name,
                e.role,
                e.department,
                e.salary,
                e.bank_account,
                e.start_day,
                e.status,
                e.hr_record,
            )
            employees.append(db.row_to_dict(row))

        expenses: list[dict[str, Any]] = []
        for x in body.expenses:
            if isinstance(x.employee_ref, int):
                emp_id = employees[x.employee_ref]["id"]
            else:
                emp_id = await conn.fetchval("SELECT id FROM employees WHERE id=$1 AND episode_id=$2", x.employee_ref, episode_id)
                if emp_id is None:
                    raise HTTPException(404, f"employee {x.employee_ref} not in episode")
            row = await conn.fetchrow(
                "INSERT INTO expenses (id, episode_id, employee_id, amount, category, memo, submitted_day, origin) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,'sim') RETURNING *",
                db.new_id("exp"),
                episode_id,
                emp_id,
                x.amount,
                x.category,
                x.memo,
                x.submitted_day,
            )
            expenses.append(db.row_to_dict(row))

        await conn.execute(
            "INSERT INTO audit_log (episode_id, day, agent, action, args, result, http_status) VALUES ($1,$2,'operator','fixtures.create',$3,$4,201)",
            episode_id,
            day,
            {"employees": len(body.employees), "expenses": len(body.expenses)},
            {"employee_ids": [e["id"] for e in employees], "expense_ids": [x["id"] for x in expenses]},
        )

    # After commit, like every other write route: one ledger.mutation per created row.
    for e in employees:
        await bus.emit(
            episode_id,
            day,
            "ledger.mutation",
            {"agent": "operator", "action": "employees.create", "entity_type": "employee", "entity_id": e["id"], "amount": None, "verdict_id": None},
        )
    for x in expenses:
        await bus.emit(
            episode_id,
            day,
            "ledger.mutation",
            {"agent": "operator", "action": "expenses.create", "entity_type": "expense", "entity_id": x["id"], "amount": x["amount"], "verdict_id": None},
        )
    return {"employees": employees, "expenses": expenses}
