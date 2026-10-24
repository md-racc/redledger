"""Core extension-point routes: agent state KV, inputs inbox, generic read query. Owner: Dev Ad.

These exist so other teams can add behavior without a contracts PR:
  - /state/{key}       per-agent JSON memory across turns (agents) — no schema change needed
  - /inputs            leave a message for an agent's next turn (frontend / extensions / judge)
  - /fe/query          read-only SQL for the frontend (operator token). Statement timeout, SELECT only,
                        runs as the app role. This is a hackathon convenience, not a security boundary.
"""

from __future__ import annotations

import re
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import db
from ..auth import Caller, allow, bearer, caller
from . import audit

log = structlog.get_logger(__name__)
router = APIRouter()


# ---------- per-agent state ----------


@router.get("/state/{key}")
async def get_state(key: str, c: Caller = Depends(allow("red", "green", "blue", operator=False))):
    row = await db.fetchrow("SELECT value FROM agent_state WHERE episode_id=$1 AND agent=$2 AND key=$3", c.episode_id, c.agent, key)
    return row["value"] if row else {}


@router.put("/state/{key}")
async def put_state(key: str, value: dict[str, Any], c: Caller = Depends(allow("red", "green", "blue", operator=False))):
    await db.execute(
        "INSERT INTO agent_state (episode_id, agent, key, value) VALUES ($1,$2,$3,$4) "
        "ON CONFLICT (episode_id, agent, key) DO UPDATE SET value=EXCLUDED.value, updated_at=now()",
        c.episode_id,
        c.agent,
        key,
        value,
    )
    return {"ok": True}


@router.get("/state")
async def list_state(c: Caller = Depends(allow("red", "green", "blue", operator=False))):
    rows = await db.fetch("SELECT key, value, updated_at FROM agent_state WHERE episode_id=$1 AND agent=$2 ORDER BY key", c.episode_id, c.agent)
    return db.rows_to_list(rows)


@router.get("/fe/episodes/{episode_id}/state/{agent}")
async def operator_state(episode_id: str, agent: str, _: None = Depends(bearer)):
    rows = await db.fetch("SELECT key, value, updated_at FROM agent_state WHERE episode_id=$1 AND agent=$2 ORDER BY key", episode_id, agent)
    return db.rows_to_list(rows)


# ---------- inputs inbox ----------


class InputCreate(BaseModel):
    episode_id: str
    target: str
    source: str = "frontend"
    payload: dict[str, Any] = Field(default_factory=dict)


INPUTS_ACTION = "inputs.post"


async def _audit_refusal(c: Caller, args: dict[str, Any], status: int, error: str) -> None:
    """Best effort, like the no-turn audit: the refusal stands even if the audit write fails."""
    try:
        await audit.record(c, INPUTS_ACTION, args, {"error": error}, status)
    except Exception:
        log.exception("inputs_audit_failed", agent=c.agent, episode_id=c.episode_id)


@router.post("/inputs", status_code=201)
async def post_input(body: InputCreate, c: Caller = Depends(caller)):
    """Agents may only leave messages inside the episode they are acting in (X-Episode), and every
    agent call is audited like any other agent write. The operator may address any episode."""
    args = {"episode_id": body.episode_id, "target": body.target, "payload": body.payload}
    if body.target not in ("red", "green", "blue"):
        if c.is_agent:
            await _audit_refusal(c, args, 422, "target must be red|green|blue")
        raise HTTPException(422, "target must be red|green|blue")
    if c.is_agent and body.episode_id != c.episode_id:
        await _audit_refusal(c, args, 403, "episode_id must match X-Episode")
        raise HTTPException(403, "episode_id must match X-Episode")
    source = c.agent or body.source
    row = await db.fetchrow(
        "INSERT INTO inputs (episode_id, target, source, payload) VALUES ($1,$2,$3,$4) RETURNING id", body.episode_id, body.target, source, body.payload
    )
    if c.is_agent:
        await audit.record(c, INPUTS_ACTION, args, {"id": row["id"]}, 201)
    return {"id": row["id"], "queued_for": f"{body.target}'s next turn"}


@router.get("/inputs")
async def list_inputs(episode_id: str, target: str | None = None, pending_only: bool = True, _: None = Depends(bearer)):
    rows = await db.fetch(
        "SELECT * FROM inputs WHERE episode_id=$1 AND ($2::text IS NULL OR target=$2) AND (NOT $3 OR consumed_day IS NULL) ORDER BY id",
        episode_id,
        target,
        pending_only,
    )
    return db.rows_to_list(rows)


# ---------- read-only SQL for the frontend ----------

_FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|vacuum|analyze|lock|call|do)\b", re.I)


class Query(BaseModel):
    sql: str
    params: list[Any] = Field(default_factory=list)
    limit: int = 1000


@router.post("/fe/query")
async def fe_query(q: Query, _: None = Depends(bearer)):
    sql = q.sql.strip().rstrip(";")
    if not sql.lower().startswith(("select", "with")) or _FORBIDDEN.search(sql) or ";" in sql:
        raise HTTPException(422, "read-only: a single SELECT/WITH statement")
    async with db.pool().acquire() as conn, conn.transaction(readonly=True):
        await conn.execute("SET LOCAL statement_timeout = '5s'")
        rows = await conn.fetch(f"SELECT * FROM ({sql}) _q LIMIT {max(1, min(q.limit, 5000))}", *q.params)
    return db.rows_to_list(rows)
