"""Control plane: episodes, controller toggle, attacks, escalations, replays, health. Owner: Dev Ad."""

from __future__ import annotations

import asyncio
import json
import random
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import asyncpg
import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError

from agentkit.models import LineageConfig
from seed import company

from .. import db
from ..auth import bearer
from ..config import settings
from ..events import bus
from ..gate import gatekeeper
from ..orchestrator import agents, lineage, runner
from ..scoring import score

log = structlog.get_logger(__name__)

router = APIRouter(dependencies=[Depends(bearer)])


class EpisodeCreate(BaseModel):
    seed: int | None = None
    controller_mode: str = "shadow"
    days: int | None = None
    attack_plan: list[dict[str, Any]] | None = None
    name: str | None = None
    lineage_id: str | None = None  # run as that (finished/failed) lineage's next generation


class LineageCreate(BaseModel):
    name: str = ""
    base_seed: int | None = None
    config: dict[str, Any] = Field(default_factory=dict)


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
    episode_id: str | None = None  # id for the new replay episode; must start with replay_ and not exist


@router.post("/episodes", status_code=201)
async def create_episode(body: EpisodeCreate):
    if body.controller_mode not in ("off", "shadow", "enforce"):
        raise HTTPException(422, "controller_mode must be off|shadow|enforce")
    if body.lineage_id is not None:
        return await _lineage_episode(body)
    ep_id = db.new_id("ep")
    seed = body.seed if body.seed is not None else random.randint(1, 10**6)
    days = body.days or settings.episode_default_days
    await db.execute(
        "INSERT INTO episodes (id, seed, controller_mode, days, attack_plan) VALUES ($1,$2,$3,$4,$5)", ep_id, seed, body.controller_mode, days, body.attack_plan
    )
    await company.seed_episode(ep_id, seed)
    return db.row_to_dict(await db.fetchrow("SELECT * FROM episodes WHERE id=$1", ep_id))


async def _lineage_episode(body: EpisodeCreate) -> dict[str, Any]:
    """The real-time demo: a finished (or failed) lineage's next generation, started by hand, never headless."""
    ln = await db.fetchrow("SELECT * FROM lineages WHERE id=$1", body.lineage_id)
    if ln is None:
        raise HTTPException(404, "unknown lineage_id")
    if ln["status"] not in ("finished", "failed"):
        raise HTTPException(409, f"lineage is {ln['status']}: its runner owns generation creation")
    g = ln["current_generation"] + 1
    seed = body.seed if body.seed is not None else ln["base_seed"] + g
    if await db.fetchval("SELECT 1 FROM episodes WHERE lineage_id=$1 AND seed=$2", ln["id"], seed):
        raise HTTPException(422, "seed already used by an episode of this lineage")
    days = body.days or lineage.config(ln).days
    try:
        eid = await lineage.create_generation(ln["id"], g, seed=seed, days=days, mode=body.controller_mode, attack_plan=body.attack_plan)
    except asyncpg.UniqueViolationError:  # a concurrent create took the generation or the seed
        raise HTTPException(409, "lineage generation or seed taken concurrently") from None
    return db.row_to_dict(await db.fetchrow("SELECT * FROM episodes WHERE id=$1", eid))  # type: ignore[return-value]


# ---------- lineages ----------


async def _lineage_out(row: Any) -> dict[str, Any]:
    out = db.row_to_dict(row) or {}
    eps = await db.fetch("SELECT id, generation, seed, status FROM episodes WHERE lineage_id=$1 ORDER BY generation", row["id"])
    out["generations"] = [
        {"generation": e["generation"], "episode_id": e["id"], "seed": e["seed"], "status": e["status"], "score": await score.compute(e["id"])} for e in eps
    ]
    versions = {r["agent"]: r["v"] for r in await db.fetch("SELECT agent, MAX(version) AS v FROM playbooks WHERE lineage_id=$1 GROUP BY agent", row["id"])}
    out["playbook_versions"] = {a: versions.get(a, 0) for a in ("red", "green", "blue")}
    return out


async def _lineage_row(lineage_id: str) -> Any:
    row = await db.fetchrow("SELECT * FROM lineages WHERE id=$1", lineage_id)
    if row is None:
        raise HTTPException(404, "unknown lineage")
    return row


async def _other_running(lineage_id: str) -> bool:
    return bool(await db.fetchval("SELECT 1 FROM lineages WHERE status='running' AND id<>$1", lineage_id))


