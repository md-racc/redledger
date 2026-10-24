"""Blue's write surface: flags, freezes, reports. Owner: Dev Ad (routes) / Dev M (consumer)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import db
from ..auth import Caller, allow
from ..events import bus
from . import audit

router = APIRouter()
BLUE = allow("blue", operator=False)


class FlagCreate(BaseModel):
    entity_type: str
    entity_id: str
    severity: str
    reason: str


class Reason(BaseModel):
    reason: str


class ReportCreate(BaseModel):
    day: int
    markdown: str


@router.post("/flags", status_code=201)
async def raise_flag(body: FlagCreate, c: Caller = Depends(BLUE)):
    if body.severity not in ("low", "medium", "high"):
        raise HTTPException(422, "severity must be low|medium|high")
    fid = db.new_id("flg")
    await db.execute(
        "INSERT INTO flags (id, episode_id, day, entity_type, entity_id, severity, reason, raised_by) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
        fid,
        c.episode_id,
        c.day,
        body.entity_type,
        body.entity_id,
        body.severity,
        body.reason,
        c.agent,
    )
    await bus.emit(c.episode_id, c.day, "flag.raised", {"flag_id": fid, **body.model_dump()}, agent="blue")  # type: ignore[arg-type]
    await audit.record(c, "flags.raise", body.model_dump(), {"id": fid}, 201)
    return db.row_to_dict(await db.fetchrow("SELECT * FROM flags WHERE id=$1", fid))


@router.post("/vendors/{vendor_id}/freeze")
async def freeze_vendor(vendor_id: str, body: Reason, c: Caller = Depends(BLUE)):
    v = await db.fetchrow("SELECT * FROM vendors WHERE id=$1 AND episode_id=$2", vendor_id, c.episode_id)
    if not v:
        raise HTTPException(404)
    await db.execute("UPDATE vendors SET status='frozen' WHERE id=$1", vendor_id)
    await bus.emit(c.episode_id, c.day, "vendor.frozen", {"vendor_id": vendor_id, "reason": body.reason}, agent="blue")  # type: ignore[arg-type]
    await audit.record(c, "vendors.freeze", {"id": vendor_id, **body.model_dump()}, {"ok": True}, 200)
    await audit.mutation(c, "vendors.freeze", "vendor", vendor_id)
    return {"ok": True, "status": "frozen"}


@router.post("/vendors/{vendor_id}/unfreeze")
async def unfreeze_vendor(vendor_id: str, c: Caller = Depends(BLUE)):
    await db.execute("UPDATE vendors SET status='active' WHERE id=$1 AND episode_id=$2", vendor_id, c.episode_id)
    await bus.emit(c.episode_id, c.day, "vendor.unfrozen", {"vendor_id": vendor_id}, agent="blue")  # type: ignore[arg-type]
    await audit.record(c, "vendors.unfreeze", {"id": vendor_id}, {"ok": True}, 200)
    return {"ok": True, "status": "active"}


@router.post("/reports", status_code=201)
async def post_report(body: ReportCreate, c: Caller = Depends(BLUE)):
    rid = db.new_id("rpt")
    await db.execute(
        "INSERT INTO reports (id, episode_id, day, markdown, posted_by) VALUES ($1,$2,$3,$4,$5)", rid, c.episode_id, body.day, body.markdown, c.agent
    )
    await bus.emit(c.episode_id, c.day, "report.posted", {"report_id": rid, "day": body.day}, agent="blue")  # type: ignore[arg-type]
    await audit.record(c, "reports.post", {"day": body.day, "chars": len(body.markdown)}, {"id": rid}, 201)
    return {"id": rid}
