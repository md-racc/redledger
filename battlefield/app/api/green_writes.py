"""Green's write surface: the AP workflow. Every route is gated. Owner: Dev Ad (routes) / Dev M (consumer).

Pattern per route:
  1. load entity, 409 if state doesn't allow the action (fast path; step 5 re-checks atomically)
  2. assemble blue's context (vendor, PO, recent changes, paid history)
  3. gate.check() → Decision or GateBlockedError
  4. on block: mark entity 'blocked', audit, 403 {verdict, reason, verdict_id}
  5. on allow: one transaction whose first statement is a compare-and-set of the entity's status
     (`UPDATE … WHERE status IN allowed RETURNING`); only its winner writes payments/bank lines/vendor
     fields, audits 200 and emits ledger.mutation. A concurrent loser (parallel tool calls, same key or
     not) gets an audited 409 "<entity> is <status>", never a second payment. Blocks are conditional
     the same way, so a block can't overwrite a concurrent transition.
Every response an agent gets is audited (AGENTS.md §3.5), including the 404/409 rejections in step 1
and a 409 when the X-Tool-Use-Id was already judged for a different action (the verdict is not replayed).
"""

from __future__ import annotations

import asyncio
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
_gl_locks: dict[tuple[str | None, str | None], list[Any]] = {}  # key -> [Lock, users]


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


class _VendorFrozen(Exception):
    """The vendor was frozen while the payment waited on the gate (e.g. during an escalation hold)."""


class _StateLost(Exception):
    """A compare-and-set transition found the entity no longer in an allowed state (a concurrent
    request moved it first)."""

    def __init__(self, status: str | None):
        super().__init__(status)
        self.status = status


async def _cas(conn: Any, c: Caller, table: str, id_: str, allowed: tuple[str, ...], set_sql: str, *params: Any) -> Any:
    """Compare-and-set a state transition inside the caller's transaction: `UPDATE … WHERE status IN
    allowed RETURNING *`. Only one of several concurrent requests can win it; the others get
    _StateLost(current status) and must not mutate anything else. `set_sql` uses $1..$n for params."""
    n = len(params)
    row = await conn.fetchrow(
        f"UPDATE {table} SET {set_sql} WHERE id=${n + 1} AND episode_id=${n + 2} AND status = ANY(${n + 3}::text[]) RETURNING *",
        *params,
        id_,
        c.episode_id,
        list(allowed),
    )
    if row is None:
        raise _StateLost(await conn.fetchval(f"SELECT status FROM {table} WHERE id=$1", id_))
    return row


async def _lost(c: Caller, action: str, args: dict[str, Any], noun: str, e: _StateLost) -> HTTPException:
    return await _reject(c, action, args, 409, f"{noun} is {e.status}")


# ---------- consuming a preparation (contracts/ledger-api.yaml /preparations) ----------
# A gated call whose X-Tool-Use-Id has a preparation consumes it instead of gating inline: no second
# blue call, no new escalation. Without one the route gates inline exactly as before.


class _Prepared:
    """The preparation a gated call consumes, and (shadow/off) why it is stale but still allowed."""

    def __init__(self, row: Any, mode: str):
        self.row, self.mode = row, mode
        self.stale: list[str] = []

    @property
    def id(self) -> str:
        return self.row["id"]

    @property
    def verdict_id(self) -> str | None:
        return self.row["verdict_id"]

    def result(self, result: dict[str, Any]) -> dict[str, Any]:
        out = {**result, "preparation_id": self.id}
        if self.stale:  # shadow/off: drift and expiry are audited, not refused
            out |= {"stale": True, "stale_detail": ", ".join(self.stale)}
        return out


class _PrepRefused(Exception):
    """Raised inside the execution transaction (which then rolls back): fingerprint drift in enforce, or
    the preparation was consumed by a concurrent call between the pre-checks and the transaction."""

    def __init__(self, error: str, detail: str = ""):
        super().__init__(error)
        self.error, self.detail = error, detail


