"""HTTP calls from battlefield to the three agent services. Owner: Dev Ad."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
import structlog

from ..config import settings

log = structlog.get_logger(__name__)

URLS = {"red": settings.red_url, "green": settings.green_url, "blue": settings.blue_url}

# An agent serves one turn at a time and answers 409 "... in progress" while busy. Another run should
# not exist (orchestrator/active.py), but a turn that is just finishing can still overlap by a moment,
# so retry that 409 briefly before recording the turn as failed.
BUSY_RETRY_SEC = 10.0


def _headers(agent: str) -> dict[str, str]:
    """Each agent is called with its own token (contracts/agent-service.md "Tokens")."""
    return {"Authorization": f"Bearer {settings.token_for(agent)}"}


def _busy(r: httpx.Response) -> bool:
    return r.status_code == 409 and "in progress" in r.text


async def _post(client: httpx.AsyncClient, agent: str, path: str, body: dict[str, Any]) -> httpx.Response:
    """POST to an agent, retrying its busy 409 with backoff for up to BUSY_RETRY_SEC."""
    deadline, delay = time.monotonic() + BUSY_RETRY_SEC, 0.5
    while True:
        r = await client.post(f"{URLS[agent]}{path}", json=body, headers=_headers(agent))
        if not _busy(r) or time.monotonic() + delay > deadline:
            return r
        log.info("agent_busy_retry", agent=agent, path=path, episode_id=body.get("episode_id"), delay_sec=delay)
        await asyncio.sleep(delay)
        delay = min(delay * 2, 4.0)


async def turn(agent: str, episode_id: str, day: int, controller_mode: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    body = {"episode_id": episode_id, "day": day, "controller_mode": controller_mode, "options": options or {}}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(settings.turn_timeout_sec + 5, connect=10)) as client:
            r = await _post(client, agent, "/turn", body)
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
            r = await _post(client, "blue", "/audit", body)
            return r.json() if r.status_code < 400 else {"ok": False, "summary": r.text[:200]}
    except Exception as e:
        return {"ok": False, "summary": f"blue unreachable: {type(e).__name__}"}


async def reflect(agent: str, body: dict[str, Any]) -> dict[str, Any]:
    """POST {agent}/reflect (contracts/agent-service.md). Any failure → ok false: the playbook is kept."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(settings.turn_timeout_sec + 5, connect=10)) as client:
            r = await _post(client, agent, "/reflect", body)
            if r.status_code >= 400:
                return {"ok": False, "rationale": f"{agent} returned {r.status_code}: {r.text[:200]}"}
            return r.json()
    except Exception as e:
        log.warning("agent_reflect_failed", agent=agent, episode_id=body.get("episode_id"), error=str(e))
        return {"ok": False, "rationale": f"{agent} unreachable: {type(e).__name__}"}


async def schemes() -> list[dict[str, Any]]:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{settings.red_url}/schemes", headers=_headers("red"))
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
