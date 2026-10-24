"""HTTP calls from battlefield to the three agent services. Owner: Dev Ad."""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from ..config import settings

log = structlog.get_logger(__name__)

URLS = {"red": settings.red_url, "green": settings.green_url, "blue": settings.blue_url}


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.agent_token}"}


async def turn(agent: str, episode_id: str, day: int, controller_mode: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    body = {"episode_id": episode_id, "day": day, "controller_mode": controller_mode, "options": options or {}}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(settings.turn_timeout_sec + 5, connect=10)) as client:
            r = await client.post(f"{URLS[agent]}/turn", json=body, headers=_headers())
            if r.status_code >= 400:
                return {"ok": False, "summary": f"{agent} returned {r.status_code}: {r.text[:200]}", "duration_sec": 0}
            return r.json()
    except Exception as e:
        log.warning("agent_turn_failed", agent=agent, error=str(e))
        return {"ok": False, "summary": f"{agent} unreachable: {type(e).__name__}", "duration_sec": 0}


async def audit(episode_id: str, day: int, inputs: list[dict[str, Any]] | None = None, **lineage: Any) -> dict[str, Any]:
    """`lineage` holds blue's `lineage` / `debrief` fields in a lineage episode (contracts/agent-service.md); empty otherwise."""
    body = {"episode_id": episode_id, "day": day, "inputs": inputs or [], **lineage}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(settings.turn_timeout_sec + 5, connect=10)) as client:
            r = await client.post(f"{settings.blue_url}/audit", json=body, headers=_headers())
            return r.json() if r.status_code < 400 else {"ok": False, "summary": r.text[:200]}
    except Exception as e:
        return {"ok": False, "summary": f"blue unreachable: {type(e).__name__}"}


async def reflect(agent: str, body: dict[str, Any]) -> dict[str, Any]:
    """POST {agent}/reflect (contracts/agent-service.md). Any failure → ok false: the playbook is kept."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(settings.turn_timeout_sec + 5, connect=10)) as client:
            r = await client.post(f"{URLS[agent]}/reflect", json=body, headers=_headers())
            if r.status_code >= 400:
                return {"ok": False, "rationale": f"{agent} returned {r.status_code}: {r.text[:200]}"}
            return r.json()
    except Exception as e:
        log.warning("agent_reflect_failed", agent=agent, episode_id=body.get("episode_id"), error=str(e))
        return {"ok": False, "rationale": f"{agent} unreachable: {type(e).__name__}"}


async def schemes() -> list[dict[str, Any]]:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{settings.red_url}/schemes", headers=_headers())
            r.raise_for_status()
            return r.json()
    except Exception as e:
        log.warning("schemes_unavailable", error=str(e))
        return []


async def health(agent: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{URLS[agent]}/health")
            return r.json()
    except Exception as e:
        return {"ok": False, "agent": agent, "error": str(e)}