def _prep_body(row: Any, error: str, detail: str = "") -> dict[str, Any]:
    body: dict[str, Any] = {"error": error, "preparation_id": row["id"]}
    if detail:
        body["detail"] = detail
    if error == "preparation_consumed":
        body["consumed_status"] = row["consumed_status"]
    return body


async def _refuse(c: Caller, action: str, args: dict[str, Any], status: int, body: dict[str, Any], verdict_id: str | None = None) -> JSONResponse:
    await audit.record(c, action, args, body, status, verdict_id)
    return JSONResponse(status_code=status, content=body)


async def _prepared(c: Caller, action: str, entity_id: str | None, amount: float | None, bargs: dict[str, Any], args: dict[str, Any]) -> Any:
    """None (no preparation: gate inline), a _Prepared to consume, or the audited refusal to return.
    Order (design §2.5): binding (every mode) → consumed / pending → mode or day changed (every mode)
    → enforce: expired, then a stored block (403, no blue call)."""
    assert c.episode_id is not None
    row = await gate._prep_row(c.episode_id, c.tool_use_id)
    if row is None:
        return None
    if not gate.same_binding(row, action, entity_id, amount, bargs):
        return await _refuse(c, action, args, 409, {"error": gate.IDEMPOTENCY_CONFLICT, "verdict_id": row["verdict_id"]})
    if row["consumed_at"] is not None:
        return await _refuse(c, action, args, 409, _prep_body(row, "preparation_consumed"), row["verdict_id"])
    if row["effective"] == "pending":  # its escalation is still held: never join or open one from here
        return await _refuse(c, action, args, 409, _prep_body(row, "preparation_pending"), row["verdict_id"])
    mode = await gate.controller_mode(c.episode_id)
    if row["controller_mode"] != mode or row["day"] != c.day:
        detail = "mode changed" if row["controller_mode"] != mode else "day changed"
        return await _refuse(c, action, args, 409, _prep_body(row, "preparation_stale", detail), row["verdict_id"])
    p = _Prepared(row, mode)
    if await db.fetchval("SELECT now() >= $1::timestamptz", row["expires_at"]):
        if mode == "enforce":
            return await _refuse(c, action, args, 409, _prep_body(row, "preparation_expired"), row["verdict_id"])
        p.stale.append("expired")
    if mode == "enforce" and row["effective"] == "block":
        # already marked blocked and persisted at preparation; the stored decision is the answer
        reason = row["reason"] if row["decided_by"] == "gate" else f"escalated; {'timeout' if row['decided_by'] == 'timeout' else 'block'}"
        body = {
            "verdict": "block",
            "reason": reason,
            "verdict_id": row["verdict_id"],
            "escalation_id": row["escalation_id"],
            "cause": row["cause"],
            "decided_by": row["decided_by"],
            "preparation_id": row["id"],
        }
        await audit.record(c, action, args, {"blocked": True, "reason": reason, "preparation_id": row["id"]}, 403, row["verdict_id"])
        return JSONResponse(status_code=403, content=body)
    return p


