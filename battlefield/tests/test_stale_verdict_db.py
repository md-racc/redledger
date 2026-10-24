"""DB: a gate verdict replays only on the day and under the enforcement it was judged in.

contracts/agent-service.md: the same key on the same action on a later day, or after the controller
mode changed between shadow and enforce, is refused (409 "stale verdict"), audited, and never
replayed. Same-day, same-mode retries replay exactly as before; a different action is still the
idempotency-key conflict.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
import pytest

from app import db
from app.auth import Caller
from app.config import settings
from app.gate import gatekeeper as gate
from app.main import app
from tests import factories as f

pytestmark = pytest.mark.usefixtures("pg")


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bf", timeout=30)


def _key() -> str:
    return f"tu_{uuid.uuid4().hex}"


def _green(episode: str, key: str, day: int = 1) -> dict[str, str]:
    return f.auth("green", episode=episode, day=day, tool_use_id=key)


def _caller(episode: str, key: str, day: int = 1) -> Caller:
    return Caller(agent="green", episode_id=episode, day=day, tool_use_id=key)


async def _episode(mode: str) -> str:
    eid = f.uid("ep")
    await db.execute("INSERT INTO episodes (id, seed, controller_mode) VALUES ($1, 42, $2)", eid, mode)
    return eid


async def _set_mode(episode: str, mode: str) -> None:
    await db.execute("UPDATE episodes SET controller_mode=$2 WHERE id=$1", episode, mode)


async def _audit(episode: str, key: str) -> list[dict[str, Any]]:
    rows = await db.fetch("SELECT action, http_status, result, verdict_id FROM audit_log WHERE episode_id=$1 AND tool_use_id=$2 ORDER BY id", episode, key)
    return [dict(r) for r in rows]


@pytest.fixture
def blue(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stand-in for POST blue/gate: answers state['verdict'] and records every call."""
    state: dict[str, Any] = {"verdict": "block", "asked": []}

    async def ask(c: Caller, mode: str, action: str, et: str | None, eid: str | None, amount: float | None, args: dict, context: dict, **kw: Any):
        state["asked"].append({"key": c.tool_use_id, "action": action, "mode": mode, "day": c.day})
        return state["verdict"], f"stand-in says {state['verdict']}", 0.9, ["near_threshold"]

    monkeypatch.setattr(gate, "_ask_blue", ask)
    return state


@pytest.fixture
def short_hold(monkeypatch: pytest.MonkeyPatch) -> float:
    monkeypatch.setattr(settings, "escalation_timeout_sec", 5)
    return 5.0


# ---------- 1: same day, same mode replays as before ----------


@pytest.mark.parametrize(("mode", "verdict"), [("shadow", "block"), ("enforce", "allow"), ("enforce", "block")])
async def test_same_day_same_mode_replays_the_verdict(blue: dict[str, Any], mode: str, verdict: str) -> None:
    ep = await _episode(mode)
    inv = await f.invoice(ep, await f.vendor(ep), amount=100.0)
    key = _key()
    blue["verdict"] = verdict
    outcomes = []
    for _ in range(2):
        try:
            d = await gate.check(_caller(ep, key), action="invoices.approve", entity_type="invoice", entity_id=inv, amount=100.0)
            outcomes.append(("allowed", d.verdict_id, d.verdict, d.enforced))
        except gate.GateBlockedError as e:
            outcomes.append(("blocked", e.verdict_id, "block", True))
    assert outcomes[0] == outcomes[1]
    expected = "blocked" if (mode, verdict) == ("enforce", "block") else "allowed"
    assert outcomes[0][0] == expected and outcomes[0][2] == verdict
    assert len(blue["asked"]) == 1  # replayed, blue not re-asked


async def test_same_day_same_mode_route_retry_replays_the_403(blue: dict[str, Any]) -> None:
    ep = await _episode("enforce")
    inv = await f.invoice(ep, await f.vendor(ep), amount=100.0)
    key = _key()
    async with _client() as cl:
        first = await cl.post(f"/api/invoices/{inv}/reject", json={"reason": "dup"}, headers=_green(ep, key))
        again = await cl.post(f"/api/invoices/{inv}/reject", json={"reason": "dup"}, headers=_green(ep, key))
    assert first.status_code == again.status_code == 403
    assert first.json()["verdict_id"] == again.json()["verdict_id"]
    assert len(blue["asked"]) == 1


# ---------- 2: shadow block, then enforce ----------


async def test_shadow_block_replayed_under_enforce_is_stale_not_403(blue: dict[str, Any]) -> None:
    ep = await _episode("shadow")
    inv = await f.invoice(ep, await f.vendor(ep), amount=100.0)
    key = _key()
    shadow = await gate.check(_caller(ep, key), action="invoices.approve", entity_type="invoice", entity_id=inv, amount=100.0)
    assert shadow.allowed and shadow.verdict == "block" and not shadow.enforced

    await _set_mode(ep, "enforce")
    with pytest.raises(gate.StaleVerdictError) as exc:
        await gate.check(_caller(ep, key), action="invoices.approve", entity_type="invoice", entity_id=inv, amount=100.0)
    assert exc.value.error == "stale verdict" and exc.value.verdict_id == shadow.verdict_id and exc.value.detail == "mode changed"

    async with _client() as cl:
        r = await cl.post(f"/api/invoices/{inv}/approve", headers=_green(ep, key))
    assert r.status_code == 409  # never the shadow block turned into an enforced 403
    assert r.json() == {"error": "stale verdict", "verdict_id": shadow.verdict_id}
    assert await db.fetchval("SELECT status FROM invoices WHERE id=$1", inv) == "pending"  # not marked blocked
    (row,) = await _audit(ep, key)
    assert row["action"] == "invoices.approve" and row["http_status"] == 409
    assert row["result"] == {"error": "stale verdict", "verdict_id": shadow.verdict_id}
    assert len(blue["asked"]) == 1  # blue not re-asked
    assert await db.fetchval("SELECT count(*) FROM verdicts WHERE episode_id=$1", ep) == 1


