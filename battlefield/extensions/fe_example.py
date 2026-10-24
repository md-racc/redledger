"""Example frontend extension. Owner: Dev R (delete or replace).

Mounted at /api/x/fe/... . Shows the three things an extension can do: read core tables, own a
table of its own (contracts/ext/fe/00_example.sql), and drop a message into an agent's inbox.
A QR-code crowd page would be exactly this shape: a public POST that records a participant and
writes an `inputs` row for red or blue, plus a public GET leaderboard.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app import db
from app.auth import bearer
from app.events import bus

router = APIRouter()


@router.get("/ping")  # public on purpose: no bearer dependency. Only fe_* extensions may do this.
async def ping():
    return {"ok": True, "extension": "fe_example"}


@router.get("/episodes/{episode_id}/vendor_count", dependencies=[Depends(bearer)])
async def vendor_count(episode_id: str) -> dict[str, Any]:
    return {"vendors": await db.fetchval("SELECT COUNT(*) FROM vendors WHERE episode_id=$1", episode_id)}


class Nudge(BaseModel):
    episode_id: str
    target: str  # red | blue
    who: str
    message: str


@router.post("/nudge", status_code=201)  # public on purpose; a crowd page would call this
async def nudge(body: Nudge):
    if body.target not in ("red", "blue"):
        return {"ok": False, "reason": "target must be red or blue"}
    row = await db.fetchrow(
        "INSERT INTO fe_example_nudges (episode_id, target, who, message) VALUES ($1,$2,$3,$4) RETURNING id",
        body.episode_id,
        body.target,
        body.who[:40],
        body.message[:200],
    )
    await db.execute(
        "INSERT INTO inputs (episode_id, target, source, payload) VALUES ($1,$2,'crowd',$3)",
        body.episode_id,
        body.target,
        {"who": body.who[:40], "message": body.message[:200]},
    )
    day = await db.fetchval("SELECT current_day FROM episodes WHERE id=$1", body.episode_id) or 0
    await bus.emit(body.episode_id, day, "x.fe.nudge", {"id": row["id"], "target": body.target, "who": body.who[:40]}, agent="human")
    return {"ok": True, "id": row["id"]}
