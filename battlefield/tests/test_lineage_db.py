"""DB: lineages run generation by generation with reflection (docs/EVOLUTION-DESIGN.md §2)."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from app import db, main
from app.config import settings
from app.main import app
from app.orchestrator import agents, lineage, runner
from app.scoring import score
from tests import factories as f

pytestmark = pytest.mark.usefixtures("pg")


@pytest.fixture(autouse=True)
async def _fresh(pg: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """One running lineage per battlefield: park any a crashed earlier run left in the shared test DB."""
    await db.execute("UPDATE lineages SET status='failed' WHERE status IN ('running','paused')")
    monkeypatch.setattr(lineage, "POLL_SEC", 0.01)
    monkeypatch.setattr(settings, "day_pause_sec", 0.0)


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bf")


class _Agents:
    """Stub agent services. Red lands one paid red invoice per day; reflect answers per agent."""

    def __init__(self, credits: float | None = None) -> None:
        self.reflects: list[tuple[str, dict[str, Any]]] = []
        self.credits = credits
        self.block: asyncio.Event | None = None  # set → blue's reflect waits on it (a process dying mid-reflection)

    async def turn(self, agent: str, episode_id: str, day: int, mode: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        if agent == "red":
            vid = await f.vendor(episode_id, origin="red", bank_account="ACCT-RED")
            aid = await f.attack(episode_id, day=day, scheme_id="ghost_vendor", target_amount=3_000)
            await f.invoice(episode_id, vid, amount=3_000, origin="red", status="paid", attack_id=aid, day=day)
        return {"ok": True, "summary": "stub", "duration_sec": 0, "usage": {"factory_credits": self.credits} if self.credits else None}

    async def audit(self, episode_id: str, day: int, inputs: list | None = None, **extra: Any) -> dict[str, Any]:
        return {"ok": True, "summary": "stub"}

    async def reflect(self, agent: str, body: dict[str, Any]) -> dict[str, Any]:
        self.reflects.append((agent, body))
        if agent == "red":
            return {"ok": True, "playbook": {"learned_in": body["generation"]}, "rationale": f"after gen {body['generation']}"}
        if agent == "green":
            return {"ok": False, "playbook": {"ignored": True}, "rationale": "model error"}  # failure keeps the playbook
        if self.block is not None:
            await self.block.wait()
        return {"ok": True, "playbook": None, "rationale": "keep"}


def _stub(monkeypatch: pytest.MonkeyPatch, stub: _Agents) -> _Agents:
    monkeypatch.setattr(agents, "turn", stub.turn)
    monkeypatch.setattr(agents, "audit", stub.audit)
    monkeypatch.setattr(agents, "reflect", stub.reflect)
    return stub


async def _create(c: httpx.AsyncClient, **config: Any) -> dict[str, Any]:
    r = await c.post("/api/lineages", json={"name": "t", "base_seed": 9000, "config": {"generations": 2, "days": 2, **config}}, headers=f.auth())
    assert r.status_code == 201, r.text
    return r.json()


async def _types(eid: str) -> list[str]:
    return [r["type"] for r in await db.fetch("SELECT type FROM events WHERE episode_id=$1 ORDER BY id", eid)]


async def _cleanup(lid: str) -> None:
    for st in (lineage.state(lid),):
        if st.task and not st.task.done():
            st.task.cancel()
    for eid in [r["id"] for r in await db.fetch("SELECT id FROM episodes WHERE lineage_id=$1", lid)]:
        rst = runner._states.pop(eid, None)
        if rst and rst.task and not rst.task.done():
            rst.task.cancel()


async def test_create_validates_config_and_seeds_version_0() -> None:
    async with _client() as c:
        for bad in ({"bogus": 1}, {"generations": 0}, {"headless": {"escalation_timeout_sec": settings.escalation_timeout_sec + 1}}):
            assert (await c.post("/api/lineages", json={"config": bad}, headers=f.auth())).status_code == 422
        ln = await _create(c)
    assert ln["status"] == "created" and ln["current_generation"] == 0 and ln["generations"] == []
    assert ln["playbook_versions"] == {"red": 0, "green": 0, "blue": 0}
    assert ln["config"]["reveal_days"] == 3 and ln["config"]["reveal_generations"] == 2  # LineageConfig defaults stored
    rows = await db.fetch("SELECT agent, version, generation, source, content FROM playbooks WHERE lineage_id=$1 ORDER BY agent", ln["id"])
    assert [(r["agent"], r["version"], r["generation"], r["source"], r["content"]) for r in rows] == [
        ("blue", 0, 0, "seed", {}),
        ("green", 0, 0, "seed", {}),
        ("red", 0, 0, "seed", {}),
    ]


async def test_two_generations_end_to_end(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _stub(monkeypatch, _Agents())
    async with _client() as c:
        ln = await _create(c)
        lid = ln["id"]
        assert (await c.post(f"/api/lineages/{lid}/start", headers=f.auth())).status_code == 202
        await asyncio.wait_for(lineage.state(lid).task, 60)
        out = (await c.get(f"/api/lineages/{lid}", headers=f.auth())).json()
    try:
        assert out["status"] == "finished" and out["current_generation"] == 2
        assert [(g["generation"], g["seed"], g["status"]) for g in out["generations"]] == [(1, 9001, "finished"), (2, 9002, "finished")]
        assert out["playbook_versions"] == {"red": 2, "green": 0, "blue": 0}
        e1, e2 = (g["episode_id"] for g in out["generations"])

        # reflect after every generation, agents in order; red's answers become versions, green's failure and blue's null keep theirs
        assert [(a, b["generation"]) for a, b in stub.reflects] == [("red", 1), ("green", 1), ("blue", 1), ("red", 2), ("green", 2), ("blue", 2)]
        red = await db.fetch(
            "SELECT version, parent_version, generation, episode_id, source, content FROM playbooks WHERE lineage_id=$1 AND agent='red' ORDER BY version", lid
        )
        assert [(r["version"], r["parent_version"], r["generation"], r["episode_id"], r["source"]) for r in red[1:]] == [
            (1, 0, 1, e1, "reflect"),
            (2, 1, 2, e2, "reflect"),
        ]
        assert stub.reflects[3][1]["playbook"]["version"] == 1 and stub.reflects[3][1]["playbook"]["content"] == {"learned_in": 1}

        # after-action reviews: stored once per agent and generation (day NULL), exactly as sent
        aar = await db.fetch("SELECT generation, agent, payload FROM debriefs WHERE lineage_id=$1 AND day IS NULL ORDER BY generation, agent", lid)
        assert [(r["generation"], r["agent"]) for r in aar] == [(g, a) for g in (1, 2) for a in ("blue", "green", "red")]
        sent = {(b["generation"], a): b["review"] for a, b in stub.reflects}
        assert all(sent[(r["generation"], r["agent"])] == r["payload"] for r in aar)
        red2 = sent[(2, "red")]
        assert red2["seed"] == 9002 and red2["items"] and all(i["kind"] == "attack" for i in red2["items"])
        assert [h["generation"] for h in red2["history"]] == [1] and sent[(1, "red")]["history"] == []
        assert "rules" in sent[(2, "blue")] and "rules" not in red2

        # events.md: reflect-time playbook.updated → generation.started → episode.started; episode.ended → generation.ended
        t1, t2 = await _types(e1), await _types(e2)
        assert t1[:2] == ["generation.started", "episode.started"] and t1[-2:] == ["episode.ended", "generation.ended"]
        assert t2[:3] == ["playbook.updated", "generation.started", "episode.started"] and t2[-2:] == ["episode.ended", "generation.ended"]
        gs = await db.fetchval("SELECT payload FROM events WHERE episode_id=$1 AND type='generation.started'", e2)
        assert gs == {"lineage_id": lid, "generation": 2, "seed": 9002, "playbook_versions": {"red": 1, "green": 0, "blue": 0}}

        # the review reveals the rest of the episode without moving its score
        ended = await db.fetchval("SELECT payload FROM events WHERE episode_id=$1 AND type='generation.ended'", e1)
        assert ended["score"] == await score.compute(e1)
        assert await db.fetchval("SELECT COUNT(*) FROM attacks WHERE episode_id=$1 AND revealed_day IS NULL", e1) == 0
    finally:
        await _cleanup(lid)


async def test_reveal_generations_0_means_no_review_and_no_reflect(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _stub(monkeypatch, _Agents())
    async with _client() as c:
        lid = (await _create(c, reveal_generations=0))["id"]
        await c.post(f"/api/lineages/{lid}/start", headers=f.auth())
        await asyncio.wait_for(lineage.state(lid).task, 60)
    try:
        assert stub.reflects == []
        assert await db.fetchval("SELECT COUNT(*) FROM debriefs WHERE lineage_id=$1 AND day IS NULL", lid) == 0
        assert await db.fetchval("SELECT status FROM lineages WHERE id=$1", lid) == "finished"
        eps = await db.fetch("SELECT id FROM episodes WHERE lineage_id=$1", lid)
        assert len(eps) == 2
        for e in eps:
            assert "generation.ended" in await _types(e["id"])
    finally:
        await _cleanup(lid)


async def test_one_lineage_runs_at_a_time() -> None:
    async with _client() as c:
        a, b = (await _create(c))["id"], (await _create(c))["id"]
        await db.execute("UPDATE lineages SET status='running' WHERE id=$1", a)
        assert (await c.post(f"/api/lineages/{b}/start", headers=f.auth())).status_code == 409
        assert (await c.post(f"/api/lineages/{a}/start", headers=f.auth())).status_code == 409  # not in status created
        assert (await c.post(f"/api/lineages/{b}/pause", headers=f.auth())).status_code == 409  # not running
        assert (await c.post(f"/api/lineages/{b}/resume", headers=f.auth())).status_code == 409  # not paused
        assert (await c.post("/api/lineages/ln_nope/start", headers=f.auth())).status_code == 404
    await db.execute("UPDATE lineages SET status='failed' WHERE id=$1", a)


async def test_demo_episode_is_the_next_generation_of_a_finished_lineage() -> None:
    async with _client() as c:
        ln = await _create(c)
        lid, body = ln["id"], {"controller_mode": "enforce", "lineage_id": ln["id"]}
        for status in ("created", "running", "paused"):
            await db.execute("UPDATE lineages SET status=$2 WHERE id=$1", lid, status)
            assert (await c.post("/api/episodes", json=body, headers=f.auth())).status_code == 409
        assert (await c.post("/api/episodes", json={**body, "lineage_id": "ln_nope"}, headers=f.auth())).status_code == 404
        await db.execute("UPDATE lineages SET status='finished' WHERE id=$1", lid)
        r1 = await c.post("/api/episodes", json=body, headers=f.auth())
        assert r1.status_code == 201 and (r1.json()["generation"], r1.json()["seed"], r1.json()["days"]) == (1, 9001, 2)
        assert (await c.post("/api/episodes", json={**body, "seed": 9001}, headers=f.auth())).status_code == 422
        r2 = await c.post("/api/episodes", json=body, headers=f.auth())
        assert r2.status_code == 201 and (r2.json()["generation"], r2.json()["seed"]) == (2, 9002)
    assert await db.fetchval("SELECT current_generation FROM lineages WHERE id=$1", lid) == 2
    assert await _types(r2.json()["id"]) == ["generation.started"]  # episode.started follows when started by hand
    assert runner.state(r2.json()["id"]).day_pause_sec is None  # never headless: DAY_PAUSE_SEC as usual


async def test_lineage_credit_cap_pauses_lineage_and_episode(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, _Agents(credits=0.6))
    async with _client() as c:
        lid = (await _create(c, max_credits=1.0))["id"]
        await c.post(f"/api/lineages/{lid}/start", headers=f.auth())
        for _ in range(500):
            if await db.fetchval("SELECT status FROM lineages WHERE id=$1", lid) == "paused":
                break
            await asyncio.sleep(0.02)
    try:
        assert await db.fetchval("SELECT status FROM lineages WHERE id=$1", lid) == "paused"
        eid = await db.fetchval("SELECT id FROM episodes WHERE lineage_id=$1 AND generation=1", lid)
        for _ in range(200):  # the tripping day still runs to day.ended before the episode parks
            if runner.state(eid).task is None or not runner.state(eid).pause.is_set():
                break
            await asyncio.sleep(0.02)
        rows = await db.fetch("SELECT type, payload FROM events WHERE episode_id=$1 AND type IN ('error','lineage.paused','episode.paused') ORDER BY id", eid)
        assert [r["type"] for r in rows][:3] == ["error", "lineage.paused", "episode.paused"]
        assert rows[0]["payload"] == {"where": "credit_guard", "message": "lineage paused at 1.2 credits (limit 1)"}
        assert await db.fetchval("SELECT status FROM episodes WHERE id=$1", eid) == "paused"
    finally:
        await _cleanup(lid)


async def test_restart_pauses_lineage_and_resume_finishes_the_interrupted_reflection(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _stub(monkeypatch, _Agents())
    stub.block = asyncio.Event()  # blue's generation-1 reflection never returns: the process dies there
    async with _client() as c:
        lid = (await _create(c))["id"]
        await c.post(f"/api/lineages/{lid}/start", headers=f.auth())
        for _ in range(1000):
            if len(stub.reflects) == 3:
                break
            await asyncio.sleep(0.02)
        assert [a for a, _ in stub.reflects] == ["red", "green", "blue"]

        # the process dies: in-memory state is gone, startup recovery pauses the lineage
        lineage.state(lid).task.cancel()
        lineage._states.pop(lid, None)
        lineage._reflect_done.clear()
        e1 = await db.fetchval("SELECT id FROM episodes WHERE lineage_id=$1 AND generation=1", lid)
        runner._states.pop(e1, None)
        await db.execute("UPDATE lineages SET status='running' WHERE id=$1", lid)  # what the dead process left
        await main.recover_after_restart()
        assert await db.fetchval("SELECT status FROM lineages WHERE id=$1", lid) == "paused"
        assert (await _types(e1))[-1] == "lineage.paused"

        stub.block = None
        assert (await c.post(f"/api/lineages/{lid}/resume", headers=f.auth())).status_code == 200
        await asyncio.wait_for(lineage.state(lid).task, 60)
    try:
        assert await db.fetchval("SELECT status FROM lineages WHERE id=$1", lid) == "finished"
        gen1 = [a for a, b in stub.reflects if b["generation"] == 1]
        assert gen1 == ["red", "green", "blue", "green", "blue"]  # red's version was written: not asked again
        assert await db.fetchval("SELECT COUNT(*) FROM debriefs WHERE lineage_id=$1 AND generation=1 AND day IS NULL", lid) == 3  # reused
        assert await db.fetchval("SELECT COUNT(*) FROM playbooks WHERE lineage_id=$1 AND agent='red' AND source='reflect' AND generation=1", lid) == 1
        assert await db.fetchval("SELECT COUNT(*) FROM episodes WHERE lineage_id=$1", lid) == 2
        assert "lineage.resumed" in await _types(e1)
    finally:
        await _cleanup(lid)
