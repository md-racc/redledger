"""Gatekeeper: the enforcement point. Owner: Dev Ad (logic) / Dev Al (verdict semantics with blue).

Every gated green route calls `check()` before mutating. check():
  1. reads the episode's controller_mode
  2. off      → returns Allow with no verdict recorded
  3. assembles context for blue, calls POST blue/gate with the idempotency key (X-Tool-Use-Id)
  4. persists the verdict, emits gate.verdict
  5. shadow   → records enforced=false and returns Allow regardless of verdict
  6. enforce  → allow → Allow; block → raises GateBlockedError (403);
                escalate → opens escalation, waits for human up to ESCALATION_TIMEOUT_SEC,
                timeout = block (a headless lineage generation waits its config's
                headless.escalation_timeout_sec instead: nobody is watching)

Same-key requests are single-flight: they run one at a time, so a key gets one verdict and at most
one escalation; the later ones replay the first's outcome. Without the lock (the backstop for
concurrent first uses that bypass it), the verdict INSERT ... ON CONFLICT picks one winner and a
loser of an escalate verdict waits for the winner's escalation row and joins it.
Escalations close exactly once (compare-and-set on status='open': resolver, timeout or orphan sweep).
A replay of an escalated key joins that escalation or reuses its decision. The waiter lives in this
process, so an escalation left open by a restart is an orphan: resolving it is a 409 and times it out.
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
_key_slots: dict[tuple[str, str], list[Any]] = {}  # (episode_id, idempotency key) -> [Lock, users]


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


async def _lineage(episode_id: str) -> Any:
    return await db.fetchrow("SELECT l.id, l.status, l.config FROM episodes e JOIN lineages l ON l.id = e.lineage_id WHERE e.id=$1", episode_id)


async def escalation_timeout_sec(episode_id: str) -> float:
    """ESCALATION_TIMEOUT_SEC, or the lineage's headless.escalation_timeout_sec for a generation its runner
    owns. A demo episode needs a finished/failed lineage (POST /episodes {lineage_id}), so a lineage that is
    running or paused can only be gating its runner's own, headless generation."""
    ln = await _lineage(episode_id)
    headless = (ln["config"] or {}).get("headless") if ln and ln["status"] in ("running", "paused") else None
    if headless:  # escalation_policy is always "block" (contract enum): timeout = block, as today
        return min(float(headless.get("escalation_timeout_sec", 5)), float(settings.escalation_timeout_sec))
    return float(settings.escalation_timeout_sec)


async def blue_playbook_version(episode_id: str) -> int | None:
    """Blue's latest playbook version in the episode's lineage (0 before any write); None outside lineages."""
    ln = await _lineage(episode_id)
    if ln is None:
        return None
    return int(await db.fetchval("SELECT COALESCE(MAX(version), 0) FROM playbooks WHERE lineage_id=$1 AND agent='blue'", ln["id"]))


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
    # Single flight per key: concurrent requests with one X-Tool-Use-Id (parallel Droid tool calls, a
    # retry racing the original) run one at a time, the first through to its outcome, including any
    # escalation hold. The others then replay that verdict (and join/reuse its escalation), so one key
    # gets one verdict, one escalation card and one human decision. Battlefield is one process.
    slot_key = (c.episode_id, c.tool_use_id)
    slot = _key_slots.setdefault(slot_key, [asyncio.Lock(), 0])
    slot[1] += 1  # holders + waiters; dropped when nobody can still need it (also on cancel)
    try:
        async with slot[0]:
            return await _check(c, mode, action, entity_type, entity_id, amount, args, context)
    finally:
        slot[1] -= 1
        if slot[1] == 0:
            del _key_slots[slot_key]


