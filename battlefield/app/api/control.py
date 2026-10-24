"""Control plane: episodes, controller toggle, attacks, escalations, replays, health. Owner: Dev Ad."""

from __future__ import annotations

import asyncio
import json
import random
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from seed import company

from .. import db
from ..auth import bearer
from ..config import settings
from ..events import bus
from ..gate import gatekeeper
from ..orchestrator import agents, runner
from ..scoring import score

router = APIRouter(dependencies=[Depends(bearer)])


class EpisodeCreate(BaseModel):
    seed: int | None = None
    controller_mode: str = "shadow"
    days: int | None = None
    attack_plan: list[dict[str, Any]] | None = None
    name: str | None = None


class ControllerPatch(BaseModel):
    mode: str


class AttackForce(BaseModel):
    scheme_id: str
    params: dict[str, Any] = Field(default_factory=dict)


class Resolve(BaseModel):
    decision: str
    by: str = "judge"


class ReplayPlay(BaseModel):
    speed: float = 1.0
    episode_id: str | None = None


@router.post("/episodes", status_code=201)
async def create_episode(body: EpisodeCreate):
    if body.controller_mode not in ("off", "shadow", "enforce"):
        raise HTTPException(422, "controller_mode must be off|shadow|enforce")
    ep_id = db.new_id("ep")
    seed = body.seed if body.seed is not None else random.randint(1, 10**6)
    days = body.days or settings.episode_default_days
    await db.execute(
        "INSERT INTO episodes (id, seed, controller_mode, days, attack_plan) VALUES ($1,$2,$3,$4,$5)", ep_id, seed, body.controller_mode, days, body.attack_plan
    )
    await company.seed_episode(ep_id, seed)
    return db.row_to_dict(await db.fetchrow("SELECT * FROM episodes WHERE id=$1", ep_id))


@router.get("/episodes")
async def list_episodes():
    return db.rows_to_list(await db.fetch("SELECT * FROM episodes ORDER BY created_at DESC LIMIT 50"))


@router.get("/episodes/{episode_id}")
async def get_episode(episode_id: str):
    row = await db.fetchrow("SELECT * FROM episodes WHERE id=$1", episode_id)
    if not row:
        raise HTTPException(404)
    return db.row_to_dict(row)


@router.post("/episodes/{episode_id}/start", status_code=202)
async def start_episode(episode_id: str):
    await _must_exist(episode_id)
    await runner.start(episode_id)
    return {"ok": True}


@router.post("/episodes/{episode_id}/pause")
async def pause_episode(episode_id: str):
    await _must_exist(episode_id)
    await runner.pause(episode_id)
    return {"ok": True}


@router.post("/episodes/{episode_id}/resume")
async def resume_episode(episode_id: str):
    await _must_exist(episode_id)
    await runner.resume(episode_id)
    return {"ok": True}


@router.post("/episodes/{episode_id}/step")
async def step_episode(episode_id: str):
    await _must_exist(episode_id)
    try:
        return await runner.step(episode_id)
    except RuntimeError as e:
        raise HTTPException(409, str(e))


@router.get("/episodes/{episode_id}/score")
async def episode_score(episode_id: str):
    await _must_exist(episode_id)
    return await score.compute(episode_id)


@router.patch("/episodes/{episode_id}/controller")
async def set_controller(episode_id: str, body: ControllerPatch):
    if body.mode not in ("off", "shadow", "enforce"):
        raise HTTPException(422)
    await _must_exist(episode_id)
    await runner.set_controller(episode_id, body.mode)
    return {"ok": True, "mode": body.mode}


@router.post("/episodes/{episode_id}/attack", status_code=202)
async def force_attack(episode_id: str, body: AttackForce):
    await _must_exist(episode_id)
    runner.force_attack(episode_id, body.scheme_id, body.params)
    return {"ok": True, "queued_for": "next red turn"}


@router.get("/schemes")
async def schemes():
    return await agents.schemes()


@router.get("/escalations")
async def list_escalations(episode_id: str | None = None, status: str = "open"):
    rows = await db.fetch(
        "SELECT e.id, e.verdict_id, e.status, e.expires_at, e.opened_at, v.action, v.amount, v.reason, v.entity_type, v.entity_id, v.episode_id "
        "FROM escalations e JOIN verdicts v ON v.id=e.verdict_id "
        "WHERE ($1::text IS NULL OR e.episode_id=$1) AND ($2::text IS NULL OR e.status=$2) ORDER BY e.opened_at DESC",
        episode_id,
        status if status != "all" else None,
    )
    return db.rows_to_list(rows)


@router.post("/escalations/{esc_id}/resolve")
async def resolve(esc_id: str, body: Resolve):
    if body.decision not in ("approve", "block"):
        raise HTTPException(422)
    ok = await gatekeeper.resolve_escalation(esc_id, body.decision, body.by)
    if not ok:
        raise HTTPException(409, "already resolved or unknown")
    return {"ok": True}


@router.get("/attacks/all")
async def all_attacks(episode_id: str):
    return db.rows_to_list(await db.fetch("SELECT * FROM attacks WHERE episode_id=$1 ORDER BY day_launched, created_at, id", episode_id))


@router.get("/health")
async def health():
    agents_health = await asyncio.gather(*(agents.health(a) for a in ("red", "green", "blue")))
    return {"ok": True, "db": True, "agents": {h.get("agent", a): h for a, h in zip(("red", "green", "blue"), agents_health, strict=True)}}


# ---------- replays ----------


@router.get("/replays")
async def list_replays():
    d = Path(settings.fixtures_dir)
    return [p.stem for p in sorted(d.glob("*.jsonl"))] if d.exists() else []


@router.post("/replays/{replay_id}/play", status_code=202)
async def play_replay(replay_id: str, body: ReplayPlay):
    p = Path(settings.fixtures_dir) / f"{replay_id}.jsonl"
    if not p.exists():
        raise HTTPException(404)
    virtual = body.episode_id or f"replay_{replay_id}"
    asyncio.create_task(_stream_fixture(p, virtual, body.speed))
    return {"ok": True, "episode_id": virtual}


async def _stream_fixture(p: Path, episode_id: str, speed: float) -> None:
    prev_ts = None
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        ev = json.loads(line)
        if prev_ts and ev.get("ts") and speed > 0:
            from datetime import datetime

            dt = (datetime.fromisoformat(ev["ts"]) - datetime.fromisoformat(prev_ts)).total_seconds()
            await asyncio.sleep(min(max(dt / speed, 0), 3.0))
        prev_ts = ev.get("ts")
        bus._broadcast(episode_id, {**ev, "episode_id": episode_id, "replay": True})


async def _must_exist(episode_id: str) -> None:
    if not await db.fetchval("SELECT 1 FROM episodes WHERE id=$1", episode_id):
        raise HTTPException(404, "episode not found")