@router.post("/lineages", status_code=201)
async def create_lineage(body: LineageCreate):
    try:
        cfg = LineageConfig.model_validate(body.config)
    except ValidationError as e:
        raise HTTPException(422, e.errors(include_url=False, include_context=False)) from None
    if cfg.headless and cfg.headless.escalation_timeout_sec > settings.escalation_timeout_sec:
        raise HTTPException(422, f"headless.escalation_timeout_sec must be <= ESCALATION_TIMEOUT_SEC ({settings.escalation_timeout_sec})")
    lid = db.new_id("ln")
    base_seed = body.base_seed if body.base_seed is not None else random.randint(1, 10**6)
    async with db.pool().acquire() as conn, conn.transaction():
        await conn.execute("INSERT INTO lineages (id, name, base_seed, config) VALUES ($1,$2,$3,$4)", lid, body.name, base_seed, cfg.model_dump())
        await lineage.seed_playbooks(conn, lid)
    return await _lineage_out(await _lineage_row(lid))


@router.get("/lineages")
async def list_lineages():
    return [await _lineage_out(r) for r in await db.fetch("SELECT * FROM lineages ORDER BY created_at DESC LIMIT 50")]


@router.get("/lineages/{lineage_id}")
async def get_lineage(lineage_id: str):
    return await _lineage_out(await _lineage_row(lineage_id))


@router.post("/lineages/{lineage_id}/start", status_code=202)
async def start_lineage(lineage_id: str):
    row = await _lineage_row(lineage_id)
    if row["status"] != "created" or await _other_running(lineage_id):
        raise HTTPException(409, "another lineage is running, or this one is not in status created")
    await lineage.start(lineage_id)
    return {"ok": True}


@router.post("/lineages/{lineage_id}/pause")
async def pause_lineage(lineage_id: str):
    if (await _lineage_row(lineage_id))["status"] != "running":
        raise HTTPException(409, "not running")
    await lineage.pause(lineage_id)
    return {"ok": True}


@router.post("/lineages/{lineage_id}/resume")
async def resume_lineage(lineage_id: str):
    if (await _lineage_row(lineage_id))["status"] != "paused" or await _other_running(lineage_id):
        raise HTTPException(409, "not paused, or another lineage is running")
    await lineage.resume(lineage_id)
    return {"ok": True}


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
    await _must_exist(episode_id, live=True)
    await runner.start(episode_id)
    return {"ok": True}


@router.post("/episodes/{episode_id}/pause")
async def pause_episode(episode_id: str):
    await _must_exist(episode_id, live=True)
    await runner.pause(episode_id)
    return {"ok": True}


@router.post("/episodes/{episode_id}/resume")
async def resume_episode(episode_id: str):
    await _must_exist(episode_id, live=True)
    await runner.resume(episode_id)
    return {"ok": True}


@router.post("/episodes/{episode_id}/step")
async def step_episode(episode_id: str):
    await _must_exist(episode_id, live=True)
    try:
        return await runner.step(episode_id)
    except RuntimeError as e:
        raise HTTPException(409, str(e))


@router.get("/episodes/{episode_id}/score")
async def episode_score(episode_id: str):
    await _must_exist(episode_id)
    return await replay_score(episode_id) if is_replay(episode_id) else await score.compute(episode_id)


@router.patch("/episodes/{episode_id}/controller")
async def set_controller(episode_id: str, body: ControllerPatch):
    if body.mode not in ("off", "shadow", "enforce"):
        raise HTTPException(422)
    await _must_exist(episode_id, live=True)
    await runner.set_controller(episode_id, body.mode)
    return {"ok": True, "mode": body.mode}


@router.post("/episodes/{episode_id}/attack", status_code=202)
async def force_attack(episode_id: str, body: AttackForce):
    await _must_exist(episode_id, live=True)
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
#
# A replay is a real episode: `episodes` row with id `replay_...`, every fixture event re-emitted
# through `bus.emit` (persisted, fresh monotonic ids, live WS fan-out), so WS `after_id` catch-up,
# `GET /events` and the event-derived `/fe/*` views work for it like for a live episode. It never
# has ledger rows (no seed, no agents, no runner), so table-derived views are empty for it and the
# runner/controller routes refuse it (409).

