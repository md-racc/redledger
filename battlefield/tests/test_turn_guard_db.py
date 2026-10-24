"""DB: agent writes are accepted only during that agent's active turn (app/turns.py)."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
import pytest

from app import db, turns
from app.auth import Caller
from app.config import settings
from app.gate import gatekeeper as gate
from app.main import app
from app.orchestrator import agents, runner
from seed.company import seed_episode
from tests import factories as f

pytestmark = pytest.mark.usefixtures("pg", "turn_guard")

NO_TURN = {"error": "no active turn for this agent"}


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bf", timeout=30)


def _h(agent: str, episode: str, day: int = 1) -> dict[str, str]:
    return f.auth(agent, episode=episode, day=day, tool_use_id=f"tu_{uuid.uuid4().hex}")


ATTACK = {"scheme_id": "ghost_vendor", "display_name": "Ghost", "story": "s", "target_amount": 100.0}


async def test_orphaned_writes_after_restart_are_409_audited_and_write_nothing(episode: str) -> None:
    """After a restart nothing is active: a red turn still running in its container can't write."""
    vid = await f.vendor(episode)
    inv = await f.invoice(episode, vid, amount=100.0)
    async with _client() as cl:
        r = await cl.post("/api/attacks", json=ATTACK, headers=_h("red", episode))
        g = await cl.post(f"/api/invoices/{inv}/approve", headers=_h("green", episode))
        e = await cl.post("/api/events", json=[{"type": "agent.thinking", "payload": {"text": "x"}}], headers=_h("red", episode))
        s = await cl.put("/api/state/k", json={"v": 1}, headers=_h("blue", episode))
        reads = await cl.get("/api/invoices", headers=f.auth("green", episode=episode, day=1))
    for resp in (r, g, e, s):
        assert resp.status_code == 409 and resp.json() == NO_TURN
    assert reads.status_code == 200  # reads stay allowed
    assert await db.fetchval("SELECT COUNT(*) FROM attacks WHERE episode_id=$1", episode) == 0
    assert await db.fetchval("SELECT status FROM invoices WHERE id=$1", inv) == "pending"
    assert await db.fetchval("SELECT COUNT(*) FROM events WHERE episode_id=$1 AND type='agent.thinking'", episode) == 0
    assert await db.fetchval("SELECT COUNT(*) FROM agent_state WHERE episode_id=$1", episode) == 0
    rows = await db.fetch("SELECT agent, action, http_status, result FROM audit_log WHERE episode_id=$1 ORDER BY id", episode)
    assert [(x["agent"], x["action"], x["http_status"]) for x in rows] == [
        ("red", "POST /attacks", 409),
        ("green", "POST /invoices/{invoice_id}/approve", 409),
        ("red", "POST /events", 409),
        ("blue", "PUT /state/{key}", 409),
    ]
    assert all(x["result"] == NO_TURN for x in rows)


async def test_only_the_active_agent_and_day_may_write(episode: str) -> None:
    async with _client() as cl:
        with turns.turn(episode, "red", 1):
            ok = await cl.post("/api/attacks", json=ATTACK, headers=_h("red", episode, day=1))
            wrong_day = await cl.post("/api/attacks", json=ATTACK, headers=_h("red", episode, day=2))
            wrong_agent = await cl.put("/api/state/k", json={"v": 1}, headers=_h("green", episode, day=1))
            other_ep = await cl.post("/api/attacks", json=ATTACK, headers=_h("red", f.uid("ep"), day=1))
        after = await cl.post("/api/attacks", json=ATTACK, headers=_h("red", episode, day=1))
        operator = await cl.post("/api/inputs", json={"episode_id": episode, "target": "red", "payload": {}}, headers=f.auth())
    assert ok.status_code == 201
    assert [x.status_code for x in (wrong_day, wrong_agent, other_ep, after)] == [409, 409, 409, 409]
    assert operator.status_code == 201  # the operator is not an agent: no turn needed
    assert turns.active(episode) is None


async def test_held_escalation_finishes_after_the_turn_is_given_up(episode: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """A gated write admitted during the turn completes even if battlefield stops waiting on the turn."""
    monkeypatch.setattr(settings, "escalation_timeout_sec", 5)

    async def ask(c: Caller, mode: str, action: str, et: str | None, eid: str | None, amount: float | None, args: dict, context: dict):
        return "escalate", "review", 0.9, ["t"]

    monkeypatch.setattr(gate, "_ask_blue", ask)
    vid = await f.vendor(episode)
    inv = await f.invoice(episode, vid, amount=100.0)
    async with _client() as cl:
        with turns.turn(episode, "green", 1):
            held = asyncio.create_task(cl.post(f"/api/invoices/{inv}/approve", headers=_h("green", episode)))
            for _ in range(250):
                esc = await db.fetchval("SELECT id FROM escalations WHERE episode_id=$1", episode)
                if esc:
                    break
                await asyncio.sleep(0.02)
        assert turns.active(episode) is None and not held.done()
        assert (await cl.post(f"/api/escalations/{esc}/resolve", json={"decision": "approve"}, headers=f.auth())).status_code == 200
        resp = await held
    assert resp.status_code == 200 and await db.fetchval("SELECT status FROM invoices WHERE id=$1", inv) == "approved"


async def test_step_mode_marks_the_turn_active_for_agent_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Agents writing through the API during a stepped day (what DRY_RUN and mock agents do) are accepted."""
    eid = f.uid("ep")
    await db.execute("INSERT INTO episodes (id, seed, controller_mode, days) VALUES ($1, 7, 'shadow', 1)", eid)
    await seed_episode(eid, 7)
    results: dict[str, int] = {}

    async def turn(agent: str, episode_id: str, day: int, mode: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        async with _client() as cl:
            if agent == "red":
                results["red"] = (await cl.post("/api/attacks", json=ATTACK, headers=_h("red", episode_id, day))).status_code
            else:
                results[agent] = (await cl.put("/api/state/k", json={"v": 1}, headers=_h(agent, episode_id, day))).status_code
        return {"ok": True, "summary": "stub", "duration_sec": 0}

    async def audit(episode_id: str, day: int, inputs: list | None = None) -> dict[str, Any]:
        async with _client() as cl:
            body = {"entity_type": "vendor", "entity_id": "v_x", "severity": "low", "reason": "r"}
            results["blue"] = (await cl.post("/api/flags", json=body, headers=_h("blue", episode_id, day))).status_code
        return {"ok": True, "summary": "stub"}

    monkeypatch.setattr(agents, "turn", turn)
    monkeypatch.setattr(agents, "audit", audit)
    async with _client() as cl:
        r = await cl.post(f"/api/episodes/{eid}/step", headers=f.auth())
    assert r.status_code == 200
    assert results == {"red": 201, "green": 200, "blue": 201}
    assert await db.fetchval("SELECT COUNT(*) FROM attacks WHERE episode_id=$1", eid) == 1
    assert turns.active(eid) is None
    runner._states.pop(eid, None)
