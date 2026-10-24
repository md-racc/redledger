"""FastAPI app factory for agent services. Owner: Dev Ad.

    # red/server.py
    from agentkit.server import make_agent_app
    from red.agent import RedAgent
    app = make_agent_app(RedAgent)

Gives every agent /health, /turn and /reflect with auth, timeouts, and logging handled identically.
Red adds /schemes and blue adds /gate and /audit by passing `extra_routes`.
"""

from __future__ import annotations

import asyncio
import hmac
import time
from collections.abc import Callable
from typing import Any

import structlog
from fastapi import Depends, FastAPI, Header, HTTPException

from .config import AgentSettings
from .droid_agent import DroidAgent
from .models import HealthResponse, ReflectRequest, ReflectResponse, TurnRequest, TurnResponse

log = structlog.get_logger(__name__)


def make_agent_app(
    agent_cls: type[DroidAgent],
    *,
    settings: AgentSettings | None = None,
    extra_routes: Callable[[FastAPI, DroidAgent, AgentSettings], None] | None = None,
) -> FastAPI:
    s = settings or AgentSettings()  # type: ignore[call-arg]
    agent = agent_cls(s)
    app = FastAPI(title=f"redledger-{s.agent_name}", version="0.1.0")
    app.state.agent = agent
    app.state.settings = s
    turn_lock = asyncio.Lock()

    def auth(authorization: str | None = Header(default=None)) -> None:
        if not hmac.compare_digest((authorization or "").encode(), f"Bearer {s.internal_token}".encode()):
            raise HTTPException(401, "bad token")

    @app.get("/health", response_model=HealthResponse)
    async def health() -> Any:
        return await agent.health()

    @app.post("/turn", response_model=TurnResponse, dependencies=[Depends(auth)])
    async def turn(req: TurnRequest) -> TurnResponse:
        if turn_lock.locked():
            raise HTTPException(409, "turn already in progress")
        async with turn_lock:
            log.info("turn_start", agent=s.agent_name, episode_id=req.episode_id, day=req.day)
            resp = await agent.run_turn(req)
            log.info("turn_end", agent=s.agent_name, day=req.day, ok=resp.ok, duration=round(resp.duration_sec, 1))
            return resp

    @app.post("/reflect", response_model=ReflectResponse, dependencies=[Depends(auth)])
    async def reflect(req: ReflectRequest) -> ReflectResponse:
        if turn_lock.locked():  # one turn or reflection at a time, same as /turn
            raise HTTPException(409, "turn already in progress")
        async with turn_lock:
            t0 = time.monotonic()
            log.info("reflect_start", agent=s.agent_name, lineage_id=req.lineage_id, generation=req.generation, episode_id=req.episode_id)
            resp = await agent.run_reflect(req)
            log.info(
                "reflect_end",
                agent=s.agent_name,
                lineage_id=req.lineage_id,
                generation=req.generation,
                ok=resp.ok,
                changed=resp.playbook is not None,
                factory_credits=resp.usage.factory_credits if resp.usage else None,
                duration=round(time.monotonic() - t0, 1),
            )
            return resp

    if extra_routes:
        extra_routes(app, agent, s)
    return app


def bearer_dependency(settings: AgentSettings) -> Callable[..., None]:
    def auth(authorization: str | None = Header(default=None)) -> None:
        if not hmac.compare_digest((authorization or "").encode(), f"Bearer {settings.internal_token}".encode()):
            raise HTTPException(401, "bad token")

    return auth