REPLAY_PREFIX = "replay_"
REPLAY_MAX_GAP_SEC = 3.0  # cap on one inter-event sleep, whatever the original gap
_REPLAY_ID_RE = re.compile(r"replay_[A-Za-z0-9_-]{1,57}")  # <=64 chars: must be a valid WS ticket scope
_ZERO_SCORE: dict[str, Any] = {
    "dollars_extracted": 0.0,
    "dollars_blocked": 0.0,
    "false_positive_cost": 0.0,
    "detection_latency_days": None,
    "attacks_launched": 0,
    "attacks_caught": 0,
    "legit_blocked": 0,
    "legit_processed": 0,
}
_PG_INT_MIN, _PG_INT_MAX = -(2**31), 2**31 - 1
_replay_tasks: set[asyncio.Task] = set()


def new_replay_id(replay_id: str) -> str:
    """`replay_<fixture>_<8 hex>`: unique per play, always a valid WS ticket scope."""
    return f"{REPLAY_PREFIX}{re.sub(r'[^A-Za-z0-9_-]', '-', replay_id)[:40]}_{uuid.uuid4().hex[:8]}"


def is_replay(episode_id: str) -> bool:
    return episode_id.startswith(REPLAY_PREFIX)


async def replay_score(episode_id: str) -> dict[str, Any]:
    """A replay's Score is the last one its events carried (`score.updated` or `episode.ended.final_score`)."""
    row = await db.fetchrow(
        "SELECT type, payload FROM events WHERE episode_id=$1 AND type IN ('score.updated','episode.ended') ORDER BY id DESC LIMIT 1", episode_id
    )
    if not row:
        return dict(_ZERO_SCORE)
    p = row["payload"] if isinstance(row["payload"], dict) else {}
    sc = p.get("final_score") if row["type"] == "episode.ended" else p
    out = dict(_ZERO_SCORE)
    if isinstance(sc, dict):  # only well-typed Score fields; anything else keeps its zero
        out.update({k: sc[k] for k in _ZERO_SCORE if isinstance(sc.get(k), int | float) and not isinstance(sc.get(k), bool)})
    return out


@router.get("/replays")
async def list_replays():
    d = Path(settings.fixtures_dir)
    return [p.stem for p in sorted(d.glob("*.jsonl"))] if d.exists() else []


@router.post("/replays/{replay_id}/play", status_code=202)
async def play_replay(replay_id: str, body: ReplayPlay):
    if replay_id not in await list_replays():
        raise HTTPException(404)
    root = Path(settings.fixtures_dir).resolve()
    path = (root / f"{replay_id}.jsonl").resolve()  # follows symlinks; the real file must stay inside the dir
    if not path.is_relative_to(root):
        raise HTTPException(404)
    events = _load_fixture(path)
    if body.episode_id is not None:
        if not _REPLAY_ID_RE.fullmatch(body.episode_id):
            raise HTTPException(422, f"episode_id must match {_REPLAY_ID_RE.pattern}")
        ep_id = body.episode_id
    else:
        ep_id = new_replay_id(replay_id)
    started = next((e.get("payload") or {} for e in events if e["type"] == "episode.started"), {})
    mode = started.get("controller_mode") if started.get("controller_mode") in ("off", "shadow", "enforce") else "shadow"
    seed = started.get("seed") if isinstance(started.get("seed"), int) else 0
    days = started.get("days") if isinstance(started.get("days"), int) else max((e["day"] for e in events), default=0) + 1
    created = await db.fetchval(
        "INSERT INTO episodes (id, seed, controller_mode, days, status, started_at) VALUES ($1,$2,$3,$4,'running',now()) ON CONFLICT (id) DO NOTHING RETURNING id",
        ep_id,
        seed,
        mode,
        days,
    )
    if not created:
        raise HTTPException(409, "episode id already exists")
    task = asyncio.create_task(_stream_fixture(events, ep_id, body.speed), name=f"replay-{ep_id}")
    _replay_tasks.add(task)
    task.add_done_callback(_replay_tasks.discard)
    return {"ok": True, "episode_id": ep_id, "events": len(events)}


