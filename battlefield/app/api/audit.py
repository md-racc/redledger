"""audit_log + ledger.mutation helper used by every write route. Owner: Dev Ad."""

from __future__ import annotations

from typing import Any

from .. import db
from ..auth import Caller
from ..events import bus


async def record(
    c: Caller, action: str, args: dict[str, Any], result: dict[str, Any], status: int, verdict_id: str | None = None, *, conn: Any | None = None
) -> None:
    """Write one audit_log row. Pass `conn` to write it inside the caller's transaction."""
    assert c.is_agent
    await (conn.execute if conn is not None else db.execute)(
        "INSERT INTO audit_log (episode_id, day, agent, action, tool_use_id, args, result, http_status, verdict_id) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)",
        c.episode_id,
        c.day,
        c.agent,
        action,
        c.tool_use_id,
        args,
        result,
        status,
        verdict_id,
    )


async def mutation(
    c: Caller,
    action: str,
    entity_type: str,
    entity_id: str,
    amount: float | None = None,
    verdict_id: str | None = None,
    *,
    preparation_id: str | None = None,
) -> None:
    assert c.is_agent and c.episode_id is not None and c.day is not None
    payload = {"agent": c.agent, "action": action, "entity_type": entity_type, "entity_id": entity_id, "amount": amount, "verdict_id": verdict_id}
    if preparation_id is not None:  # the execution consumed a preparation (contracts/events.md)
        payload["preparation_id"] = preparation_id
    await bus.emit(c.episode_id, c.day, "ledger.mutation", payload, agent=c.agent)