async def _consume(conn: Any, p: _Prepared | None, action: str, entity_id: str | None, bargs: dict[str, Any], status: int = 200) -> None:
    """First statements of the execution transaction, before the compare-and-set (which may itself
    rewrite a fingerprinted field such as invoices.po_id). Any refusal rolls the whole transaction back.

    1. The mode, read FOR SHARE so a toggle can't land until this commits; a change since the
       pre-checks is stale (a shadow-only verdict must never execute under enforce).
    2. Claim the preparation: concurrent same-key calls queue on its row lock here, and the losers then
       see it consumed (409 preparation_consumed), never the winner's own writes as drift. In enforce
       the claim also requires `clock_timestamp() < expires_at` (wall clock, so time spent waiting on locks counts).
    3. Recompute the fingerprint under row locks."""
    if p is None:
        return
    from .preparations import fingerprint  # preparations imports this module

    mode = await conn.fetchval("SELECT controller_mode FROM episodes WHERE id=$1 FOR SHARE", p.row["episode_id"])
    if mode != p.row["controller_mode"]:
        raise _PrepRefused("preparation_stale", "mode changed")
    claimed = await conn.fetchval(
        "UPDATE preparations SET consumed_at=now(), consumed_status=$2 WHERE id=$1 AND consumed_at IS NULL AND (NOT $3 OR clock_timestamp() < expires_at) RETURNING id",
        p.id,
        status,
        mode == "enforce",
    )
    if claimed is None:
        consumed = await conn.fetchval("SELECT consumed_at IS NOT NULL FROM preparations WHERE id=$1", p.id)
        raise _PrepRefused("preparation_consumed" if consumed else "preparation_expired")

    async def locked(sql: str, *a: Any) -> Any:
        return await conn.fetchrow(sql + " FOR UPDATE", *a)

    if await fingerprint(action, entity_id, bargs, fetchrow=locked) != p.row["state_hash"]:
        if mode == "enforce":
            raise _PrepRefused("preparation_stale", "state changed")
        p.stale.append("state changed")


async def _prep_failed(c: Caller, action: str, args: dict[str, Any], p: _Prepared, e: _PrepRefused) -> JSONResponse:
    assert c.episode_id is not None
    row = await gate._prep_row(c.episode_id, c.tool_use_id) if e.error == "preparation_consumed" else p.row
    return await _refuse(c, action, args, 409, _prep_body(row, e.error, e.detail), p.verdict_id)


def _res(result: dict[str, Any], p: _Prepared | None) -> dict[str, Any]:
    return p.result(result) if p is not None else result


def _pid(p: _Prepared | None) -> str | None:
    return p.id if p is not None else None


# Allowed source states per transition (the pre-gate check and the compare-and-set use the same set).
INV_MATCHABLE = ("pending",)
INV_APPROVABLE = ("pending", "matched")
INV_REJECTABLE = ("pending", "matched", "approved", "blocked")
INV_PAYABLE = ("approved", "matched", "pending")
CHANGE_OPEN = ("pending",)
EXP_APPROVABLE = ("pending",)
EXP_PAYABLE = ("approved", "pending")


async def _gated(
    c: Caller,
    action: str,
    entity_type: str,
    entity: dict[str, Any],
    amount: float | None,
    ctx: dict[str, Any],
    table: str,
    args: dict[str, Any] | None = None,
    *,
    allowed: tuple[str, ...],
):
    try:
        return await gate.check(c, action=action, entity_type=entity_type, entity_id=entity["id"], amount=amount, args=args or {}, context=ctx)
    except gate.IdempotencyConflictError as e:
        await audit.record(c, action, args or {"id": entity["id"]}, {"error": gate.IDEMPOTENCY_CONFLICT, "verdict_id": e.verdict_id}, 409)
        raise
    except gate.GateBlockedError as e:
        # conditional, so a block can never overwrite a transition a concurrent request already made
        day_sql = ", status_day=$3" if table == "invoices" else ""
        params = (entity["id"], list(allowed), c.day) if table == "invoices" else (entity["id"], list(allowed))
        await db.execute(f"UPDATE {table} SET status='blocked'{day_sql} WHERE id=$1 AND status = ANY($2::text[])", *params)
        await audit.record(c, action, args or {"id": entity["id"]}, {"blocked": True, "reason": e.reason}, 403, e.verdict_id)
        raise


# ---------- invoices ----------
# Every route: load (404) → a preparation for this key, if any (consume it; else gate inline) → the
# route's own state checks → one transaction: [consume] → compare-and-set → mutation rows.


