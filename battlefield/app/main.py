"""Battlefield FastAPI app. Owner: Dev Ad."""

from __future__ import annotations

import logging
import math
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import db, turns
from .api import blue_writes, control, events_api, extension_points, fixtures, frontend, green_writes, playbooks, preparations, reads, red_writes
from .config import settings
from .events import bus
from .gate import gatekeeper

log = structlog.get_logger(__name__)

RESTART_MESSAGE = "battlefield restarted mid-episode; resume to continue"
REPLAY_RESTART_MESSAGE = "battlefield restarted mid-replay"


def _configure_logging() -> None:
    logging.basicConfig(level=settings.log_level.upper())
    structlog.configure(
        processors=[structlog.processors.TimeStamper(fmt="iso"), structlog.processors.add_log_level, structlog.processors.JSONRenderer()],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(settings.log_level.upper())),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_logging()
    gatekeeper.check_preparation_budget()  # refuse to start if an escalation hold could outlive a preparation
    await db.init_pool()
    await recover_after_restart()
    yield
    await control.shutdown_replays()  # before the pool closes: cancelled replays mark themselves failed
    await db.close_pool()


async def recover_after_restart() -> None:
    """State a previous process left behind. The orchestrator loop and the escalation waiters live in
    memory, so after a restart (1) open escalations have no held request behind them: time them out;
    (2) episodes still marked `running` have no loop: mark them `paused` with an `error` event so the
    UI shows why. Never auto-resumed; a human resumes. (3) replay episodes (`replay_*`) still `running`
    lost their streaming task without the graceful shutdown that marks them failed: mark them `failed`
    with an `error {where:"replay"}` event."""
    expired = await gatekeeper.expire_orphaned_escalations()
    preps = await preparations.sweep_pending()  # their escalation hold died with the old process: block / timeout
    rows = await db.fetch("UPDATE episodes SET status='paused' WHERE status='running' AND id NOT LIKE 'replay\\_%' RETURNING id, current_day")
    for r in rows:
        await bus.emit(r["id"], r["current_day"], "error", {"where": "orchestrator", "message": RESTART_MESSAGE})
        await bus.emit(r["id"], r["current_day"], "episode.paused", {})
    lineages = await db.fetch("UPDATE lineages SET status='paused' WHERE status='running' RETURNING id, current_generation")
    for ln in lineages:  # the lineage loop lives in memory too: paused, resumed by a human (POST /lineages/{id}/resume)
        ep = await db.fetchrow("SELECT id, current_day FROM episodes WHERE lineage_id=$1 AND generation=$2", ln["id"], ln["current_generation"])
        if ep is not None:
            await bus.emit(ep["id"], ep["current_day"], "lineage.paused", {"lineage_id": ln["id"], "generation": ln["current_generation"]})
    replays = await db.fetch("UPDATE episodes SET status='failed', finished_at=now() WHERE status='running' AND id LIKE 'replay\\_%' RETURNING id, current_day")
    for r in replays:
        await bus.emit(r["id"], r["current_day"], "error", {"where": "replay", "message": REPLAY_RESTART_MESSAGE})
    if expired or preps or rows or replays or lineages:
        log.warning(
            "recovered_after_restart",
            escalations_expired=expired,
            preparations_expired=preps,
            episodes_paused=[r["id"] for r in rows],
            replays_failed=[r["id"] for r in replays],
            lineages_paused=[ln["id"] for ln in lineages],
        )


app = FastAPI(title="Red Ledger — battlefield", version="0.1.0", lifespan=lifespan)


@app.exception_handler(turns.NoActiveTurnError)
async def _no_active_turn(request: Request, exc: turns.NoActiveTurnError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"error": turns.NO_ACTIVE_TURN})


def _finite(x: object) -> object:
    if isinstance(x, float) and not math.isfinite(x):
        return str(x)
    if isinstance(x, dict):
        return {k: _finite(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [_finite(v) for v in x]
    return x


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """FastAPI's default 422, except that a non-finite number echoed in an error's `input` (a body with
    NaN/Infinity, which the JSON parser accepts) is rendered as a string; the default handler cannot
    serialize it and the request would fail with a 500 instead of a 422."""
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(_finite(exc.errors()))})


app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)

app.include_router(reads.router, prefix="/api", tags=["read"])
app.include_router(red_writes.router, prefix="/api", tags=["red"])
app.include_router(green_writes.router, prefix="/api", tags=["green"])
app.include_router(preparations.router, prefix="/api", tags=["green"])
app.include_router(blue_writes.router, prefix="/api", tags=["blue"])
app.include_router(events_api.router, prefix="/api", tags=["events"])
app.include_router(control.router, prefix="/api", tags=["control"])
app.include_router(frontend.router, prefix="/api", tags=["frontend"])
app.include_router(extension_points.router, prefix="/api", tags=["extension-points"])
app.include_router(playbooks.router, prefix="/api", tags=["playbooks"])
app.include_router(fixtures.router, prefix="/api", tags=["control"])

# Team extensions: battlefield/extensions/<area>_*.py → /api/x/<area>/...
import extensions as _ext  # noqa: E402

_mounted = _ext.mount_all(app)


@app.get("/")
async def root():
    return {"service": "battlefield", "ok": True, "extensions": _mounted}
