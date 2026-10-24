"""Green's write surface: the AP workflow. Every route is gated. Owner: Dev Ad (routes) / Dev M (consumer).

Pattern per route:
  1. load entity, 409 if state doesn't allow the action
  2. assemble blue's context (vendor, PO, recent changes, paid history)
  3. gate.check() → Decision or GateBlockedError
  4. on block: mark entity 'blocked', audit, 403 {verdict, reason, verdict_id}
  5. on allow: mutate, audit, emit ledger.mutation (with verdict_id when one exists)
Every response an agent gets is audited (AGENTS.md §3.5), including the 404/409 rejections in step 1
and a 409 when the X-Tool-Use-Id was already judged for a different action (the verdict is not replayed).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .. import db
from ..auth import Caller, allow
from ..gate import gatekeeper as gate
from . import audit

router = APIRouter()
GREEN = allow("green", operator=False)


class Reason(BaseModel):
    reason: str


class MatchBody(BaseModel):
    po_id: str


class GlEntryCreate(BaseModel):
    account: str
    debit: float = 0.0
    credit: float = 0.0
    memo: str | None = None
    ref_type: str | None = None
    ref_id: str | None = None


# ---------- context assembly for blue ----------


async def _invoice_context(inv: dict[str, Any]) -> dict[str, Any]:
    ep = inv["episode_id"]
    vendor = db.row_to_dict(await db.fetchrow("SELECT * FROM vendors WHERE id=$1", inv["vendor_id"]), hide=True)
    po = db.row_to_dict(await db.fetchrow("SELECT * FROM purchase_orders WHERE id=$1", inv["po_id"]), hide=True) if inv.get("po_id") else None
    changes = db.rows_to_list(
        await db.fetch("SELECT * FROM vendor_changes WHERE episode_id=$1 AND vendor_id=$2 ORDER BY requested_day DESC LIMIT 10", ep, inv["vendor_id"]),
        hide=True,
    )
    paid = db.rows_to_list(
        await db.fetch(
            "SELECT * FROM invoices WHERE episode_id=$1 AND vendor_id=$2 AND status='paid' ORDER BY received_day DESC LIMIT 12", ep, inv["vendor_id"]
        ),
        hide=True,
    )
    pos = db.rows_to_list(
        await db.fetch("SELECT * FROM purchase_orders WHERE episode_id=$1 AND vendor_id=$2 ORDER BY created_day DESC LIMIT 12", ep, inv["vendor_id"]), hide=True
    )
    flags = db.rows_to_list(
        await db.fetch(
            "SELECT * FROM flags WHERE episode_id=$1 AND ((entity_type='vendor' AND entity_id=$2) OR (entity_type='invoice' AND entity_id=$3))",
            ep,
            inv["vendor_id"],
            inv["id"],
        )
    )
    return {
        "invoice": {k: db._jsonable(v) for k, v in inv.items() if k not in db.HIDDEN_COLUMNS},
        "vendor": vendor,
        "po": po,
        "vendor_recent_changes": changes,
        "vendor_paid_invoices": paid,
        "vendor_purchase_orders": pos,
        "flags": flags,
    }


async def _expense_context(exp: dict[str, Any]) -> dict[str, Any]:
    ep = exp["episode_id"]
    employee = db.row_to_dict(await db.fetchrow("SELECT * FROM employees WHERE id=$1", exp["employee_id"]), hide=True)
    history = db.rows_to_list(
        await db.fetch(
            "SELECT * FROM expenses WHERE episode_id=$1 AND employee_id=$2 AND id<>$3 ORDER BY submitted_day DESC LIMIT 12", ep, exp["employee_id"], exp["id"]
        ),
        hide=True,
    )
    vendor_match = db.rows_to_list(
        await db.fetch("SELECT id, name FROM vendors WHERE episode_id=$1 AND bank_account=$2", ep, employee["bank_account"] if employee else ""), hide=True
    )
    return {
        "expense": {k: db._jsonable(v) for k, v in exp.items() if k not in db.HIDDEN_COLUMNS},
        "employee": employee,
        "employee_expense_history": history,
        "vendors_sharing_bank_account": vendor_match,
    }


async def _change_context(ch: dict[str, Any]) -> dict[str, Any]:
    ep = ch["episode_id"]
    vendor = db.row_to_dict(await db.fetchrow("SELECT * FROM vendors WHERE id=$1", ch["vendor_id"]), hide=True)
    pending = db.rows_to_list(
        await db.fetch("SELECT * FROM invoices WHERE episode_id=$1 AND vendor_id=$2 AND status IN ('pending','matched','approved')", ep, ch["vendor_id"]),
        hide=True,
    )
    prior = db.rows_to_list(
        await db.fetch(
            "SELECT * FROM vendor_changes WHERE episode_id=$1 AND vendor_id=$2 AND id<>$3 ORDER BY requested_day DESC LIMIT 10", ep, ch["vendor_id"], ch["id"]
        ),
        hide=True,
    )
    return {
        "vendor_change": {k: db._jsonable(v) for k, v in ch.items() if k not in db.HIDDEN_COLUMNS},
        "vendor": vendor,
        "vendor_open_invoices": pending,
        "vendor_prior_changes": prior,
    }


# ---------- helpers ----------


async def _reject(c: Caller, action: str, args: dict[str, Any], status: int, detail: str) -> HTTPException:
    """Audit a rejection that happens before the gate, then hand back the exception to raise."""
    await audit.record(c, action, args, {"error": detail}, status)
    return HTTPException(status, detail)


async def _load(table: str, id_: str, c: Caller, action: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    row = await db.fetchrow(f"SELECT * FROM {table} WHERE id=$1 AND episode_id=$2", id_, c.episode_id)
    if not row:
        raise await _reject(c, action, args or {"id": id_}, 404, f"{table[:-1]} not found")
    return dict(row)


def _conflict_response(e: gate.IdempotencyConflictError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"error": gate.IDEMPOTENCY_CONFLICT, "verdict_id": e.verdict_id})


def _blocked_response(e: gate.GateBlockedError) -> JSONResponse:
    return JSONResponse(status_code=403, content={"verdict": "block", "reason": e.reason, "verdict_id": e.verdict_id, "escalation_id": e.escalation_id})


async def _gated(
    c: Caller, action: str, entity_type: str, entity: dict[str, Any], amount: float | None, ctx: dict[str, Any], table: str, args: dict[str, Any] | None = None
):
    try:
        return await gate.check(c, action=action, entity_type=entity_type, entity_id=entity["id"], amount=amount, args=args or {}, context=ctx)
    except gate.IdempotencyConflictError as e:
        await audit.record(c, action, args or {"id": entity["id"]}, {"error": gate.IDEMPOTENCY_CONFLICT, "verdict_id": e.verdict_id}, 409)
        raise
    except gate.GateBlockedError as e:
        await db.execute(f"UPDATE {table} SET status='blocked' WHERE id=$1", entity["id"])
        if table == "invoices":
            await db.execute("UPDATE invoices SET status_day=$2 WHERE id=$1", entity["id"], c.day)
        await audit.record(c, action, args or {"id": entity["id"]}, {"blocked": True, "reason": e.reason}, 403, e.verdict_id)
        raise


# ---------- invoices ----------


@router.post("/invoices/{invoice_id}/match")
async def match_invoice(invoice_id: str, body: MatchBody, c: Caller = Depends(GREEN)):
    inv = await _load("invoices", invoice_id, c, "invoices.match", body.model_dump())
    if inv["status"] != "pending":
        raise await _reject(c, "invoices.match", body.model_dump(), 409, f"invoice is {inv['status']}")
    po = await db.fetchrow("SELECT * FROM purchase_orders WHERE id=$1 AND episode_id=$2", body.po_id, c.episode_id)
    if not po:
        raise await _reject(c, "invoices.match", body.model_dump(), 404, "po not found")
    try:
        d = await _gated(
            c,
            "invoices.match",
            "invoice",
            inv,
            float(inv["amount"]),
            {**await _invoice_context(inv), "proposed_po": db.row_to_dict(po, hide=True)},
            "invoices",
            body.model_dump(),
        )
    except gate.GateBlockedError as e:
        return _blocked_response(e)
    except gate.IdempotencyConflictError as e:
        return _conflict_response(e)
    await db.execute("UPDATE invoices SET status='matched', po_id=$2, status_day=$3 WHERE id=$1", invoice_id, body.po_id, c.day)
    await audit.record(c, "invoices.match", body.model_dump(), {"id": invoice_id}, 200, d.verdict_id)
    await audit.mutation(c, "invoices.match", "invoice", invoice_id, float(inv["amount"]), d.verdict_id)
    return {"ok": True, "status": "matched"}


@router.post("/invoices/{invoice_id}/approve")
async def approve_invoice(invoice_id: str, c: Caller = Depends(GREEN)):
    inv = await _load("invoices", invoice_id, c, "invoices.approve", {"id": invoice_id})
    if inv["status"] not in ("pending", "matched"):
        raise await _reject(c, "invoices.approve", {"id": invoice_id}, 409, f"invoice is {inv['status']}")
    try:
        d = await _gated(c, "invoices.approve", "invoice", inv, float(inv["amount"]), await _invoice_context(inv), "invoices")
    except gate.GateBlockedError as e:
        return _blocked_response(e)
    except gate.IdempotencyConflictError as e:
        return _conflict_response(e)
    await db.execute("UPDATE invoices SET status='approved', status_day=$2 WHERE id=$1", invoice_id, c.day)
    await audit.record(c, "invoices.approve", {"id": invoice_id}, {"ok": True}, 200, d.verdict_id)
    await audit.mutation(c, "invoices.approve", "invoice", invoice_id, float(inv["amount"]), d.verdict_id)
    return {"ok": True, "status": "approved"}


@router.post("/invoices/{invoice_id}/reject")
async def reject_invoice(invoice_id: str, body: Reason, c: Caller = Depends(GREEN)):
    inv = await _load("invoices", invoice_id, c, "invoices.reject", body.model_dump())
    if inv["status"] in ("paid", "rejected"):
        raise await _reject(c, "invoices.reject", body.model_dump(), 409, f"invoice is {inv['status']}")
    try:
        d = await _gated(c, "invoices.reject", "invoice", inv, float(inv["amount"]), await _invoice_context(inv), "invoices", body.model_dump())
    except gate.GateBlockedError as e:
        return _blocked_response(e)
    except gate.IdempotencyConflictError as e:
        return _conflict_response(e)
    await db.execute("UPDATE invoices SET status='rejected', status_day=$2 WHERE id=$1", invoice_id, c.day)
    await audit.record(c, "invoices.reject", body.model_dump(), {"id": invoice_id}, 200, d.verdict_id)
    await audit.mutation(c, "invoices.reject", "invoice", invoice_id, float(inv["amount"]), d.verdict_id)
    return {"ok": True, "status": "rejected"}


@router.post("/invoices/{invoice_id}/pay")
async def pay_invoice(invoice_id: str, c: Caller = Depends(GREEN)):
    inv = await _load("invoices", invoice_id, c, "invoices.pay", {"id": invoice_id})
    if inv["status"] not in ("approved", "matched", "pending"):
        raise await _reject(c, "invoices.pay", {"id": invoice_id}, 409, f"invoice is {inv['status']}")
    vendor = await db.fetchrow("SELECT * FROM vendors WHERE id=$1", inv["vendor_id"])
    if vendor["status"] == "frozen":
        raise await _reject(c, "invoices.pay", {"id": invoice_id}, 409, "vendor is frozen")
    try:
        d = await _gated(c, "invoices.pay", "invoice", inv, float(inv["amount"]), await _invoice_context(inv), "invoices")
    except gate.GateBlockedError as e:
        return _blocked_response(e)
    except gate.IdempotencyConflictError as e:
        return _conflict_response(e)
    pid = db.new_id("pay")
    async with db.pool().acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO payments (id, episode_id, invoice_id, amount, to_account, paid_day, paid_by, origin_of_source) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
            pid,
            c.episode_id,
            invoice_id,
            inv["amount"],
            vendor["bank_account"],
            c.day,
            c.agent,
            inv["origin"],
        )
        await conn.execute("UPDATE invoices SET status='paid', status_day=$2 WHERE id=$1", invoice_id, c.day)
        await conn.execute(
            "INSERT INTO bank_transactions (id, episode_id, day, amount, counterparty, memo, matched_payment_id) VALUES ($1,$2,$3,$4,$5,$6,$7)",
            db.new_id("bnk"),
            c.episode_id,
            c.day,
            -float(inv["amount"]),
            vendor["name"],
            f"ACH {inv['invoice_number']}",
            pid,
        )
        if inv.get("po_id"):
            await conn.execute("UPDATE purchase_orders SET status='fulfilled' WHERE id=$1", inv["po_id"])
    await audit.record(c, "invoices.pay", {"id": invoice_id}, {"payment_id": pid, "amount": float(inv["amount"])}, 200, d.verdict_id)
    await audit.mutation(c, "invoices.pay", "invoice", invoice_id, float(inv["amount"]), d.verdict_id)
    return db.row_to_dict(await db.fetchrow("SELECT * FROM payments WHERE id=$1", pid), hide=True)


# ---------- vendor changes ----------


@router.post("/vendor_changes/{change_id}/approve")
async def approve_change(change_id: str, c: Caller = Depends(GREEN)):
    ch = await _load("vendor_changes", change_id, c, "vendor_changes.approve", {"id": change_id})
    if ch["status"] != "pending":
        raise await _reject(c, "vendor_changes.approve", {"id": change_id}, 409, f"change is {ch['status']}")
    try:
        d = await _gated(c, "vendor_changes.approve", "vendor_change", ch, None, await _change_context(ch), "vendor_changes")
    except gate.GateBlockedError as e:
        return _blocked_response(e)
    except gate.IdempotencyConflictError as e:
        return _conflict_response(e)
    async with db.pool().acquire() as conn, conn.transaction():
        await conn.execute(f"UPDATE vendors SET {ch['field']}=$2 WHERE id=$1", ch["vendor_id"], ch["new_value"])  # field is CHECK-constrained
        await conn.execute("UPDATE vendor_changes SET status='approved', resolved_day=$2 WHERE id=$1", change_id, c.day)
    await audit.record(c, "vendor_changes.approve", {"id": change_id}, {"ok": True}, 200, d.verdict_id)
    await audit.mutation(c, "vendor_changes.approve", "vendor_change", change_id, None, d.verdict_id)
    return {"ok": True, "status": "approved"}


@router.post("/vendor_changes/{change_id}/reject")
async def reject_change(change_id: str, body: Reason, c: Caller = Depends(GREEN)):
    ch = await _load("vendor_changes", change_id, c, "vendor_changes.reject", body.model_dump())
    if ch["status"] != "pending":
        raise await _reject(c, "vendor_changes.reject", body.model_dump(), 409, f"change is {ch['status']}")
    try:
        d = await _gated(c, "vendor_changes.reject", "vendor_change", ch, None, await _change_context(ch), "vendor_changes", body.model_dump())
    except gate.GateBlockedError as e:
        return _blocked_response(e)
    except gate.IdempotencyConflictError as e:
        return _conflict_response(e)
    await db.execute("UPDATE vendor_changes SET status='rejected', resolved_day=$2 WHERE id=$1", change_id, c.day)
    await audit.record(c, "vendor_changes.reject", body.model_dump(), {"id": change_id}, 200, d.verdict_id)
    await audit.mutation(c, "vendor_changes.reject", "vendor_change", change_id, None, d.verdict_id)
    return {"ok": True, "status": "rejected"}


# ---------- expenses ----------


@router.post("/expenses/{expense_id}/approve")
async def approve_expense(expense_id: str, c: Caller = Depends(GREEN)):
    ex = await _load("expenses", expense_id, c, "expenses.approve", {"id": expense_id})
    if ex["status"] != "pending":
        raise await _reject(c, "expenses.approve", {"id": expense_id}, 409, f"expense is {ex['status']}")
    try:
        d = await _gated(c, "expenses.approve", "expense", ex, float(ex["amount"]), await _expense_context(ex), "expenses")
    except gate.GateBlockedError as e:
        return _blocked_response(e)
    except gate.IdempotencyConflictError as e:
        return _conflict_response(e)
    await db.execute("UPDATE expenses SET status='approved' WHERE id=$1", expense_id)
    await audit.record(c, "expenses.approve", {"id": expense_id}, {"ok": True}, 200, d.verdict_id)
    await audit.mutation(c, "expenses.approve", "expense", expense_id, float(ex["amount"]), d.verdict_id)
    return {"ok": True, "status": "approved"}


@router.post("/expenses/{expense_id}/pay")
async def pay_expense(expense_id: str, c: Caller = Depends(GREEN)):
    ex = await _load("expenses", expense_id, c, "expenses.pay", {"id": expense_id})
    if ex["status"] not in ("approved", "pending"):
        raise await _reject(c, "expenses.pay", {"id": expense_id}, 409, f"expense is {ex['status']}")
    emp = await db.fetchrow("SELECT * FROM employees WHERE id=$1", ex["employee_id"])
    try:
        d = await _gated(c, "expenses.pay", "expense", ex, float(ex["amount"]), await _expense_context(ex), "expenses")
    except gate.GateBlockedError as e:
        return _blocked_response(e)
    except gate.IdempotencyConflictError as e:
        return _conflict_response(e)
    pid = db.new_id("pay")
    async with db.pool().acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO payments (id, episode_id, expense_id, amount, to_account, paid_day, paid_by, origin_of_source) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
            pid,
            c.episode_id,
            expense_id,
            ex["amount"],
            emp["bank_account"],
            c.day,
            c.agent,
            ex["origin"],
        )
        await conn.execute("UPDATE expenses SET status='paid' WHERE id=$1", expense_id)
        await conn.execute(
            "INSERT INTO bank_transactions (id, episode_id, day, amount, counterparty, memo, matched_payment_id) VALUES ($1,$2,$3,$4,$5,$6,$7)",
            db.new_id("bnk"),
            c.episode_id,
            c.day,
            -float(ex["amount"]),
            emp["name"],
            f"Reimbursement {ex['category']}",
            pid,
        )
    await audit.record(c, "expenses.pay", {"id": expense_id}, {"payment_id": pid}, 200, d.verdict_id)
    await audit.mutation(c, "expenses.pay", "expense", expense_id, float(ex["amount"]), d.verdict_id)
    return db.row_to_dict(await db.fetchrow("SELECT * FROM payments WHERE id=$1", pid), hide=True)


# ---------- GL ----------


@router.post("/gl/entries", status_code=201)
async def post_gl(body: GlEntryCreate, c: Caller = Depends(GREEN)):
    gid = db.new_id("gl")
    try:
        d = await gate.check(
            c,
            action="gl.post",
            entity_type="gl_entry",
            entity_id=gid,
            amount=max(body.debit, body.credit),
            args=body.model_dump(),
            context={"entry": body.model_dump()},
        )
    except gate.GateBlockedError as e:
        await audit.record(c, "gl.post", body.model_dump(), {"blocked": True, "reason": e.reason}, 403, e.verdict_id)
        return _blocked_response(e)
    except gate.IdempotencyConflictError as e:
        await audit.record(c, "gl.post", body.model_dump(), {"error": gate.IDEMPOTENCY_CONFLICT, "verdict_id": e.verdict_id}, 409)
        return _conflict_response(e)
    await db.execute(
        "INSERT INTO gl_entries (id, episode_id, day, account, debit, credit, memo, posted_by, ref_type, ref_id) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)",
        gid,
        c.episode_id,
        c.day,
        body.account,
        body.debit,
        body.credit,
        body.memo,
        c.agent,
        body.ref_type,
        body.ref_id,
    )
    await audit.record(c, "gl.post", body.model_dump(), {"id": gid}, 201, d.verdict_id)
    await audit.mutation(c, "gl.post", "gl_entry", gid, max(body.debit, body.credit), d.verdict_id)
    return db.row_to_dict(await db.fetchrow("SELECT * FROM gl_entries WHERE id=$1", gid))