async def test_enforce_verdict_replayed_under_shadow_is_stale(blue: dict[str, Any]) -> None:
    ep = await _episode("enforce")
    inv = await f.invoice(ep, await f.vendor(ep), amount=100.0)
    key = _key()
    with pytest.raises(gate.GateBlockedError):
        await gate.check(_caller(ep, key), action="invoices.approve", entity_type="invoice", entity_id=inv, amount=100.0)
    await _set_mode(ep, "shadow")
    with pytest.raises(gate.StaleVerdictError):
        await gate.check(_caller(ep, key), action="invoices.approve", entity_type="invoice", entity_id=inv, amount=100.0)
    assert len(blue["asked"]) == 1


async def test_preparation_does_not_reuse_a_stale_inline_verdict(blue: dict[str, Any]) -> None:
    ep = await _episode("shadow")
    inv = await f.invoice(ep, await f.vendor(ep), amount=100.0)
    key = _key()
    await gate.check(_caller(ep, key), action="invoices.approve", entity_type="invoice", entity_id=inv, amount=100.0)
    await _set_mode(ep, "enforce")
    async with _client() as cl:
        r = await cl.post("/api/preparations", json={"action": "invoices.approve", "entity_id": inv, "args": {}}, headers=_green(ep, key))
    assert r.status_code == 409 and r.json()["error"] == "stale verdict"
    assert await db.fetchval("SELECT count(*) FROM preparations WHERE episode_id=$1", ep) == 0
    assert await db.fetchval("SELECT status FROM invoices WHERE id=$1", inv) == "pending"
    assert [a["http_status"] for a in await _audit(ep, key)] == [409]
    assert len(blue["asked"]) == 1


# ---------- 3: an escalation decision does not carry over to another day ----------


async def test_escalation_approved_on_day_d_is_stale_on_day_d_plus_1(blue: dict[str, Any], short_hold: float) -> None:
    ep = await _episode("enforce")
    inv = await f.invoice(ep, await f.vendor(ep), amount=4_900.0)
    key = _key()
    blue["verdict"] = "escalate"
    held = asyncio.create_task(gate.check(_caller(ep, key, day=3), action="invoices.approve", entity_type="invoice", entity_id=inv, amount=4_900.0))
    esc_id = None
    for _ in range(250):
        esc_id = await db.fetchval("SELECT id FROM escalations WHERE episode_id=$1 AND status='open'", ep)
        if esc_id:
            break
        await asyncio.sleep(0.02)
    assert esc_id is not None
    assert await gate.resolve_escalation(esc_id, "approve", "judge")
    first = await held
    assert first.allowed and first.verdict == "escalate"

    # same day: the human's approval is reused, no second escalation
    same_day = await gate.check(_caller(ep, key, day=3), action="invoices.approve", entity_type="invoice", entity_id=inv, amount=4_900.0)
    assert same_day.allowed and same_day.verdict_id == first.verdict_id

    # next day: refused, never replayed
    with pytest.raises(gate.StaleVerdictError) as exc:
        await gate.check(_caller(ep, key, day=4), action="invoices.approve", entity_type="invoice", entity_id=inv, amount=4_900.0)
    assert exc.value.detail == "day changed" and exc.value.verdict_id == first.verdict_id
    async with _client() as cl:
        r = await cl.post(f"/api/invoices/{inv}/approve", headers=_green(ep, key, day=4))
    assert r.status_code == 409 and r.json() == {"error": "stale verdict", "verdict_id": first.verdict_id}
    assert await db.fetchval("SELECT status FROM invoices WHERE id=$1", inv) == "pending"
    assert [(a["http_status"], a["result"]["verdict_id"]) for a in await _audit(ep, key)] == [(409, first.verdict_id)]
    assert await db.fetchval("SELECT count(*) FROM escalations WHERE episode_id=$1", ep) == 1
    assert len(blue["asked"]) == 1


# ---------- 4: a different action under the key is still the idempotency conflict ----------


@pytest.mark.parametrize("day", [1, 2])
async def test_different_action_reuse_is_still_the_idempotency_conflict(blue: dict[str, Any], day: int) -> None:
    ep = await _episode("enforce")
    vid = await f.vendor(ep)
    inv, other = await f.invoice(ep, vid, amount=100.0), await f.invoice(ep, vid, amount=200.0)
    key = _key()
    blue["verdict"] = "allow"
    async with _client() as cl:
        ok = await cl.post(f"/api/invoices/{inv}/approve", headers=_green(ep, key))
        reused = await cl.post(f"/api/invoices/{other}/approve", headers=_green(ep, key, day=day))
    assert ok.status_code == 200
    assert reused.status_code == 409 and reused.json()["error"] == "idempotency key reused for a different action"
    with pytest.raises(gate.IdempotencyConflictError) as exc:
        await gate.check(_caller(ep, key, day=day), action="invoices.approve", entity_type="invoice", entity_id=other, amount=200.0)
    assert not isinstance(exc.value, gate.StaleVerdictError)
    assert await db.fetchval("SELECT status FROM invoices WHERE id=$1", other) == "pending"
    assert len(blue["asked"]) == 1