@router.post("/invoices/{invoice_id}/match")
async def match_invoice(invoice_id: str, body: MatchBody, c: Caller = Depends(GREEN)):
    args = body.model_dump()
    inv = await _load("invoices", invoice_id, c, "invoices.match", args)
    p = await _prepared(c, "invoices.match", invoice_id, float(inv["amount"]), args, args)
    if isinstance(p, JSONResponse):
        return p
    if inv["status"] not in INV_MATCHABLE:
        raise await _reject(c, "invoices.match", args, 409, f"invoice is {inv['status']}")
    po = await db.fetchrow("SELECT * FROM purchase_orders WHERE id=$1 AND episode_id=$2", body.po_id, c.episode_id)
    if not po:
        raise await _reject(c, "invoices.match", args, 404, "po not found")
    vid = p.verdict_id if p is not None else None
    if p is None:
        try:
            d = await _gated(
                c,
                "invoices.match",
                "invoice",
                inv,
                float(inv["amount"]),
                {**await _invoice_context(inv), "proposed_po": db.row_to_dict(po, hide=True)},
                "invoices",
                args,
                allowed=INV_MATCHABLE,
            )
        except gate.GateBlockedError as e:
            return _blocked_response(e)
        except gate.IdempotencyConflictError as e:
            return _conflict_response(e)
        vid = d.verdict_id
    try:
        async with db.pool().acquire() as conn, conn.transaction():
            await _consume(conn, p, "invoices.match", invoice_id, args)
            await _cas(conn, c, "invoices", invoice_id, INV_MATCHABLE, "status='matched', po_id=$1, status_day=$2", body.po_id, c.day)
    except _StateLost as e:
        raise await _lost(c, "invoices.match", args, "invoice", e) from None
    except _PrepRefused as e:
        assert p is not None
        return await _prep_failed(c, "invoices.match", args, p, e)
    await audit.record(c, "invoices.match", args, _res({"id": invoice_id}, p), 200, vid)
    await audit.mutation(c, "invoices.match", "invoice", invoice_id, float(inv["amount"]), vid, preparation_id=_pid(p))
    return {"ok": True, "status": "matched"}


async def _simple_transition(
    c: Caller,
    action: str,
    table: str,
    entity_type: str,
    noun: str,
    id_: str,
    allowed: tuple[str, ...],
    set_sql: str,
    params: tuple[Any, ...],
    context: Any,
    *,
    with_amount: bool,
    body_args: dict[str, Any] | None = None,
    extra: Any = None,
) -> Any:
    """approve/reject on invoices, vendor changes and expenses: one CAS (plus `extra(conn, row)` in the
    same transaction), audited, one ledger.mutation."""
    args = body_args if body_args is not None else {"id": id_}
    bargs = body_args or {}
    ent = await _load(table, id_, c, action, args)
    amount = float(ent["amount"]) if with_amount else None
    p = await _prepared(c, action, id_, amount, bargs, args)
    if isinstance(p, JSONResponse):
        return p
    if ent["status"] not in allowed:
        raise await _reject(c, action, args, 409, f"{noun} is {ent['status']}")
    vid = p.verdict_id if p is not None else None
    if p is None:
        try:
            d = await _gated(c, action, entity_type, ent, amount, await context(ent), table, body_args, allowed=allowed)
        except gate.GateBlockedError as e:
            return _blocked_response(e)
        except gate.IdempotencyConflictError as e:
            return _conflict_response(e)
        vid = d.verdict_id
    try:
        async with db.pool().acquire() as conn, conn.transaction():
            await _consume(conn, p, action, id_, bargs)
            await _cas(conn, c, table, id_, allowed, set_sql, *params)
            if extra is not None:
                await extra(conn, ent)
    except _StateLost as e:
        raise await _lost(c, action, args, noun, e) from None
    except _PrepRefused as e:
        assert p is not None
        return await _prep_failed(c, action, args, p, e)
    await audit.record(c, action, args, _res({"id": id_} if body_args is not None else {"ok": True}, p), 200, vid)
    await audit.mutation(c, action, entity_type, id_, amount, vid, preparation_id=_pid(p))
    return None


