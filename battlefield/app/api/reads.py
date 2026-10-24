"""Read routes — all agents + operator. Provenance columns hidden from agents. Owner: Dev Ad."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import db
from ..auth import Caller, agent_episode, allow, caller

router = APIRouter()


def _ep(c: Caller, episode_id: str | None) -> str:
    return agent_episode(c, episode_id)


@router.get("/vendors")
async def list_vendors(status: str | None = None, episode_id: str | None = None, c: Caller = Depends(caller)):
    ep = _ep(c, episode_id)
    rows = await db.fetch("SELECT * FROM vendors WHERE episode_id=$1 AND ($2::text IS NULL OR status=$2) ORDER BY created_day, name", ep, status)
    return db.rows_to_list(rows, hide=c.hide)


@router.get("/vendors/{vendor_id}")
async def get_vendor(vendor_id: str, episode_id: str | None = None, c: Caller = Depends(caller)):
    row = await db.fetchrow("SELECT * FROM vendors WHERE id=$1", vendor_id)
    if not row:
        raise HTTPException(404)
    return db.row_to_dict(row, hide=c.hide)


@router.get("/vendor_changes")
async def list_vendor_changes(status: str | None = None, episode_id: str | None = None, c: Caller = Depends(caller)):
    ep = _ep(c, episode_id)
    rows = await db.fetch("SELECT * FROM vendor_changes WHERE episode_id=$1 AND ($2::text IS NULL OR status=$2) ORDER BY requested_day", ep, status)
    return db.rows_to_list(rows, hide=c.hide)


@router.get("/employees")
async def list_employees(episode_id: str | None = None, c: Caller = Depends(caller)):
    ep = _ep(c, episode_id)
    rows = await db.fetch("SELECT * FROM employees WHERE episode_id=$1 ORDER BY start_day, name", ep)
    return db.rows_to_list(rows, hide=c.hide)


@router.get("/purchase_orders")
async def list_pos(status: str | None = None, vendor_id: str | None = None, episode_id: str | None = None, c: Caller = Depends(caller)):
    ep = _ep(c, episode_id)
    rows = await db.fetch(
        "SELECT * FROM purchase_orders WHERE episode_id=$1 AND ($2::text IS NULL OR status=$2) AND ($3::text IS NULL OR vendor_id=$3) ORDER BY created_day",
        ep,
        status,
        vendor_id,
    )
    return db.rows_to_list(rows, hide=c.hide)


@router.get("/invoices")
async def list_invoices(
    status: str | None = None, vendor_id: str | None = None, day: int | None = None, episode_id: str | None = None, c: Caller = Depends(caller)
):
    ep = _ep(c, episode_id)
    rows = await db.fetch(
        "SELECT * FROM invoices WHERE episode_id=$1 AND ($2::text IS NULL OR status=$2) AND ($3::text IS NULL OR vendor_id=$3) AND ($4::int IS NULL OR received_day=$4) ORDER BY received_day, id",
        ep,
        status,
        vendor_id,
        day,
    )
    return db.rows_to_list(rows, hide=c.hide)


@router.get("/invoices/{invoice_id}")
async def get_invoice(invoice_id: str, c: Caller = Depends(caller)):
    row = await db.fetchrow("SELECT * FROM invoices WHERE id=$1", invoice_id)
    if not row:
        raise HTTPException(404)
    return db.row_to_dict(row, hide=c.hide)


@router.get("/payments")
async def list_payments(day: int | None = None, episode_id: str | None = None, c: Caller = Depends(caller)):
    ep = _ep(c, episode_id)
    rows = await db.fetch("SELECT * FROM payments WHERE episode_id=$1 AND ($2::int IS NULL OR paid_day=$2) ORDER BY paid_day, id", ep, day)
    return db.rows_to_list(rows, hide=c.hide)


@router.get("/expenses")
async def list_expenses(status: str | None = None, episode_id: str | None = None, c: Caller = Depends(caller)):
    ep = _ep(c, episode_id)
    rows = await db.fetch("SELECT * FROM expenses WHERE episode_id=$1 AND ($2::text IS NULL OR status=$2) ORDER BY submitted_day", ep, status)
    return db.rows_to_list(rows, hide=c.hide)


@router.get("/bank/transactions")
async def list_bank(from_day: int | None = None, to_day: int | None = None, episode_id: str | None = None, c: Caller = Depends(caller)):
    ep = _ep(c, episode_id)
    rows = await db.fetch(
        "SELECT * FROM bank_transactions WHERE episode_id=$1 AND ($2::int IS NULL OR day>=$2) AND ($3::int IS NULL OR day<=$3) ORDER BY day, id",
        ep,
        from_day,
        to_day,
    )
    return db.rows_to_list(rows, hide=c.hide)


@router.get("/gl/entries")
async def list_gl(
    from_day: int | None = None, to_day: int | None = None, account: str | None = None, episode_id: str | None = None, c: Caller = Depends(caller)
):
    ep = _ep(c, episode_id)
    rows = await db.fetch(
        "SELECT * FROM gl_entries WHERE episode_id=$1 AND ($2::int IS NULL OR day>=$2) AND ($3::int IS NULL OR day<=$3) AND ($4::text IS NULL OR account=$4) ORDER BY day, id",
        ep,
        from_day,
        to_day,
        account,
    )
    return db.rows_to_list(rows, hide=c.hide)


@router.get("/flags")
async def list_flags(episode_id: str | None = None, c: Caller = Depends(allow("green", "blue"))):
    ep = _ep(c, episode_id)
    rows = await db.fetch("SELECT * FROM flags WHERE episode_id=$1 ORDER BY day, id", ep)
    return db.rows_to_list(rows)


@router.get("/audit_log")
async def list_audit(
    agent: str | None = None, day: int | None = None, episode_id: str | None = None, limit: int = Query(500, le=5000), c: Caller = Depends(allow("blue"))
):
    ep = _ep(c, episode_id)
    # Only red's legwork writes audit rows for entities that look like sim traffic, so to an agent a
    # red row is provenance (AGENTS.md §3.4). Agents see green/blue rows only (an allowlist, plus no
    # attacks.* actions as a backstop). Playbook rows are operator-only too, in both spellings: the
    # route's own `playbook.*` rows and the guard's refused-write rows (`PUT /playbook`, auth.py; `/api` prefix tolerated),
    # since either would show another agent's playbook writes. `agent=red` is just an empty result, not a 403, so the filter itself
    # isn't advertised. The operator sees everything. LIMIT applies after the filter.
    rows = await db.fetch(
        "SELECT * FROM audit_log WHERE episode_id=$1 AND ($2::text IS NULL OR agent=$2) AND ($3::int IS NULL OR day=$3)"
        " AND (NOT $5::bool OR (agent IN ('green', 'blue') AND action NOT LIKE 'attacks.%' AND action NOT LIKE 'playbook.%' AND action !~ '^[A-Z]+ (/api)?/playbook(/|$)')) ORDER BY id DESC LIMIT $4",
        ep,
        agent,
        day,
        limit,
        c.is_agent,
    )
    return db.rows_to_list(rows)


@router.get("/reports/{report_id}")
async def get_report(report_id: str, c: Caller = Depends(caller)):
    row = await db.fetchrow("SELECT * FROM reports WHERE id=$1", report_id)
    if not row:
        raise HTTPException(404)
    return db.row_to_dict(row)


@router.get("/attacks")
async def list_attacks(episode_id: str | None = None, c: Caller = Depends(allow("red"))):
    ep = _ep(c, episode_id)
    rows = await db.fetch("SELECT * FROM attacks WHERE episode_id=$1 ORDER BY day_launched, created_at, id", ep)
    return db.rows_to_list(rows)
