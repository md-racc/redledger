"""Gatekeeper: the enforcement point. Owner: Dev Ad (logic) / Dev Al (verdict semantics with blue).

Every gated green route calls `check()` before mutating. check():
  1. reads the episode's controller_mode
  2. off      → returns Allow with no verdict recorded
  3. assembles context for blue, calls POST blue/gate with the idempotency key (X-Tool-Use-Id)
  4. persists the verdict, emits gate.verdict
  5. shadow   → records enforced=false and returns Allow regardless of verdict
  6. enforce  → allow → Allow; block → raises GateBlockedError (403);
                escalate → opens escalation, waits for human up to ESCALATION_TIMEOUT_SEC,
                timeout = block
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import structlog

from .. import db
from ..auth import Caller
from ..config import settings
from ..events import bus

log = structlog.get_logger(__name__)

_escalation_waiters: dict[str, asyncio.Future] = {}


IDEMPOTENCY_CONFLICT = "idempotency key reused for a different action"


class IdempotencyConflictError(Exception):
    """The X-Tool-Use-Id already has a verdict for a different action/entity/amount. Replaying that
    verdict would let one approval authorize another action, so the request is refused (409)."""

    def __init__(self, verdict_id: str):
        super().__init__(IDEMPOTENCY_CONFLICT)
        self.verdict_id = verdict_id


class GateBlockedError(Exception):
    def __init__(self, reason: str, verdict_id: str, escalation_id: str | None = None):
        super().__init__(reason)
        self.reason = reason
        self.verdict_id = verdict_id
        self.escalation_id = escalation_id


@dataclass
class Decision:
    allowed: bool
    verdict_id: str | None = None
    verdict: str = "allow"
    reason: str = ""
    enforced: bool = False
    rules_fired: list[str] = field(default_factory=list)


async def controller_mode(episode_id: str) -> str:
    return await db.fetchval("SELECT controller_mode FROM episodes WHERE id=$1", episode_id) or "off"


async def check(
    c: Caller,
    *,
    action: str,
    entity_type: str | None,
    entity_id: str | None,
    amount: float | None,
    args: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> Decision:
    assert c.is_agent and c.episode_id is not None and c.day is not None and c.tool_use_id
    mode = await controller_mode(c.episode_id)
    if mode == "off":
        return Decision(allowed=True)

    # idempotent on key: if we already judged this tool_use_id for this same action, reuse the verdict;
    # the same key on a different action is refused, never replayed
    existing = await db.fetchrow("SELECT * FROM verdicts WHERE episode_id=$1 AND idempotency_key=$2", c.episode_id, c.tool_use_id)
    if existing:
        if not same_action(existing, action, entity_type, entity_id, amount, args or {}):
            log.warning("idempotency_key_reused", key=c.tool_use_id, verdict_id=existing["id"], stored_action=existing["action"], action=action)
            raise IdempotencyConflictError(existing["id"])
        return await _apply(existing["id"], existing["verdict"], existing["reason"], mode, c, action, entity_type, entity_id, amount, replay=True)

    t0 = time.monotonic()
    verdict, reason, confidence, rules = await _ask_blue(c, mode, action, entity_type, entity_id, amount, args or {}, context or {})
    latency_ms = int((time.monotonic() - t0) * 1000)

    vid = db.new_id("vd")
    await db.execute(
        "INSERT INTO verdicts (id, episode_id, idempotency_key, day, agent, action, entity_type, entity_id, amount, args, verdict, reason, confidence, rules_fired, enforced, latency_ms) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)",
        vid,
        c.episode_id,
        c.tool_use_id,
        c.day,
        c.agent,
        action,
        entity_type,
        entity_id,
        amount,
        args or {},
        verdict,
        reason,
        confidence,
        rules,
        mode == "enforce",
        latency_ms,
    )
    await bus.emit(
        c.episode_id,
        c.day,
        "gate.verdict",
        {
            "verdict_id": vid,
            "agent": c.agent,
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "amount": amount,
            "verdict": verdict,
            "reason": reason,
            "confidence": confidence,
            "rules_fired": rules,
            "enforced": mode == "enforce",
        },
        agent="blue",
    )
    return await _apply(vid, verdict, reason, mode, c, action, entity_type, entity_id, amount)


def same_action(existing: Any, action: str, entity_type: str | None, entity_id: str | None, amount: float | None, args: dict[str, Any]) -> bool:
    """Is a stored verdict about the same action as this request? Action and entity must match and the
    amount must not differ by a cent or more. A GL entry has no id until it is posted (each attempt
    mints one), so for those the posted fields (args) stand in for the entity."""
    if existing["action"] != action or existing["entity_type"] != entity_type:
        return False
    if entity_type == "gl_entry":
        if dict(existing["args"] or {}) != dict(args):
            return False
    elif existing["entity_id"] != entity_id:
        return False
    stored = existing["amount"]
    if (stored is None) != (amount is None):
        return False
    return stored is None or abs(float(stored) - float(amount)) < 0.01  # type: ignore[arg-type]


async def _ask_blue(
    c: Caller, mode: str, action: str, et: str | None, eid: str | None, amount: float | None, args: dict, context: dict
) -> tuple[str, str, float | None, list[str]]:
    body = {
        "idempotency_key": c.tool_use_id,
        "episode_id": c.episode_id,
        "day": c.day,
        "controller_mode": mode,
        "agent": c.agent,
        "action": action,
        "entity_type": et,
        "entity_id": eid,
        "amount": amount,
        "args": args,
        "context": context,
    }
    try:
        async with httpx.AsyncClient(timeout=settings.gate_timeout_sec) as client:
            r = await client.post(f"{settings.blue_url}/gate", json=body, headers={"Authorization": f"Bearer {settings.agent_token}"})
            r.raise_for_status()
            j = r.json()
            return j["verdict"], j.get("reason", ""), j.get("confidence"), list(j.get("rules_fired", []))
    except Exception as e:
        log.warning("blue_gate_unavailable", error=str(e), action=action)
        fallback = "allow" if mode == "shadow" else "escalate"
        return fallback, f"controller unavailable ({type(e).__name__}); defaulted to {fallback}", None, ["gate_timeout"]


async def _apply(
    vid: str, verdict: str, reason: str, mode: str, c: Caller, action: str, et: str | None, eid: str | None, amount: float | None, *, replay: bool = False
) -> Decision:
    if mode == "shadow":
        return Decision(allowed=True, verdict_id=vid, verdict=verdict, reason=reason, enforced=False)
    if verdict == "allow":
        return Decision(allowed=True, verdict_id=vid, verdict=verdict, reason=reason, enforced=True)
    if verdict == "block":
        raise GateBlockedError(reason, vid)
    # escalate
    decision = await _escalate(vid, c, action, et, eid, amount, reason)
    if decision == "approve":
        return Decision(allowed=True, verdict_id=vid, verdict="escalate", reason="escalated; human approved", enforced=True)
    raise GateBlockedError(f"escalated; {decision}", vid)


async def _escalate(vid: str, c: Caller, action: str, et: str | None, eid: str | None, amount: float | None, reason: str) -> str:
    assert c.episode_id is not None and c.day is not None
    esc_id = db.new_id("esc")
    expires = datetime.now(UTC) + timedelta(seconds=settings.escalation_timeout_sec)
    await db.execute("INSERT INTO escalations (id, episode_id, verdict_id, expires_at) VALUES ($1,$2,$3,$4)", esc_id, c.episode_id, vid, expires)
    fut: asyncio.Future = asyncio.get_running_loop().create_future()
    _escalation_waiters[esc_id] = fut
    await bus.emit(
        c.episode_id,
        c.day,
        "escalation.opened",
        {
            "escalation_id": esc_id,
            "verdict_id": vid,
            "action": action,
            "entity_type": et,
            "entity_id": eid,
            "amount": amount,
            "reason": reason,
            "expires_at": expires.isoformat(),
        },
    )
    try:
        decision = await asyncio.wait_for(fut, timeout=settings.escalation_timeout_sec)
    except TimeoutError:
        decision = "timeout"
        await db.execute("UPDATE escalations SET status='timeout', resolved_at=now() WHERE id=$1", esc_id)
        await bus.emit(c.episode_id, c.day, "escalation.resolved", {"escalation_id": esc_id, "decision": "timeout", "by": "system"})
    finally:
        _escalation_waiters.pop(esc_id, None)
    return decision


async def resolve_escalation(esc_id: str, decision: str, by: str) -> bool:
    """Called by the control-plane route. Returns False if already resolved."""
    row = await db.fetchrow("SELECT * FROM escalations WHERE id=$1", esc_id)
    if not row or row["status"] != "open":
        return False
    status = "approved" if decision == "approve" else "blocked"
    await db.execute("UPDATE escalations SET status=$2, resolved_by=$3, resolved_at=now() WHERE id=$1", esc_id, status, by)
    v = await db.fetchrow("SELECT episode_id, day FROM verdicts WHERE id=$1", row["verdict_id"])
    await bus.emit(v["episode_id"], v["day"], "escalation.resolved", {"escalation_id": esc_id, "decision": decision, "by": by}, agent="human")
    fut = _escalation_waiters.get(esc_id)
    if fut and not fut.done():
        fut.set_result(decision)
    return True