@router.post("/invoices/{invoice_id}/approve")
async def approve_invoice(invoice_id: str, c: Caller = Depends(GREEN)):
    r = await _simple_transition(
        c,
        "invoices.approve",
        "invoices",
        "invoice",
        "invoice",
        invoice_id,
        INV_APPROVABLE,
        "status='approved', status_day=$1",
        (c.day,),
        _invoice_context,
        with_amount=True,
    )
    return r if r is not None else {"ok": True, "status": "approved"}


@router.post("/invoices/{invoice_id}/reject")
async def reject_invoice(invoice_id: str, body: Reason, c: Caller = Depends(GREEN)):
    r = await _simple_transition(
        c,
        "invoices.reject",
        "invoices",
        "invoice",
        "invoice",
        invoice_id,
        INV_REJECTABLE,
        "status='rejected', status_day=$1",
        (c.day,),
        _invoice_context,
        with_amount=True,
        body_args=body.model_dump(),
    )
    return r if r is not None else {"ok": True, "status": "rejected"}


@router.post("/invoices/{invoice_id}/pay")
async def pay_invoice(invoice_id: str, c: Caller = Depends(GREEN)):
    args = {"id": invoice_id}
    inv = await _load("invoices", invoice_id, c, "invoices.pay", args)
    p = await _prepared(c, "invoices.pay", invoice_id, float(inv["amount"]), {}, args)
    if isinstance(p, JSONResponse):
        return p
    if inv["status"] not in INV_PAYABLE:
        raise await _reject(c, "invoices.pay", args, 409, f"invoice is {inv['status']}")
    vendor = await db.fetchrow("SELECT * FROM vendors WHERE id=$1", inv["vendor_id"])
    if vendor["status"] == "frozen":
        raise await _reject(c, "invoices.pay", args, 409, "vendor is frozen")
    vid = p.verdict_id if p is not None else None
    if p is None:
        try:
            d = await _gated(c, "invoices.pay", "invoice", inv, float(inv["amount"]), await _invoice_context(inv), "invoices", allowed=INV_PAYABLE)
        except gate.GateBlockedError as e:
            return _blocked_response(e)
        except gate.IdempotencyConflictError as e:
            return _conflict_response(e)
        vid = d.verdict_id
    pid = db.new_id("pay")
    try:
        # The status compare-and-set comes first (after consuming a preparation, if any): only the
        # request that moves the invoice to 'paid' writes the payment, the bank line and the PO update
        # (one transaction, no pooled connection held across the gate above).
        async with db.pool().acquire() as conn, conn.transaction():
            await _consume(conn, p, "invoices.pay", invoice_id, {})
            await _cas(conn, c, "invoices", invoice_id, INV_PAYABLE, "status='paid', status_day=$1", c.day)
            # The vendor read above is from before the gate, which may have held this call for a human
            # for up to ESCALATION_TIMEOUT_SEC. Re-read it locked: a freeze during the hold aborts the
            # payment (the CAS rolls back with it), and the money goes to the account on file now.
            vendor = await conn.fetchrow("SELECT * FROM vendors WHERE id=$1 FOR UPDATE", inv["vendor_id"])
            if vendor["status"] == "frozen":
                raise _VendorFrozen()
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
    except _StateLost as e:
        raise await _lost(c, "invoices.pay", args, "invoice", e) from None
    except _VendorFrozen:
        raise await _reject(c, "invoices.pay", args, 409, "vendor is frozen") from None
    except _PrepRefused as e:
        assert p is not None
        return await _prep_failed(c, "invoices.pay", args, p, e)
    await audit.record(c, "invoices.pay", args, _res({"payment_id": pid, "amount": float(inv["amount"])}, p), 200, vid)
    await audit.mutation(c, "invoices.pay", "invoice", invoice_id, float(inv["amount"]), vid, preparation_id=_pid(p))
    return db.row_to_dict(await db.fetchrow("SELECT * FROM payments WHERE id=$1", pid), hide=True)


# ---------- vendor changes ----------