def _load_fixture(p: Path) -> list[dict[str, Any]]:
    """Parse and validate a fixture up front (422 naming the line), so a bad file creates no episode."""
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:  # IsADirectoryError is an OSError
        raise HTTPException(422, f"fixture is not readable UTF-8 text ({type(e).__name__})") from None
    out: list[dict[str, Any]] = []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            raise HTTPException(422, f"fixture line {n} is not JSON") from None
        if not isinstance(ev, dict) or not isinstance(ev.get("type"), str) or not ev["type"]:
            raise HTTPException(422, f"fixture line {n} is not an event (needs a non-empty string type)")
        if ev["type"] == "ping":
            continue
        day = ev.get("day")
        day = 0 if day is None else day
        # day+1 is written on day.ended, so the top of the INT range is excluded
        if not isinstance(day, int) or isinstance(day, bool) or not (_PG_INT_MIN <= day < _PG_INT_MAX):
            raise HTTPException(422, f"fixture line {n} has a bad day (integer within Postgres INTEGER range)")
        payload = ev.get("payload")
        payload = {} if payload is None else payload
        if not isinstance(payload, dict):
            raise HTTPException(422, f"fixture line {n} has a non-object payload")
        agent = ev.get("agent", "battlefield")
        if agent is not None and not isinstance(agent, str):
            raise HTTPException(422, f"fixture line {n} has a non-string agent")
        if _has_nul(payload) or "\x00" in ev["type"] or (agent and "\x00" in agent):
            raise HTTPException(422, f"fixture line {n} contains a NUL character (Postgres text/jsonb reject it)")
        out.append({**ev, "day": day, "payload": payload, "agent": agent})
    return out


def _has_nul(x: Any) -> bool:
    if isinstance(x, str):
        return "\x00" in x
    if isinstance(x, dict):
        return any(_has_nul(k) or _has_nul(v) for k, v in x.items())
    if isinstance(x, list):
        return any(_has_nul(v) for v in x)
    return False


def _ts(ev: dict[str, Any]) -> datetime | None:
    try:
        return datetime.fromisoformat(ev["ts"]) if isinstance(ev.get("ts"), str) else None
    except ValueError:
        return None


async def _stream_fixture(events: list[dict[str, Any]], episode_id: str, speed: float) -> None:
    """Re-emit `events` under `episode_id`, paced by original ts / speed (speed <= 0: no pacing)."""
    prev: datetime | None = None
    day = 0
    try:
        for ev in events:
            ts = _ts(ev)
            if prev and ts and speed > 0:
                await asyncio.sleep(min(max((ts - prev).total_seconds() / speed, 0.0), REPLAY_MAX_GAP_SEC))
            prev = ts or prev
            day, type_, payload = ev["day"], ev["type"], ev["payload"]
            await bus.emit(episode_id, day, type_, payload, agent=ev["agent"])
            # mirror the runner's episode bookkeeping so snapshot/timeline see the right day and mode
            if type_ == "day.started":
                await db.execute("UPDATE episodes SET current_day=$2 WHERE id=$1", episode_id, day)
            elif type_ == "day.ended":
                await db.execute("UPDATE episodes SET current_day=$2 WHERE id=$1", episode_id, day + 1)
            elif type_ == "controller.changed" and payload.get("to") in ("off", "shadow", "enforce"):
                await db.execute("UPDATE episodes SET controller_mode=$2 WHERE id=$1", episode_id, payload["to"])
        await db.execute("UPDATE episodes SET status='finished', finished_at=now() WHERE id=$1", episode_id)
    except asyncio.CancelledError:
        log.warning("replay_cancelled", episode_id=episode_id)
        await _record_failure(episode_id, day, "replay cancelled (battlefield shutting down)")
        raise
    except Exception as e:
        log.exception("replay_failed", episode_id=episode_id)
        await _record_failure(episode_id, day, str(e))


async def _record_failure(episode_id: str, day: int, message: str) -> None:
    """Best effort: mark the replay failed and leave an `error` event (at `day`, else day 0)."""
    try:
        await db.execute("UPDATE episodes SET status='failed', finished_at=now() WHERE id=$1", episode_id)
    except Exception:
        log.exception("replay_fail_status_failed", episode_id=episode_id)
    for d in dict.fromkeys((day, 0)):
        try:
            await bus.emit(episode_id, d, "error", {"where": "replay", "message": message})
            return
        except Exception:
            log.exception("replay_fail_event_failed", episode_id=episode_id, day=d)


async def shutdown_replays(timeout: float = 5.0) -> None:
    """Lifespan shutdown: cancel running replays and let them record `failed` before the pool closes."""
    tasks = list(_replay_tasks)
    for t in tasks:
        t.cancel()
    if tasks:
        await asyncio.wait(tasks, timeout=timeout)


async def _must_exist(episode_id: str, *, live: bool = False) -> None:
    if not await db.fetchval("SELECT 1 FROM episodes WHERE id=$1", episode_id):
        raise HTTPException(404, "episode not found")
    if live and is_replay(episode_id):
        raise HTTPException(409, "replay episodes are event-only; they cannot be run or controlled")