async def _check(
    c: Caller,
    mode: str,
    action: str,
    entity_type: str | None,
    entity_id: str | None,
    amount: float | None,
    args: dict[str, Any] | None,
    context: dict[str, Any] | None,
) -> Decision:
    assert c.episode_id is not None and c.day is not None
    # idempotent on key: if we already judged this tool_use_id for this same action, reuse the verdict;
    # the same key on a different action is refused, never replayed
    existing = await db.fetchrow("SELECT * FROM verdicts WHERE episode_id=$1 AND idempotency_key=$2", c.episode_id, c.tool_use_id)
    if existing:
        return await _replay(existing, mode, c, action, entity_type, entity_id, amount, args or {})

    # blue caches learned rules by playbook version; the field exists only in lineage episodes
    version = await blue_playbook_version(c.episode_id)
    lineage_fields = {} if version is None else {"playbook_version": version}
    t0 = time.monotonic()
    verdict, reason, confidence, rules = await _ask_blue(c, mode, action, entity_type, entity_id, amount, args or {}, context or {}, **lineage_fields)
    latency_ms = int((time.monotonic() - t0) * 1000)

    # Race-safe: two requests that both saw no verdict for this key both asked blue; only the first
    # INSERT wins. The loser persists and emits nothing and is treated exactly like a later request:
    # replay the winner's verdict for the same action, 409 for a different one.
    vid = await db.fetchval(
        "INSERT INTO verdicts (id, episode_id, idempotency_key, day, agent, action, entity_type, entity_id, amount, args, verdict, reason, confidence, rules_fired, enforced, latency_ms) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16) "
        "ON CONFLICT (episode_id, idempotency_key) DO NOTHING RETURNING id",
        db.new_id("vd"),
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
    if vid is None:
        winner = await db.fetchrow("SELECT * FROM verdicts WHERE episode_id=$1 AND idempotency_key=$2", c.episode_id, c.tool_use_id)
        assert winner is not None  # verdicts are never deleted while the episode exists
        log.info("verdict_insert_lost_race", key=c.tool_use_id, verdict_id=winner["id"], action=action)
        if winner["verdict"] == "escalate" and mode == "enforce":
            # The winner opens its escalation right after its insert; wait for that row so the replay
            # joins it instead of opening a second card for the same key.
            await _await_escalation_row(winner["id"])
        return await _replay(winner, mode, c, action, entity_type, entity_id, amount, args or {})
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


# How long a request that lost the verdict-insert race waits for the winner's escalation row.
_LOST_RACE_ESCALATION_WAIT_SEC = 2.0


async def _await_escalation_row(vid: str) -> None:
    deadline = time.monotonic() + _LOST_RACE_ESCALATION_WAIT_SEC
    while time.monotonic() < deadline:
        if await db.fetchval("SELECT 1 FROM escalations WHERE verdict_id=$1 LIMIT 1", vid):
            return
        await asyncio.sleep(0.02)


async def _replay(
    existing: Any, mode: str, c: Caller, action: str, entity_type: str | None, entity_id: str | None, amount: float | None, args: dict[str, Any]
) -> Decision:
    """A verdict already exists for this key: replay it for the same action, refuse a different one."""
    if not same_action(existing, action, entity_type, entity_id, amount, args):
        log.warning("idempotency_key_reused", key=c.tool_use_id, verdict_id=existing["id"], stored_action=existing["action"], action=action)
        raise IdempotencyConflictError(existing["id"])
    return await _apply(existing["id"], existing["verdict"], existing["reason"], mode, c, action, entity_type, entity_id, amount, replay=True)


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
    c: Caller,
    mode: str,
    action: str,
    et: str | None,
    eid: str | None,
    amount: float | None,
    args: dict,
    context: dict,
    *,
    playbook_version: int | None = None,
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
    if playbook_version is not None:
        body["playbook_version"] = playbook_version
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
    # escalate. A replay of an escalated key (a retry, or a parallel call with the same key) gets the
    # same human decision: it joins the open escalation or reuses the finished one, never a second card.
    joined = await _join_escalation(vid) if replay else None
    esc_id, decision = joined if joined is not None else await _escalate(vid, c, action, et, eid, amount, reason)
    if decision == "approve":
        return Decision(allowed=True, verdict_id=vid, verdict="escalate", reason="escalated; human approved", enforced=True)
    raise GateBlockedError(f"escalated; {decision}", vid, esc_id)


# escalations.status <-> escalation.resolved decision
_STATUS = {"approve": "approved", "block": "blocked", "timeout": "timeout"}
_DECISION = {v: k for k, v in _STATUS.items()}


async def _close(esc_id: str, decision: str, by: str) -> bool:
    """Compare-and-set an open escalation to its final status and emit escalation.resolved. Exactly one
    caller (a resolver, the timeout, the orphan sweep) can win it; the losers get False."""
    row = await db.fetchrow(
        "UPDATE escalations SET status=$2, resolved_by=$3, resolved_at=now() WHERE id=$1 AND status='open' RETURNING episode_id, verdict_id",
        esc_id,
        _STATUS[decision],
        None if decision == "timeout" else by,
    )
    if row is None:
        return False
    day = await db.fetchval("SELECT day FROM verdicts WHERE id=$1", row["verdict_id"])
    payload = {"escalation_id": esc_id, "decision": decision, "by": by}
    if decision == "timeout":
        await bus.emit(row["episode_id"], day, "escalation.resolved", payload)
    else:
        await bus.emit(row["episode_id"], day, "escalation.resolved", payload, agent="human")
    return True


async def _final_decision(esc_id: str) -> str:
    return _DECISION.get(await db.fetchval("SELECT status FROM escalations WHERE id=$1", esc_id), "timeout")


async def _escalate(vid: str, c: Caller, action: str, et: str | None, eid: str | None, amount: float | None, reason: str) -> tuple[str, str]:
    assert c.episode_id is not None and c.day is not None
    esc_id = db.new_id("esc")
    hold = await escalation_timeout_sec(c.episode_id)
    expires = datetime.now(UTC) + timedelta(seconds=hold)
    # Registered before the row exists, so an open row with no waiter in this process is always an
    # orphan (battlefield restarted mid-hold): see resolve_escalation / expire_orphaned_escalations.
    fut: asyncio.Future = asyncio.get_running_loop().create_future()
    _escalation_waiters[esc_id] = fut
    try:
        await db.execute("INSERT INTO escalations (id, episode_id, verdict_id, expires_at) VALUES ($1,$2,$3,$4)", esc_id, c.episode_id, vid, expires)
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
            # shielded: the future outlives our timeout, so a joiner awaiting it is never cancelled
            decision = await asyncio.wait_for(asyncio.shield(fut), timeout=hold)
        except TimeoutError:
            # A resolver may have won the row between the deadline and here; then its decision stands.
            decision = "timeout" if await _close(esc_id, "timeout", "system") else await _final_decision(esc_id)
            if not fut.done():
                fut.set_result(decision)
    finally:
        _escalation_waiters.pop(esc_id, None)
        if not fut.done():
            fut.cancel()  # we were cancelled ourselves; release any joiner
    return esc_id, decision


async def _join_escalation(vid: str) -> tuple[str, str] | None:
    """For a replayed escalate verdict: the latest escalation of that verdict and its decision, waiting
    for it while another request holds it open. None when there is none to join (never opened, or an
    orphan left open by a restart, which is expired here): the caller opens a fresh one."""
    esc = await db.fetchrow("SELECT id, status FROM escalations WHERE verdict_id=$1 ORDER BY opened_at DESC, id DESC LIMIT 1", vid)
    if esc is None:
        return None
    if esc["status"] != "open":
        return esc["id"], _DECISION[esc["status"]]
    fut = _escalation_waiters.get(esc["id"])
    if fut is None:
        await _close(esc["id"], "timeout", "system")
        return None
    try:
        return esc["id"], await asyncio.shield(fut)
    except asyncio.CancelledError:
        if not fut.cancelled():
            raise  # we were cancelled, not the holder
        return esc["id"], await _final_decision(esc["id"])  # the holder was cancelled: still open = timeout


async def resolve_escalation(esc_id: str, decision: str, by: str) -> bool:
    """Called by the control-plane route. False (-> 409) if the escalation is unknown, already resolved,
    or has no request waiting on it in this process (an orphan from a restart: expired here as a
    timeout, since the held request is gone and the decision could never take effect)."""
    fut = _escalation_waiters.get(esc_id)
    if fut is None:
        await _close(esc_id, "timeout", "system")
        return False
    if not await _close(esc_id, decision, by):
        return False
    if not fut.done():
        fut.set_result(decision)
    return True


async def expire_orphaned_escalations() -> int:
    """Time out every open escalation no request in this process is waiting on (battlefield restarted
    mid-hold: the held HTTP request died with the old process). Meant for startup; returns the count."""
    rows = await db.fetch("SELECT id FROM escalations WHERE status='open'")
    n = 0
    for r in rows:
        if r["id"] not in _escalation_waiters and await _close(r["id"], "timeout", "system"):
            n += 1
    if n:
        log.warning("orphaned_escalations_expired", count=n)
    return n
