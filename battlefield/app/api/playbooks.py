"""Agent playbooks: each agent's versioned strategy document in a lineage. Owner: Dev Ad.

contracts/ledger-api.yaml `/playbook*`, schema `playbooks`. A playbook belongs to (lineage, agent);
the lineage is the one of the caller's X-Episode, the agent is X-Agent. No route takes an agent
parameter, so an agent can only ever read or write its own playbook (agent-service.md: no agent sees
another agent's playbook). Content is opaque here: battlefield only versions it.

Writes (`PUT`) are serialised per (lineage, agent) with a transaction-scoped advisory lock, so the
stale-`base_version` check and the version number are race-free; UNIQUE (lineage_id, agent, version)
is the backstop. A retry with the same X-Tool-Use-Id and the same body returns the version it made.
Audit rows use action `playbook.put` and are operator-only (`reads.list_audit`).
"""

from __future__ import annotations

import json
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .. import db
from ..auth import Caller, allow
from ..events import bus
from . import audit

router = APIRouter()
AGENT = allow("red", "green", "blue", operator=False)

MAX_CONTENT_BYTES = 65536  # schema CHECK octet_length(content::text) <= 65536
NOT_LINEAGE = "not a lineage episode"
STALE = "stale base_version"
KEY_REUSED = "idempotency key reused for a different playbook write"
ACTION = "playbook.put"
FIELDS = ("version", "parent_version", "generation", "episode_id", "day", "source", "content", "rationale", "created_at")


class PlaybookPut(BaseModel):
    content: dict[str, Any]
    rationale: str = ""
    base_version: int = Field(..., description="version this write is based on; must be the latest")


def _out(row: asyncpg.Record) -> dict[str, Any]:
    d = db.row_to_dict(row) or {}
    return {k: d.get(k) for k in FIELDS}


def _error(status: int, error: str, **extra: Any) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": error, **extra})


async def _lineage(c: Caller) -> tuple[str, int] | None:
    """(lineage_id, generation) of the caller's episode, or None outside lineages."""
    row = await db.fetchrow("SELECT lineage_id, generation FROM episodes WHERE id=$1", c.episode_id)
    if row is None or row["lineage_id"] is None:
        return None
    return row["lineage_id"], row["generation"] or 0


def _seed_out() -> dict[str, Any]:
    """Version 0 as reads report it when no row exists yet (reads never write)."""
    return {k: None for k in FIELDS} | {"version": 0, "generation": 0, "source": "seed", "content": {}, "rationale": ""}


async def _ensure_seed(conn: Any, lineage_id: str, agent: str) -> None:
    """Version 0 is written by `POST /lineages`; until then the first PUT writes it, under the write lock."""
    await conn.execute(
        "INSERT INTO playbooks (lineage_id, agent, version, generation, source, content) VALUES ($1,$2,0,0,'seed','{}'::jsonb)"
        " ON CONFLICT (lineage_id, agent, version) DO NOTHING",
        lineage_id,
        agent,
    )


@router.get("/playbook")
async def get_playbook(c: Caller = Depends(AGENT)):
    ln = await _lineage(c)
    if ln is None:
        return _error(404, NOT_LINEAGE)
    row = await db.fetchrow("SELECT * FROM playbooks WHERE lineage_id=$1 AND agent=$2 ORDER BY version DESC LIMIT 1", ln[0], c.agent)
    return _out(row) if row is not None else _seed_out()


@router.get("/playbook/history")
async def playbook_history(limit: int = Query(20, ge=1, le=100), c: Caller = Depends(AGENT)):
    ln = await _lineage(c)
    if ln is None:
        return _error(404, NOT_LINEAGE)
    rows = await db.fetch("SELECT * FROM playbooks WHERE lineage_id=$1 AND agent=$2 ORDER BY version DESC LIMIT $3", ln[0], c.agent, limit)
    out = [_out(r) for r in rows]
    if len(out) < limit and (not out or out[-1]["version"] != 0):
        out.append(_seed_out())  # no v0 row yet: nothing was ever written
    return out


@router.put("/playbook")
async def put_playbook(body: PlaybookPut, c: Caller = Depends(AGENT)):
    size = len(json.dumps(body.content, ensure_ascii=False).encode())
    args = {"base_version": body.base_version, "bytes": size}
    ln = await _lineage(c)
    if ln is None:
        await audit.record(c, ACTION, args, {"error": NOT_LINEAGE}, 404)
        return _error(404, NOT_LINEAGE)
    if size > MAX_CONTENT_BYTES:
        await audit.record(c, ACTION, args, {"error": "content too large"}, 413)
        return _error(413, f"content over {MAX_CONTENT_BYTES} bytes serialized", bytes=size)
    lineage_id, generation = ln

    async with db.pool().acquire() as conn, conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock(hashtext('playbooks'), hashtext($1 || '/' || $2))", lineage_id, c.agent)
        await _ensure_seed(conn, lineage_id, c.agent)  # type: ignore[arg-type]
        prior = await conn.fetchrow("SELECT * FROM playbooks WHERE lineage_id=$1 AND agent=$2 AND tool_use_id=$3", lineage_id, c.agent, c.tool_use_id)
        if prior is not None:
            same = prior["content"] == body.content and prior["rationale"] == body.rationale and prior["parent_version"] == body.base_version
            if not same:
                await audit.record(c, ACTION, args, {"error": KEY_REUSED, "version": prior["version"]}, 409, conn=conn)
                return _error(409, KEY_REUSED)
            await audit.record(c, ACTION, args, {"version": prior["version"], "retry": True}, 200, conn=conn)
            return _out(prior)
        latest = await conn.fetchval("SELECT max(version) FROM playbooks WHERE lineage_id=$1 AND agent=$2", lineage_id, c.agent)
        if body.base_version != latest:
            await audit.record(c, ACTION, args, {"error": STALE, "latest": latest}, 409, conn=conn)
            return _error(409, STALE, latest=latest)
        try:
            async with conn.transaction():  # savepoint: a CHECK failure must not abort the audit write below
                row = await conn.fetchrow(
                    "INSERT INTO playbooks (lineage_id, agent, version, parent_version, generation, episode_id, day, source, content, rationale, tool_use_id)"
                    " VALUES ($1,$2,$3,$4,$5,$6,$7,'turn',$8,$9,$10) RETURNING *",
                    lineage_id,
                    c.agent,
                    latest + 1,
                    latest,
                    generation,
                    c.episode_id,
                    c.day,
                    body.content,
                    body.rationale,
                    c.tool_use_id,
                )
        except asyncpg.CheckViolationError:  # jsonb's text form can be longer than the json.dumps estimate
            await audit.record(c, ACTION, args, {"error": "content too large"}, 413, conn=conn)
            return _error(413, f"content over {MAX_CONTENT_BYTES} bytes serialized", bytes=size)
        await audit.record(c, ACTION, args, {"version": row["version"]}, 201, conn=conn)

    await bus.emit(
        c.episode_id,  # type: ignore[arg-type]
        c.day,  # type: ignore[arg-type]
        "playbook.updated",
        {
            "agent": c.agent,
            "version": row["version"],
            "parent_version": row["parent_version"],
            "generation": generation,
            "source": "turn",
            "rationale": body.rationale,
        },
    )
    return JSONResponse(status_code=201, content=_out(row))
