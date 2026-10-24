"""Green's preparations: the gate half of a gated action, ahead of its execution. Owner: Dev Ad.

POST /api/preparations (contracts/ledger-api.yaml) runs what a gated route does before it mutates:
load the entity and apply the route's own state checks, assemble blue's context, then
`gatekeeper.prepare()` (one blue call per key, verdict persisted, an enforced block marks the entity
blocked, an escalation is held until decided). It never performs the action. The response is the
stored preparation; the gated route later called with the same X-Tool-Use-Id consumes it (step 2b).
Every outcome is audited as `prepare:<action>`.

The state fingerprint here is the contract's narrow per-action field table; the execution path
recomputes it with `fingerprint(..., fetchrow=conn.fetchrow)` inside its own transaction.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from agentkit.models import PreparationCreate

from .. import db
from ..auth import Caller, allow
from ..gate import gatekeeper as gate
from . import audit
from . import green_writes as gw

router = APIRouter()
GREEN = allow("green", operator=False)

# action -> (table, entity_type, states the route accepts); gl.post has no entity
ACTIONS: dict[str, tuple[str | None, str, tuple[str, ...]]] = {
    "invoices.match": ("invoices", "invoice", gw.INV_MATCHABLE),
    "invoices.approve": ("invoices", "invoice", gw.INV_APPROVABLE),
    "invoices.reject": ("invoices", "invoice", gw.INV_REJECTABLE),
    "invoices.pay": ("invoices", "invoice", gw.INV_PAYABLE),
    "vendor_changes.approve": ("vendor_changes", "vendor_change", gw.CHANGE_OPEN),
    "vendor_changes.reject": ("vendor_changes", "vendor_change", gw.CHANGE_OPEN),
    "expenses.approve": ("expenses", "expense", gw.EXP_APPROVABLE),
    "expenses.pay": ("expenses", "expense", gw.EXP_PAYABLE),
    "gl.post": (None, "gl_entry", ()),
}

Fetchrow = Callable[..., Awaitable[Any]]


def _pick(row: Any, *cols: str) -> dict[str, Any] | None:
    return None if row is None else {k: db._jsonable(dict(row).get(k)) for k in cols}


async def fingerprint(action: str, entity_id: str | None, args: dict[str, Any], *, fetchrow: Fetchrow = db.fetchrow) -> str:
    """sha256 over the current, provenance-stripped values the action reads (contracts/ledger-api.yaml
    /preparations). The subject's own status and history lists are deliberately not part of it."""
    state: dict[str, Any] = {}
    if action.startswith("invoices."):
        inv = await fetchrow("SELECT * FROM invoices WHERE id=$1", entity_id)
        state["invoice"] = _pick(inv, "amount", "vendor_id", "po_id")
        vendor = await fetchrow("SELECT * FROM vendors WHERE id=$1", inv["vendor_id"]) if inv else None
        if action == "invoices.match":
            state["vendor"] = _pick(vendor, "status")
            state["po"] = _pick(await fetchrow("SELECT * FROM purchase_orders WHERE id=$1", args.get("po_id")), "vendor_id", "amount", "status")
        else:
            state["vendor"] = _pick(vendor, "status", "bank_account", "bank_routing", "name")
            po_id = inv["po_id"] if inv else None
            state["po"] = _pick(await fetchrow("SELECT * FROM purchase_orders WHERE id=$1", po_id), "vendor_id", "amount", "status") if po_id else None
    elif action.startswith("vendor_changes."):
        ch = await fetchrow("SELECT * FROM vendor_changes WHERE id=$1", entity_id)
        state["change"] = _pick(ch, "vendor_id", "field", "new_value")
        vendor = await fetchrow("SELECT * FROM vendors WHERE id=$1", ch["vendor_id"]) if ch else None
        state["vendor"] = None if vendor is None else {"status": vendor["status"], ch["field"]: dict(vendor).get(ch["field"])}
    elif action.startswith("expenses."):
        ex = await fetchrow("SELECT * FROM expenses WHERE id=$1", entity_id)
        state["expense"] = _pick(ex, "amount", "employee_id")
        state["employee"] = _pick(
            await fetchrow("SELECT * FROM employees WHERE id=$1", ex["employee_id"]) if ex else None, "status", "bank_account", "hr_record"
        )
    # gl.post: none (the args are the whole action)
    blob = json.dumps(state, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def block_marker(action: str, entity_id: str | None, day: int) -> Callable[[], Awaitable[None]]:
    """D6: an enforced block marks the entity blocked at preparation, with the same conditional update
    the gated route uses, so a block can never overwrite a transition a concurrent request made."""
    table, _, allowed = ACTIONS[action]

    async def mark() -> None:
        if table is None or entity_id is None:
            return
        if table == "invoices":
            await db.execute("UPDATE invoices SET status='blocked', status_day=$3 WHERE id=$1 AND status = ANY($2::text[])", entity_id, list(allowed), day)
        else:
            await db.execute(f"UPDATE {table} SET status='blocked' WHERE id=$1 AND status = ANY($2::text[])", entity_id, list(allowed))

    return mark


def out(row: Any) -> dict[str, Any]:
    """A stored preparation as the contract's Preparation."""
    mode = row["controller_mode"]
    return {
        "preparation_id": row["id"],
        "idempotency_key": row["idempotency_key"],
        "controller_mode": mode,
        "day": row["day"],
        "action": row["action"],
        "entity_type": row["entity_type"],
        "entity_id": row["entity_id"],
        "amount": None if row["amount"] is None else float(row["amount"]),
        "effective": row["effective"],
        "enforced": mode == "enforce",
        "decided_by": row["decided_by"],
        "verdict_id": row["verdict_id"],
        "verdict": row["verdict"],
        "cause": row["cause"] or (gate.verdict_cause(row["rules_fired"]) if row["verdict_id"] else None),
        "reason": row["reason"] or ("controller off" if mode == "off" else ""),
        "rules_fired": list(row["rules_fired"] or []),
        "escalation_id": row["escalation_id"],
        "expires_at": row["expires_at"].isoformat(),
        "consumed": row["consumed_at"] is not None,
        "consumed_status": row["consumed_status"],
    }


async def _fail(c: Caller, action: str, args: dict[str, Any], status: int, body: dict[str, Any]) -> JSONResponse:
    await audit.record(c, f"prepare:{action}", args, body, status)
    return JSONResponse(status_code=status, content=body)


def _invalid_state(detail: str) -> dict[str, Any]:
    return {"error": "invalid_state", "detail": detail}


@router.post("/preparations")
async def create_preparation(request: Request, c: Caller = Depends(GREEN)):
    # The body is parsed here, not by FastAPI, so a malformed or non-object body is an audited 422 too.
    try:
        body = await request.json()
    except ValueError:
        return await _fail(c, "unknown", {}, 422, {"error": "invalid body", "detail": "body is not JSON"})
    if not isinstance(body, dict):
        return await _fail(c, "unknown", {"body": body}, 422, {"error": "invalid body", "detail": "body must be a JSON object"})
    try:
        req = PreparationCreate.model_validate(body)
    except ValidationError as e:
        action = body.get("action") if isinstance(body.get("action"), str) else "unknown"
        return await _fail(c, action, body, 422, {"error": "invalid body", "detail": str(e.errors(include_url=False, include_context=False))[:500]})
    action, eid, args = req.action, req.entity_id, dict(req.args)
    audit_args = {"entity_id": eid, "args": args}
    table, entity_type, allowed = ACTIONS[action]

    amount: float | None = None
    verdict_amount: float | None = None
    try:
        if action == "gl.post":
            gl = gw.GlEntryCreate.model_validate(args)
            args = gl.model_dump()
            verdict_amount = max(gl.debit, gl.credit)
            context: dict[str, Any] = {"entry": args}
        else:
            if not eid:
                return await _fail(c, action, audit_args, 422, {"error": "invalid body", "detail": "entity_id is required"})
            if action == "invoices.match":
                args = gw.MatchBody.model_validate(args).model_dump()
            elif action.endswith(".reject"):
                args = gw.Reason.model_validate(args).model_dump()
            row = await db.fetchrow(f"SELECT * FROM {table} WHERE id=$1 AND episode_id=$2", eid, c.episode_id)
            if row is None:
                return await _fail(c, action, audit_args, 404, {"detail": f"{table[:-1]} not found"})
            ent = dict(row)
            if ent["status"] not in allowed:
                return await _fail(c, action, audit_args, 409, _invalid_state(f"{entity_type.replace('_', ' ')} is {ent['status']}"))
            if table == "invoices":
                amount = verdict_amount = float(ent["amount"])
                context = await gw._invoice_context(ent)
                if action == "invoices.match":
                    po = await db.fetchrow("SELECT * FROM purchase_orders WHERE id=$1 AND episode_id=$2", args["po_id"], c.episode_id)
                    if po is None:
                        return await _fail(c, action, audit_args, 404, {"detail": "po not found"})
                    context["proposed_po"] = db.row_to_dict(po, hide=True)
                elif action == "invoices.pay" and (context.get("vendor") or {}).get("status") == "frozen":
                    return await _fail(c, action, audit_args, 409, _invalid_state("vendor is frozen"))
            elif table == "expenses":
                amount = verdict_amount = float(ent["amount"])
                context = await gw._expense_context(ent)
            else:
                context = await gw._change_context(ent)
    except ValidationError as e:
        return await _fail(c, action, audit_args, 422, {"error": "invalid body", "detail": str(e.errors(include_url=False, include_context=False))[:500]})

    try:
        prep = await gate.prepare(
            c,
            action=action,
            entity_type=entity_type,
            entity_id=eid if table else None,
            amount=amount,
            verdict_amount=verdict_amount,
            args=args,
            context=context,
            state_hash=await fingerprint(action, eid, args),
            mark_blocked=block_marker(action, eid, c.day or 0),
        )
    except gate.IdempotencyConflictError as e:
        return await _fail(c, action, audit_args, 409, {"error": gate.IDEMPOTENCY_CONFLICT, "verdict_id": e.verdict_id})
    result = out(prep)
    await audit.record(
        c, f"prepare:{action}", audit_args, {"preparation_id": result["preparation_id"], "effective": result["effective"]}, 200, result["verdict_id"]
    )
    return result


@router.get("/preparations/{key}")
async def get_preparation(key: str, c: Caller = Depends(GREEN)):
    assert c.episode_id is not None
    row = await gate._prep_row(c.episode_id, key)
    if row is None:
        raise HTTPException(404, "no preparation for this key in this episode")
    return out(row)


async def sweep_pending() -> int:
    """Startup recovery (main.recover_after_restart): every `pending` preparation becomes a block
    decided by timeout, and its entity is marked blocked like any enforced block."""
    rows = await gate.expire_pending_preparations()
    for r in rows:
        await block_marker(r["action"], r["entity_id"], r["day"])()
    return len(rows)