async def _apply_change(conn: Any, ch: dict[str, Any]) -> None:
    await conn.execute(f"UPDATE vendors SET {ch['field']}=$2 WHERE id=$1", ch["vendor_id"], ch["new_value"])  # field is CHECK-constrained


@router.post("/vendor_changes/{change_id}/approve")
async def approve_change(change_id: str, c: Caller = Depends(GREEN)):
    r = await _simple_transition(
        c,
        "vendor_changes.approve",
        "vendor_changes",
        "vendor_change",
        "change",
        change_id,
        CHANGE_OPEN,
        "status='approved', resolved_day=$1",
        (c.day,),
        _change_context,
        with_amount=False,
        extra=_apply_change,
    )
    return r if r is not None else {"ok": True, "status": "approved"}


@router.post("/vendor_changes/{change_id}/reject")
async def reject_change(change_id: str, body: Reason, c: Caller = Depends(GREEN)):
    r = await _simple_transition(
        c,
        "vendor_changes.reject",
        "vendor_changes",
        "vendor_change",
        "change",
        change_id,
        CHANGE_OPEN,
        "status='rejected', resolved_day=$1",
        (c.day,),
        _change_context,
        with_amount=False,
        body_args=body.model_dump(),
    )
    return r if r is not None else {"ok": True, "status": "rejected"}


# ---------- expenses ----------


@router.post("/expenses/{expense_id}/approve")
async def approve_expense(expense_id: str, c: Caller = Depends(GREEN)):
    r = await _simple_transition(
        c, "expenses.approve", "expenses", "expense", "expense", expense_id, EXP_APPROVABLE, "status='approved'", (), _expense_context, with_amount=True
    )
    return r if r is not None else {"ok": True, "status": "approved"}


@router.post("/expenses/{expense_id}/pay")
async def pay_expense(expense_id: str, c: Caller = Depends(GREEN)):
    args = {"id": expense_id}
    ex = await _load("expenses", expense_id, c, "expenses.pay", args)
    p = await _prepared(c, "expenses.pay", expense_id, float(ex["amount"]), {}, args)
    if isinstance(p, JSONResponse):
        return p
    if ex["status"] not in EXP_PAYABLE:
        raise await _reject(c, "expenses.pay", args, 409, f"expense is {ex['status']}")
    vid = p.verdict_id if p is not None else None
    if p is None:
        try:
            d = await _gated(c, "expenses.pay", "expense", ex, float(ex["amount"]), await _expense_context(ex), "expenses", allowed=EXP_PAYABLE)
        except gate.GateBlockedError as e:
            return _blocked_response(e)
        except gate.IdempotencyConflictError as e:
            return _conflict_response(e)
        vid = d.verdict_id
    pid = db.new_id("pay")
    try:
        async with db.pool().acquire() as conn, conn.transaction():
            await _consume(conn, p, "expenses.pay", expense_id, {})
            await _cas(conn, c, "expenses", expense_id, EXP_PAYABLE, "status='paid'")
            emp = await conn.fetchrow("SELECT * FROM employees WHERE id=$1 FOR UPDATE", ex["employee_id"])  # current bank details, not pre-gate
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
    except _StateLost as e:
        raise await _lost(c, "expenses.pay", args, "expense", e) from None
    except _PrepRefused as e:
        assert p is not None
        return await _prep_failed(c, "expenses.pay", args, p, e)
    await audit.record(c, "expenses.pay", args, _res({"payment_id": pid}, p), 200, vid)
    await audit.mutation(c, "expenses.pay", "expense", expense_id, float(ex["amount"]), vid, preparation_id=_pid(p))
    return db.row_to_dict(await db.fetchrow("SELECT * FROM payments WHERE id=$1", pid), hide=True)


# ---------- GL ----------


