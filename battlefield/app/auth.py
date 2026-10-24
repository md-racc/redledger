"""Bearer auth + per-agent route permissions. Owner: Dev Ad.

Two kinds of caller:
  - agents: must send X-Agent / X-Episode / X-Day (+ X-Tool-Use-Id on writes). `AgentCtx` is
    injected into handlers and carries them. Responses to agents hide provenance columns.
  - operator/frontend: bearer only; no X-Agent. Sees everything.

Permissions are declared per route with `allow("red", "green")`. A route with no `allow` is
operator-only when it is a control-plane route, or all-agents when it is a read route.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request

from .config import settings

AGENTS = ("red", "green", "blue")


def bearer(authorization: str | None = Header(default=None)) -> None:
    if authorization != f"Bearer {settings.internal_token}":
        raise HTTPException(401, "bad token")


@dataclass
class Caller:
    agent: str | None  # None = operator/frontend
    episode_id: str | None
    day: int | None
    tool_use_id: str | None

    @property
    def is_agent(self) -> bool:
        return self.agent is not None

    @property
    def hide(self) -> bool:
        return self.is_agent


def caller(
    request: Request,
    _: None = Depends(bearer),
    x_agent: str | None = Header(default=None, alias="X-Agent"),
    x_episode: str | None = Header(default=None, alias="X-Episode"),
    x_day: int | None = Header(default=None, alias="X-Day"),
    x_tool_use_id: str | None = Header(default=None, alias="X-Tool-Use-Id"),
) -> Caller:
    if x_agent is not None:
        if x_agent not in AGENTS:
            raise HTTPException(400, f"unknown X-Agent {x_agent}")
        if x_episode is None or x_day is None:
            raise HTTPException(400, "agents must send X-Episode and X-Day")
        if request.method in ("POST", "PATCH", "PUT", "DELETE") and not x_tool_use_id:
            raise HTTPException(400, "writes require X-Tool-Use-Id")
    return Caller(agent=x_agent, episode_id=x_episode, day=x_day, tool_use_id=x_tool_use_id)


def allow(*agents: str, operator: bool = True):
    """Dependency: only these agents (and optionally the operator) may call the route."""

    def dep(c: Caller = Depends(caller)) -> Caller:
        if c.is_agent:
            if c.agent not in agents:
                raise HTTPException(403, f"{c.agent} may not call this route")
        elif not operator:
            raise HTTPException(403, "agents only")
        return c

    return dep


def agent_episode(c: Caller, episode_id_query: str | None = None) -> str:
    """Resolve which episode a request is about: agents from header, operator from query."""
    if c.is_agent:
        return c.episode_id  # type: ignore[return-value]
    if episode_id_query is None:
        raise HTTPException(400, "episode_id required")
    return episode_id_query
