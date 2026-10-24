"""DB: agent playbook routes (GET/PUT /playbook, GET /playbook/history)."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app import db, turns
from app.main import app
from tests import factories as f

pytestmark = pytest.mark.usefixtures("pg")


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bf")


async def _lineage_episode(generation: int = 1) -> tuple[str, str]:
    ln = f.uid("ln")
    await db.execute("INSERT INTO lineages (id, base_seed, config) VALUES ($1, 42, '{}'::jsonb)", ln)
    ep = f.uid("ep")
    await db.execute(
        "INSERT INTO episodes (id, seed, controller_mode, lineage_id, generation) VALUES ($1, $2, 'enforce', $3, $4)", ep, 42 + generation, ln, generation
    )
    return ln, ep


def _put(agent: str, ep: str, tu: str, *, day: int = 1) -> dict[str, str]:
    return f.auth(agent, episode=ep, day=day, tool_use_id=tu)


async def test_get_put_history_happy_path() -> None:
    ln, ep = await _lineage_episode(generation=2)
    async with _client() as c:
        seed = await c.get("/api/playbook", headers=f.auth("red", episode=ep, day=1))
        assert seed.status_code == 200
        assert seed.json()["version"] == 0 and seed.json()["source"] == "seed" and seed.json()["content"] == {}
        r1 = await c.put(
            "/api/playbook", json={"content": {"prefer": ["bank_swap"]}, "rationale": "swaps paid", "base_version": 0}, headers=_put("red", ep, "tu_1")
        )
        assert r1.status_code == 201, r1.text
        b1 = r1.json()
        assert (b1["version"], b1["parent_version"], b1["generation"], b1["source"], b1["day"], b1["episode_id"]) == (1, 0, 2, "turn", 1, ep)
        r2 = await c.put("/api/playbook", json={"content": {"prefer": []}, "base_version": 1}, headers=_put("red", ep, "tu_2", day=2))
        assert r2.status_code == 201 and r2.json()["version"] == 2
        latest = (await c.get("/api/playbook", headers=f.auth("red", episode=ep, day=2))).json()
        hist = (await c.get("/api/playbook/history", params={"limit": 2}, headers=f.auth("red", episode=ep, day=2))).json()
    assert latest["version"] == 2 and latest["content"] == {"prefer": []}
    assert [h["version"] for h in hist] == [2, 1]
    assert "tool_use_id" not in latest and "agent" not in latest and "lineage_id" not in latest


async def test_agents_see_only_their_own_playbook() -> None:
    _, ep = await _lineage_episode()
    async with _client() as c:
        assert (await c.put("/api/playbook", json={"content": {"secret": "green"}, "base_version": 0}, headers=_put("green", ep, "tu_g"))).status_code == 201
        blue = (await c.get("/api/playbook", headers=f.auth("blue", episode=ep, day=1))).json()
        blue_hist = (await c.get("/api/playbook/history", headers=f.auth("blue", episode=ep, day=1))).json()
        ignored = (await c.get("/api/playbook", params={"agent": "green"}, headers=f.auth("blue", episode=ep, day=1))).json()
    assert blue["version"] == 0 and blue["content"] == {}
    assert [h["version"] for h in blue_hist] == [0]
    assert ignored["content"] == {}


async def test_operator_may_not_call_agent_playbook_routes() -> None:
    async with _client() as c:
        assert (await c.get("/api/playbook", headers=f.auth())).status_code == 403


async def test_not_a_lineage_episode_is_404(episode: str) -> None:
    async with _client() as c:
        g = await c.get("/api/playbook", headers=f.auth("red", episode=episode, day=1))
        h = await c.get("/api/playbook/history", headers=f.auth("red", episode=episode, day=1))
        p = await c.put("/api/playbook", json={"content": {}, "base_version": 0}, headers=_put("red", episode, "tu_x"))
    for r in (g, h, p):
        assert r.status_code == 404 and r.json() == {"error": "not a lineage episode"}


async def test_stale_base_version_is_409_with_latest() -> None:
    _, ep = await _lineage_episode()
    async with _client() as c:
        await c.put("/api/playbook", json={"content": {"a": 1}, "base_version": 0}, headers=_put("blue", ep, "tu_1"))
        r = await c.put("/api/playbook", json={"content": {"a": 2}, "base_version": 0}, headers=_put("blue", ep, "tu_2"))
    assert r.status_code == 409 and r.json() == {"error": "stale base_version", "latest": 1}


async def test_retry_same_body_returns_the_version_and_different_body_is_409() -> None:
    ln, ep = await _lineage_episode()
    body = {"content": {"rules": ["near_threshold"]}, "rationale": "r", "base_version": 0}
    async with _client() as c:
        first = await c.put("/api/playbook", json=body, headers=_put("blue", ep, "tu_same"))
        retry = await c.put("/api/playbook", json=body, headers=_put("blue", ep, "tu_same"))
        other = await c.put("/api/playbook", json={**body, "content": {"rules": []}}, headers=_put("blue", ep, "tu_same"))
    assert first.status_code == 201 and retry.status_code == 200
    assert retry.json()["version"] == first.json()["version"] == 1
    assert other.status_code == 409 and other.json() == {"error": "idempotency key reused for a different playbook write"}
    assert await db.fetchval("SELECT count(*) FROM playbooks WHERE lineage_id=$1 AND agent='blue'", ln) == 2  # seed + one write
    assert await db.fetchval("SELECT count(*) FROM events WHERE episode_id=$1 AND type='playbook.updated'", ep) == 1


async def test_content_over_64_kib_is_413() -> None:
    ln, ep = await _lineage_episode()
    async with _client() as c:
        r = await c.put("/api/playbook", json={"content": {"blob": "x" * 70_000}, "base_version": 0}, headers=_put("red", ep, "tu_big"))
    assert r.status_code == 413
    assert await db.fetchval("SELECT count(*) FROM playbooks WHERE lineage_id=$1 AND version > 0", ln) == 0


async def test_put_outside_the_active_turn_is_409(turn_guard: None) -> None:
    ln, ep = await _lineage_episode()
    async with _client() as c:
        refused = await c.put("/api/playbook", json={"content": {}, "base_version": 0}, headers=_put("red", ep, "tu_g1"))
        with turns.turn(ep, "red", 1):
            ok = await c.put("/api/playbook", json={"content": {"k": 1}, "base_version": 0}, headers=_put("red", ep, "tu_g2"))
    assert refused.status_code == 409 and refused.json() == {"error": "no active turn for this agent"}
    assert ok.status_code == 201
    assert await db.fetchval("SELECT count(*) FROM playbooks WHERE lineage_id=$1 AND version > 0", ln) == 1


async def test_audit_rows_are_written_and_hidden_from_agents() -> None:
    _, ep = await _lineage_episode()
    async with _client() as c:
        await c.put("/api/playbook", json={"content": {"k": "v"}, "base_version": 0}, headers=_put("green", ep, "tu_a"))
        agent_rows = (await c.get("/api/audit_log", headers=f.auth("blue", episode=ep, day=1))).json()
        op_rows = (await c.get("/api/audit_log", params={"episode_id": ep}, headers=f.auth())).json()
    assert not [r for r in agent_rows if r["action"].startswith("playbook.")]
    [row] = [r for r in op_rows if r["action"] == "playbook.put"]
    assert row["agent"] == "green" and row["http_status"] == 201 and row["tool_use_id"] == "tu_a"
    assert row["result"] == {"version": 1} and "content" not in row["args"]


async def test_event_payload() -> None:
    _, ep = await _lineage_episode(generation=3)
    async with _client() as c:
        await c.put("/api/playbook", json={"content": {"k": 1}, "rationale": "why", "base_version": 0}, headers=_put("blue", ep, "tu_e", day=4))
    ev = await db.fetchrow("SELECT day, agent, payload FROM events WHERE episode_id=$1 AND type='playbook.updated'", ep)
    assert ev["day"] == 4 and ev["agent"] == "battlefield"
    assert ev["payload"] == {"agent": "blue", "version": 1, "parent_version": 0, "generation": 3, "source": "turn", "rationale": "why"}


async def test_concurrent_puts_on_the_same_base_make_exactly_one_version() -> None:
    ln, ep = await _lineage_episode()
    async with _client() as c:
        await c.get("/api/playbook", headers=f.auth("red", episode=ep, day=1))  # seed v0 first, so the race is only on v1
        rs = await asyncio.gather(
            *(c.put("/api/playbook", json={"content": {"n": i}, "base_version": 0}, headers=_put("red", ep, f"tu_c{i}")) for i in range(8))
        )
    codes = sorted(r.status_code for r in rs)
    assert codes.count(201) == 1 and codes.count(409) == 7, codes
    assert await db.fetchval("SELECT max(version) FROM playbooks WHERE lineage_id=$1 AND agent='red'", ln) == 1
