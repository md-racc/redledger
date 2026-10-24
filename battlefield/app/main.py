"""Battlefield FastAPI app. Owner: Dev Ad."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db
from .api import blue_writes, control, events_api, extension_points, frontend, green_writes, reads, red_writes
from .config import settings
from .events import bus
from .gate import gatekeeper

log = structlog.get_logger(__name__)

RESTART_MESSAGE = "battlefield restarted mid-episode; resume to continue"


def _configure_logging() -> None:
    logging.basicConfig(level=settings.log_level.upper())
    structlog.configure(
        processors=[structlog.processors.TimeStamper(fmt="iso"), structlog.processors.add_log_level, structlog.processors.JSONRenderer()],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(settings.log_level.upper())),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_logging()
    await db.init_pool()
    await recover_after_restart()
    yield
    await db.close_pool()


async def recover_after_restart() -> None:
    """State a previous process left behind. The orchestrator loop and the escalation waiters live in
    memory, so after a restart (1) open escalations have no held request behind them: time them out;
    (2) episodes still marked `running` have no loop: mark them `paused` with an `error` event so the
    UI shows why. Never auto-resumed; a human resumes. Replay episodes (`replay_*`) are left alone."""
    expired = await gatekeeper.expire_orphaned_escalations()
    rows = await db.fetch("UPDATE episodes SET status='paused' WHERE status='running' AND id NOT LIKE 'replay\\_%' RETURNING id, current_day")
    for r in rows:
        await bus.emit(r["id"], r["current_day"], "error", {"where": "orchestrator", "message": RESTART_MESSAGE})
        await bus.emit(r["id"], r["current_day"], "episode.paused", {})
    if expired or rows:
        log.warning("recovered_after_restart", escalations_expired=expired, episodes_paused=[r["id"] for r in rows])


app = FastAPI(title="Red Ledger — battlefield", version="0.1.0", lifespan=lifespan)
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
app.include_router(blue_writes.router, prefix="/api", tags=["blue"])
app.include_router(events_api.router, prefix="/api", tags=["events"])
app.include_router(control.router, prefix="/api", tags=["control"])
app.include_router(frontend.router, prefix="/api", tags=["frontend"])
app.include_router(extension_points.router, prefix="/api", tags=["extension-points"])

# Team extensions: battlefield/extensions/<area>_*.py → /api/x/<area>/...
import extensions as _ext  # noqa: E402

_mounted = _ext.mount_all(app)


@app.get("/")
async def root():
    return {"service": "battlefield", "ok": True, "extensions": _mounted}
