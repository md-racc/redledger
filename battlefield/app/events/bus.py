"""Event bus: persist to `events`, fan out to WebSocket subscribers. Owner: Dev Ad.

emit() is the single function every other module uses. It is awaited so ordering is causal.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

import structlog

from .. import db

log = structlog.get_logger(__name__)

_subs: dict[str, set[asyncio.Queue]] = defaultdict(set)
_all_subs: set[asyncio.Queue] = set()


async def emit(episode_id: str, day: int, type_: str, payload: dict[str, Any] | None = None, *, agent: str | None = "battlefield") -> dict[str, Any]:
    row = await db.fetchrow(
        "INSERT INTO events (episode_id, day, type, agent, payload) VALUES ($1,$2,$3,$4,$5) RETURNING id, ts",
        episode_id,
        day,
        type_,
        agent,
        payload or {},
    )
    ev = {"id": row["id"], "ts": row["ts"].isoformat(), "episode_id": episode_id, "day": day, "type": type_, "agent": agent, "payload": payload or {}}
    _broadcast(episode_id, ev)
    return ev


async def emit_many(episode_id: str, day: int, agent: str, items: list[dict[str, Any]]) -> int:
    if not items:
        return 0
    async with db.pool().acquire() as conn:
        rows = await conn.fetch(
            "INSERT INTO events (episode_id, day, type, agent, payload) "
            "SELECT $1, $2, x.type, $3, x.payload FROM jsonb_to_recordset($4::jsonb) AS x(type text, payload jsonb) "
            "RETURNING id, ts, type, payload",
            episode_id,
            day,
            agent,
            items,
        )
    for r in rows:
        _broadcast(
            episode_id,
            {"id": r["id"], "ts": r["ts"].isoformat(), "episode_id": episode_id, "day": day, "type": r["type"], "agent": agent, "payload": r["payload"]},
        )
    return len(rows)


def _broadcast(episode_id: str, ev: dict[str, Any]) -> None:
    for q in list(_subs.get(episode_id, ())) + list(_all_subs):
        try:
            q.put_nowait(ev)
        except asyncio.QueueFull:
            log.warning("ws_subscriber_slow_dropping")


def subscribe(episode_id: str | None) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=2000)
    (_subs[episode_id] if episode_id else _all_subs).add(q)
    return q


def unsubscribe(episode_id: str | None, q: asyncio.Queue) -> None:
    (_subs.get(episode_id, set()) if episode_id else _all_subs).discard(q)


async def history(episode_id: str, after_id: int = 0, limit: int = 500) -> list[dict[str, Any]]:
    rows = await db.fetch(
        "SELECT id, ts, episode_id, day, type, agent, payload FROM events WHERE episode_id=$1 AND id>$2 ORDER BY id LIMIT $3",
        episode_id,
        after_id,
        limit,
    )
    return db.rows_to_list(rows)