@router.post("/gl/entries", status_code=201)
async def post_gl(body: GlEntryCreate, c: Caller = Depends(GREEN)):
    """Idempotent on X-Tool-Use-Id in every controller mode: a retry with the same key and body returns
    the entry already posted (no second row, no second ledger.mutation); a different body under that
    key is a 409 conflict. gl_entries has no key column, so the link is the 201 audit_log row of the
    first posting. Attempts sharing a key are serialized by an in-process lock so two concurrent
    retries can't both post (battlefield is one process; the gate's escalation waiters assume the same).
    No DB connection is held while waiting, so a slow escalation can't starve the pool."""
    lock_key = (c.episode_id, c.tool_use_id)
    slot = _gl_locks.setdefault(lock_key, [asyncio.Lock(), 0])
    slot[1] += 1  # holders + waiters; the lock is dropped only when nobody can still need it
    try:
        async with slot[0]:
            return await _post_gl(body, c)
    finally:
        slot[1] -= 1
        if slot[1] == 0:
            del _gl_locks[lock_key]


async def _post_gl(body: GlEntryCreate, c: Caller) -> Any:
    args = body.model_dump()
    prior = await db.fetchrow(
        "SELECT args, result, verdict_id FROM audit_log WHERE episode_id=$1 AND agent=$2 AND action='gl.post' AND tool_use_id=$3 AND http_status=201 "
        "ORDER BY id LIMIT 1",
        c.episode_id,
        c.agent,
        c.tool_use_id,
    )
    if prior is not None:
        if dict(prior["args"] or {}) != args:
            await audit.record(c, "gl.post", args, {"error": gate.IDEMPOTENCY_CONFLICT, "verdict_id": prior["verdict_id"]}, 409)
            return JSONResponse(status_code=409, content={"error": gate.IDEMPOTENCY_CONFLICT, "verdict_id": prior["verdict_id"]})
        posted = prior["result"]["id"]
        await audit.record(c, "gl.post", args, {"id": posted, "replayed": True}, 201, prior["verdict_id"])
        return db.row_to_dict(await db.fetchrow("SELECT * FROM gl_entries WHERE id=$1", posted))
    gid = db.new_id("gl")
    # After the audit-log replay above (a posted key replays, it is never "consumed" twice): a prepared
    # GL entry is bound by its posted fields; it has no entity until it is posted.
    p = await _prepared(c, "gl.post", None, None, args, args)
    if isinstance(p, JSONResponse):
        return p
    vid = p.verdict_id if p is not None else None
    if p is None:
        try:
            d = await gate.check(
                c,
                action="gl.post",
                entity_type="gl_entry",
                entity_id=gid,
                amount=max(body.debit, body.credit),
                args=args,
                context={"entry": args},
            )
        except gate.GateBlockedError as e:
            await audit.record(c, "gl.post", body.model_dump(), {"blocked": True, "reason": e.reason}, 403, e.verdict_id)
            return _blocked_response(e)
        except gate.IdempotencyConflictError as e:
            await audit.record(c, "gl.post", body.model_dump(), {"error": gate.IDEMPOTENCY_CONFLICT, "verdict_id": e.verdict_id}, 409)
            return _conflict_response(e)
        vid = d.verdict_id
    # The 201 audit row is what a retry finds, so it commits atomically with the entry: a crash between
    # them can't leave a posted entry with no record (which would let a retry post a second one).
    try:
        async with db.pool().acquire() as conn, conn.transaction():
            await _consume(conn, p, "gl.post", None, args, 201)
            await _insert_gl(conn, c, body, gid, vid, p)
    except _PrepRefused as e:
        assert p is not None
        return await _prep_failed(c, "gl.post", args, p, e)
    await audit.mutation(c, "gl.post", "gl_entry", gid, max(body.debit, body.credit), vid, preparation_id=_pid(p))
    return db.row_to_dict(await db.fetchrow("SELECT * FROM gl_entries WHERE id=$1", gid))


async def _insert_gl(conn: Any, c: Caller, body: GlEntryCreate, gid: str, vid: str | None, p: _Prepared | None) -> None:
    await conn.execute(
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
    await audit.record(c, "gl.post", body.model_dump(), _res({"id": gid}, p), 201, vid, conn=conn)
