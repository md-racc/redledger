"""FastAPI app factory for agent services. Owner: Dev Ad.

    # red/server.py
    from agentkit.server import make_agent_app
    from red.agent import RedAgent
    app = make_agent_app(RedAgent)

Gives every agent /health and /turn with auth, timeouts, and logging handled identically.
Red adds /schemes and blue adds /gate and /audit by passing `extra_routes`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import structlog
from fastapi import Depends, FastAPI, Header, HTTPException

from .config import AgentSettings
from .droid_agent import DroidAgent
from .models import HealthResponse, TurnRequest, TurnResponse

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
        if authorization != f"Bearer {s.internal_token}":
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

    if extra_routes:
        extra_routes(app, agent, s)
    return app


def bearer_dependency(settings: AgentSettings) -> Callable[..., None]:
    def auth(authorization: str | None = Header(default=None)) -> None:
        if authorization != f"Bearer {settings.internal_token}":
            raise HTTPException(401, "bad token")

    return auth
