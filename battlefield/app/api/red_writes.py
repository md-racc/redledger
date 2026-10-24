"""Red's write surface: attacker-plausible submissions only. Owner: Dev Ad (routes) / Dev M (consumer).

Red never pays, approves, or posts to the GL. Everything it creates is tagged origin='red' and,
when an attack has been declared this day, linked to it via attack_id for scoring.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import db
from ..auth import Caller, allow
from ..events import bus
from . import audit

router = APIRouter()


class VendorCreate(BaseModel):
    name: str
    ein: str | None = None
    bank_account: str
    bank_routing: str
    address: str | None = None
    category: str | None = None


class VendorChangeCreate(BaseModel):
    vendor_id: str
    field: str
    new_value: str
    justification: str | None = None


class InvoiceCreate(BaseModel):
    vendor_id: str
    amount: float
    invoice_number: str
    po_id: str | None = None
    line_items: list[dict[str, Any]] = Field(default_factory=list)
    due_in_days: int = 30


class ExpenseCreate(BaseModel):
    employee_id: str
    amount: float
    category: str
    memo: str | None = None


class EmployeeCreate(BaseModel):
    name: str
    role: str
    department: str | None = None
    salary: float
    bank_account: str


class AttackCreate(BaseModel):
    scheme_id: str
    display_name: str
    story: str
    params: dict[str, Any] = Field(default_factory=dict)
    target_amount: float


class AttackPatch(BaseModel):
    notes: str | None = None


async def _current_attack(c: Caller) -> str | None:
    """Most recent attack red declared today; used to link created rows."""
    return await db.fetchval("SELECT id FROM attacks WHERE episode_id=$1 AND day_launched=$2 ORDER BY id DESC LIMIT 1", c.episode_id, c.day)


@router.post("/attacks", status_code=201)
async def declare_attack(body: AttackCreate, c: Caller = Depends(allow("red", operator=False))):
    aid = db.new_id("atk")
    await db.execute(
        "INSERT INTO attacks (id, episode_id, scheme_id, display_name, story, day_launched, params, target_amount) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
        aid,
        c.episode_id,
        body.scheme_id,
        body.display_name,
        body.story,
        c.day,
        body.params,
        body.target_amount,
    )
    await bus.emit(
        c.episode_id,
        c.day,
        "attack.launched",  # type: ignore[arg-type]
        {"attack_id": aid, "scheme_id": body.scheme_id, "display_name": body.display_name, "story": body.story, "target_amount": body.target_amount},
    )
    row = await db.fetchrow("SELECT * FROM attacks WHERE id=$1", aid)
    await audit.record(c, "attacks.declare", body.model_dump(), {"id": aid}, 201)
    return db.row_to_dict(row)


@router.patch("/attacks/{attack_id}")
async def patch_attack(attack_id: str, body: AttackPatch, c: Caller = Depends(allow("red", operator=False))):
    await db.execute("UPDATE attacks SET notes=COALESCE($2, notes) WHERE id=$1 AND episode_id=$3", attack_id, body.notes, c.episode_id)
    await audit.record(c, "attacks.patch", body.model_dump(), {}, 200)
    return {"ok": True}


@router.post("/vendors", status_code=201)
async def create_vendor(body: VendorCreate, c: Caller = Depends(allow("red", operator=False))):
    vid = db.new_id("ven")
    await db.execute(
        "INSERT INTO vendors (id, episode_id, name, ein, bank_account, bank_routing, address, category, created_day, origin, created_by) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,'red',$10)",
        vid,
        c.episode_id,
        body.name,
        body.ein,
        body.bank_account,
        body.bank_routing,
        body.address,
        body.category,
        c.day,
        c.agent,
    )
    await audit.record(c, "vendors.create", body.model_dump(), {"id": vid}, 201)
    await audit.mutation(c, "vendors.create", "vendor", vid)
    return db.row_to_dict(await db.fetchrow("SELECT * FROM vendors WHERE id=$1", vid), hide=True)


@router.post("/vendor_changes", status_code=201)
async def request_vendor_change(body: VendorChangeCreate, c: Caller = Depends(allow("red", operator=False))):
    if body.field not in ("bank_account", "bank_routing", "address", "name"):
        raise HTTPException(422, "bad field")
    v = await db.fetchrow("SELECT * FROM vendors WHERE id=$1 AND episode_id=$2", body.vendor_id, c.episode_id)
    if not v:
        raise HTTPException(404, "vendor not found")
    cid = db.new_id("vch")
    await db.execute(
        "INSERT INTO vendor_changes (id, episode_id, vendor_id, field, old_value, new_value, justification, requested_day, origin) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'red')",
        cid,
        c.episode_id,
        body.vendor_id,
        body.field,
        v[body.field],
        body.new_value,
        body.justification,
        c.day,
    )
    await audit.record(c, "vendor_changes.create", body.model_dump(), {"id": cid}, 201)
    await audit.mutation(c, "vendor_changes.create", "vendor_change", cid)
    return db.row_to_dict(await db.fetchrow("SELECT * FROM vendor_changes WHERE id=$1", cid), hide=True)


@router.post("/invoices", status_code=201)
async def submit_invoice(body: InvoiceCreate, c: Caller = Depends(allow("red", operator=False))):
    v = await db.fetchrow("SELECT id FROM vendors WHERE id=$1 AND episode_id=$2", body.vendor_id, c.episode_id)
    if not v:
        raise HTTPException(404, "vendor not found")
    iid = db.new_id("inv")
    await db.execute(
        "INSERT INTO invoices (id, episode_id, vendor_id, po_id, amount, invoice_number, line_items, received_day, due_day, origin, attack_id) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,'red',$10)",
        iid,
        c.episode_id,
        body.vendor_id,
        body.po_id,
        body.amount,
        body.invoice_number,
        body.line_items,
        c.day,
        c.day + body.due_in_days,
        await _current_attack(c),
    )
    await audit.record(c, "invoices.submit", body.model_dump(), {"id": iid}, 201)
    await audit.mutation(c, "invoices.submit", "invoice", iid, body.amount)
    return db.row_to_dict(await db.fetchrow("SELECT * FROM invoices WHERE id=$1", iid), hide=True)


@router.post("/expenses", status_code=201)
async def submit_expense(body: ExpenseCreate, c: Caller = Depends(allow("red", operator=False))):
    e = await db.fetchrow("SELECT id FROM employees WHERE id=$1 AND episode_id=$2", body.employee_id, c.episode_id)
    if not e:
        raise HTTPException(404, "employee not found")
    xid = db.new_id("exp")
    await db.execute(
        "INSERT INTO expenses (id, episode_id, employee_id, amount, category, memo, submitted_day, origin, attack_id) VALUES ($1,$2,$3,$4,$5,$6,$7,'red',$8)",
        xid,
        c.episode_id,
        body.employee_id,
        body.amount,
        body.category,
        body.memo,
        c.day,
        await _current_attack(c),
    )
    await audit.record(c, "expenses.submit", body.model_dump(), {"id": xid}, 201)
    await audit.mutation(c, "expenses.submit", "expense", xid, body.amount)
    return db.row_to_dict(await db.fetchrow("SELECT * FROM expenses WHERE id=$1", xid), hide=True)


@router.post("/employees", status_code=201)
async def create_employee(body: EmployeeCreate, c: Caller = Depends(allow("red", operator=False))):
    eid = db.new_id("emp")
    await db.execute(
        "INSERT INTO employees (id, episode_id, name, role, department, salary, bank_account, start_day, hr_record, origin) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,false,'red')",
        eid,
        c.episode_id,
        body.name,
        body.role,
        body.department,
        body.salary,
        body.bank_account,
        c.day,
    )
    await audit.record(c, "employees.create", body.model_dump(), {"id": eid}, 201)
    await audit.mutation(c, "employees.create", "employee", eid)
    return db.row_to_dict(await db.fetchrow("SELECT * FROM employees WHERE id=$1", eid), hide=True)
