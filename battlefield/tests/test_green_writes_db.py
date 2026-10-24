"""DB: an idempotency key is replayed only for the same action, and every green request is audited."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest

from app import db
from app.auth import Caller
from app.gate import gatekeeper as gate
from app.main import app
from tests import factories as f

pytestmark = pytest.mark.usefixtures("pg")


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bf")  # lifespan not run; `pg` owns the pool


def _green(episode: str, key: str, day: int = 1) -> dict[str, str]:
    return f.auth("green", episode=episode, day=day, tool_use_id=key)


@pytest.fixture
def blue(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Stand-in for POST blue/gate: allows everything and records what it was asked."""
    asked: list[dict[str, Any]] = []

    async def ask(c: Caller, mode: str, action: str, et: str | None, eid: str | None, amount: float | None, args: dict, context: dict):
        asked.append({"key": c.tool_use_id, "action": action, "entity_id": eid, "amount": amount})
        return "allow", "ok", 0.9, []

    monkeypatch.setattr(gate, "_ask_blue", ask)
    return asked


async def _audit(episode: str, key: str) -> list[dict[str, Any]]:
    rows = await db.fetch("SELECT action, http_status, result FROM audit_log WHERE episode_id=$1 AND tool_use_id=$2 ORDER BY id", episode, key)
    return [dict(r) for r in rows]


def _caller(episode: str, key: str) -> Caller:
    return Caller(agent="green", episode_id=episode, day=1, tool_use_id=key)


async def test_same_key_same_action_replays_the_verdict(episode: str, blue: list) -> None:
    vid = await f.vendor(episode)
    inv = await f.invoice(episode, vid, amount=100.0)
    key = f"tu_{uuid.uuid4().hex}"
    first = await gate.check(_caller(episode, key), action="invoices.approve", entity_type="invoice", entity_id=inv, amount=100.0)
    again = await gate.check(_caller(episode, key), action="invoices.approve", entity_type="invoice", entity_id=inv, amount=100.0)
    assert first.allowed and again.allowed and first.verdict_id == again.verdict_id
    assert len(blue) == 1  # same key, same action: no re-evaluation (agent-service.md: same key -> same verdict)


@pytest.mark.parametrize(
    ("action", "entity", "amount"),
    [("invoices.pay", "same", 100.0), ("invoices.approve", "other", 100.0), ("invoices.approve", "same", 5000.0)],
    ids=["different-action", "different-entity", "different-amount"],
)
async def test_same_key_for_a_different_action_is_refused_not_replayed(episode: str, blue: list, action: str, entity: str, amount: float) -> None:
    vid = await f.vendor(episode)
    inv = await f.invoice(episode, vid, amount=100.0)
    other = await f.invoice(episode, vid, amount=100.0)
    key = f"tu_{uuid.uuid4().hex}"
    await gate.check(_caller(episode, key), action="invoices.approve", entity_type="invoice", entity_id=inv, amount=100.0)
    with pytest.raises(gate.IdempotencyConflictError):
        await gate.check(_caller(episode, key), action=action, entity_type="invoice", entity_id=inv if entity == "same" else other, amount=amount)
    assert len(blue) == 1


async def test_route_answers_409_audits_and_leaves_the_entity_untouched_on_key_reuse(episode: str, blue: list) -> None:
    vid = await f.vendor(episode)
    approved = await f.invoice(episode, vid, amount=100.0)
    victim = await f.invoice(episode, vid, amount=9_000.0)
    key = f"tu_{uuid.uuid4().hex}"
    async with _client() as c:
        ok = await c.post(f"/api/invoices/{approved}/approve", headers=_green(episode, key))
        reused = await c.post(f"/api/invoices/{victim}/approve", headers=_green(episode, key))
    assert ok.status_code == 200
    assert reused.status_code == 409
    assert reused.json()["error"] == "idempotency key reused for a different action"
    assert await db.fetchval("SELECT status FROM invoices WHERE id=$1", victim) == "pending"  # not approved, not marked blocked
    assert [(r["action"], r["http_status"]) for r in await _audit(episode, key)] == [("invoices.approve", 200), ("invoices.approve", 409)]
    assert len(blue) == 1


async def test_gl_post_replays_identical_fields_and_refuses_different_ones(episode: str, blue: list) -> None:
    key = f"tu_{uuid.uuid4().hex}"
    entry = {"account": "6100", "debit": 50.0, "credit": 0.0, "memo": "m"}
    async with _client() as c:
        first = await c.post("/api/gl/entries", json=entry, headers=_green(episode, key))
        retry = await c.post("/api/gl/entries", json=entry, headers=_green(episode, key))
        other = await c.post("/api/gl/entries", json={**entry, "debit": 5_000.0}, headers=_green(episode, key))
    assert (first.status_code, retry.status_code, other.status_code) == (201, 201, 409)
    assert len(blue) == 1
    assert [r["http_status"] for r in await _audit(episode, key)] == [201, 201, 409]


@pytest.mark.parametrize(
    ("path", "status", "detail"),
    [
        ("/api/invoices/{approved}/approve", 409, "invoice is approved"),
        ("/api/invoices/inv_missing/pay", 404, "invoice not found"),
        ("/api/invoices/{pending}/match", 404, "po not found"),
        ("/api/expenses/exp_missing/approve", 404, "expense not found"),
        ("/api/invoices/{frozen}/pay", 409, "vendor is frozen"),
    ],
)
async def test_rejections_before_the_gate_are_audited(episode: str, blue: list, path: str, status: int, detail: str) -> None:
    vid = await f.vendor(episode)
    frozen_vendor = await f.vendor(episode, status="frozen")
    ids = {
        "approved": await f.invoice(episode, vid, status="approved"),
        "pending": await f.invoice(episode, vid),
        "frozen": await f.invoice(episode, frozen_vendor, status="approved"),
    }
    key = f"tu_{uuid.uuid4().hex}"
    body = {"po_id": "po_missing"} if path.endswith("/match") else None
    async with _client() as c:
        r = await c.post(path.format(**ids), json=body, headers=_green(episode, key))
    assert r.status_code == status and r.json()["detail"] == detail
    (row,) = await _audit(episode, key)  # exactly one audit row per request (AGENTS.md §3.5)
    assert row["http_status"] == status
    assert row["result"] == {"error": detail}
    assert blue == []  # rejected before the gate
