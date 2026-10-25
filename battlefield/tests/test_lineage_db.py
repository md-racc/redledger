"""DB: lineages run generation by generation with reflection (ARCHITECTURE.md, Evolution: Lineage lifecycle)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import structlog.testing

from app import db, main
from app.config import settings
from app.main import app
from app.orchestrator import agents, lineage, runner
from app.scoring import score
from tests import factories as f

pytestmark = pytest.mark.usefixtures("pg")


@pytest.fixture(autouse=True)
async def _fresh(pg: None, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    """One running lineage per battlefield: park any a crashed earlier run left in the shared test DB."""
    await db.execute("UPDATE lineages SET status='failed' WHERE status IN ('running','paused')")
    await db.execute("UPDATE episodes SET status='finished' WHERE status='running'")  # one active run per battlefield
    monkeypatch.setattr(lineage, "POLL_SEC", 0.01)
    monkeypatch.setattr(settings, "day_pause_sec", 0.0)
    monkeypatch.setattr(lineage, "_control", asyncio.Lock())  # module-level lock binds to the first test's loop
    monkeypatch.setattr(lineage, "_demo_locks", {})
    monkeypatch.setattr(lineage, "_demo_tasks", {})
    yield
    await asyncio.gather(*list(lineage._background), return_exceptions=True)  # demo reflections started by _finish


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
    # Wait on the event, not on polled state: the lineage row flips to `paused` before runner.pause has
    # written the episode's status and emitted `episode.paused`, so polling either one alone races.
    parked: dict[str, asyncio.Event] = {}
    real_pause = runner.pause

    async def pause(episode_id: str) -> None:
        await real_pause(episode_id)
        parked.setdefault(episode_id, asyncio.Event()).set()

    monkeypatch.setattr(runner, "pause", pause)
    async with _client() as c:
        lid = (await _create(c, max_credits=1.0))["id"]
        await c.post(f"/api/lineages/{lid}/start", headers=f.auth())
    try:
        eid = None
        for _ in range(1500):  # bounded: only to learn generation 1's id once it exists
            eid = await db.fetchval("SELECT id FROM episodes WHERE lineage_id=$1 AND generation=1", lid)
            if eid:
                break
            await asyncio.sleep(0.02)
        assert eid is not None
        await asyncio.wait_for(parked.setdefault(eid, asyncio.Event()).wait(), 60)
        assert await db.fetchval("SELECT status FROM lineages WHERE id=$1", lid) == "paused"
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


_FAST = {"fetchval": db.fetchval, "fetchrow": db.fetchrow}


async def _slow_db(monkeypatch: pytest.MonkeyPatch) -> None:
    """Widen every check-then-act window: each fetchval/fetchrow yields first."""
    for name in _FAST:
        orig = getattr(db, name)

        async def slow(*a: Any, _orig: Any = orig, **k: Any) -> Any:
            await asyncio.sleep(0.02)
            return await _orig(*a, **k)

        monkeypatch.setattr(db, name, slow)


async def test_concurrent_starts_and_resumes_spawn_exactly_one_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, _Agents())
    async with _client() as c:
        a, b = (await _create(c))["id"], (await _create(c))["id"]
        await _slow_db(monkeypatch)
        same = await asyncio.gather(*(c.post(f"/api/lineages/{a}/start", headers=f.auth()) for _ in range(3)))
        assert sorted(r.status_code for r in same) == [202, 409, 409]
        assert (await c.post(f"/api/lineages/{b}/start", headers=f.auth())).status_code == 409  # a is running
        assert (await c.post(f"/api/lineages/{a}/pause", headers=f.auth())).status_code == 200
        resumes = await asyncio.gather(*(c.post(f"/api/lineages/{a}/resume", headers=f.auth()) for _ in range(3)))
        assert sorted(r.status_code for r in resumes) == [200, 409, 409]
        for name, fn in _FAST.items():
            monkeypatch.setattr(db, name, fn)
        await asyncio.wait_for(lineage.state(a).task, 60)
        assert await db.fetchval("SELECT status FROM lineages WHERE id=$1", a) == "finished"
        assert await db.fetchval("SELECT COUNT(*) FROM episodes WHERE lineage_id=$1", a) == 2
    await _cleanup(a)

    async with _client() as c:  # two different lineages started at once: one runs
        x, y = (await _create(c))["id"], (await _create(c))["id"]
        await _slow_db(monkeypatch)
        two = await asyncio.gather(c.post(f"/api/lineages/{x}/start", headers=f.auth()), c.post(f"/api/lineages/{y}/start", headers=f.auth()))
    try:
        assert sorted(r.status_code for r in two) == [202, 409]
        assert await db.fetchval("SELECT COUNT(*) FROM lineages WHERE id = ANY($1::text[]) AND status='running'", [x, y]) <= 1
    finally:
        await _cleanup(x)
        await _cleanup(y)
        await db.execute("UPDATE lineages SET status='failed' WHERE id = ANY($1::text[])", [x, y])


async def _paused_generation(c: httpx.AsyncClient, *events: tuple[str, dict[str, Any]]) -> tuple[str, str]:
    """A paused lineage whose generation-1 episode is paused after `events` (then episode.paused)."""
    lid = (await _create(c))["id"]
    eid = await lineage.create_generation(lid, 1, seed=9001, days=2, mode="enforce")
    await db.execute("UPDATE episodes SET status='paused' WHERE id=$1", eid)
    await db.execute("UPDATE lineages SET status='paused' WHERE id=$1", lid)
    for type_, payload in (("episode.started", {}), *events, ("episode.paused", {})):
        await db.execute("INSERT INTO events (episode_id, day, type, agent, payload) VALUES ($1,0,$2,'battlefield',$3)", eid, type_, payload)
    return lid, eid


@pytest.mark.parametrize(
    ("events", "resumed"),
    [
        ([("lineage.paused", {})], True),  # lineage pause / lineage credit guard
        ([("error", {"where": "orchestrator", "message": "battlefield restarted mid-episode; resume to continue"})], True),  # restart
        ([("error", {"where": "credit_guard", "message": "episode paused at 9 credits (limit 5)"})], False),  # MAX_CREDITS_PER_EPISODE
        ([], False),  # by hand
        (  # both guards tripped on one turn: the episode cap is not lifted by a lineage resume
            [("error", {"where": "credit_guard", "message": "episode paused at 9 credits (limit 5)"}), ("lineage.paused", {})],
            False,
        ),
    ],
)
async def test_lineage_resume_resumes_only_episodes_it_paused(monkeypatch: pytest.MonkeyPatch, events: list, resumed: bool) -> None:
    _stub(monkeypatch, _Agents())
    async with _client() as c:
        lid, eid = await _paused_generation(c, *events)
        if not resumed:  # the lineage was paused after the episode had already stopped
            await db.execute("INSERT INTO events (episode_id, day, type, agent, payload) VALUES ($1,0,'lineage.paused','battlefield','{}')", eid)
        assert (await c.post(f"/api/episodes/{eid}/resume", headers=f.auth())).status_code == 409  # its lineage is paused
        assert (await c.post(f"/api/episodes/{eid}/step", headers=f.auth())).status_code == 409
        assert (await c.post(f"/api/lineages/{lid}/resume", headers=f.auth())).status_code == 200
        status = await db.fetchval("SELECT status FROM episodes WHERE id=$1", eid)
        try:
            assert (status == "running") is resumed
            if not resumed:  # the lineage runs again; the episode resumes only by hand
                assert "episode.resumed" not in await _types(eid)
                assert (await c.post(f"/api/episodes/{eid}/resume", headers=f.auth())).status_code == 200
        finally:
            await _cleanup(lid)
            await db.execute("UPDATE lineages SET status='failed' WHERE id=$1", lid)


async def test_demo_episode_emits_generation_ended(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, _Agents())
    async with _client() as c:
        lid = (await _create(c))["id"]
        await db.execute("UPDATE lineages SET status='finished' WHERE id=$1", lid)
        eid = (await c.post("/api/episodes", json={"controller_mode": "enforce", "lineage_id": lid, "days": 1}, headers=f.auth())).json()["id"]
        await runner.step(eid)
    t = await _types(eid)
    assert t[0] == "generation.started" and t[-2:] == ["episode.ended", "generation.ended"]
    ended = await db.fetchval("SELECT payload FROM events WHERE episode_id=$1 AND type='generation.ended'", eid)
    assert ended == {"lineage_id": lid, "generation": 1, "score": await score.compute(eid)}


async def test_interrupted_generation_creation_is_redone_once(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _stub(monkeypatch, _Agents())
    async with _client() as c:
        lid = (await _create(c, generations=1))["id"]
        await db.execute(
            "INSERT INTO playbooks (lineage_id, agent, version, parent_version, generation, source, content) VALUES ($1,'red',1,0,0,'reflect','{}')", lid
        )
        # a process died after inserting generation 1 and part of its seed, before generation.started
        dead = f.uid("ep")
        await db.execute("INSERT INTO episodes (id, seed, controller_mode, days, lineage_id, generation) VALUES ($1,9001,'enforce',2,$2,1)", dead, lid)
        await db.execute("UPDATE lineages SET current_generation=1, status='paused' WHERE id=$1", lid)
        await f.vendor(dead)
        await db.execute(
            "INSERT INTO events (episode_id, day, type, agent, payload) VALUES ($1,0,'playbook.updated','battlefield','{\"agent\":\"red\",\"version\":1}')",
            dead,
        )
        assert (await c.post(f"/api/lineages/{lid}/resume", headers=f.auth())).status_code == 200
        await asyncio.wait_for(lineage.state(lid).task, 60)
    try:
        assert await db.fetchval("SELECT 1 FROM episodes WHERE id=$1", dead) is None
        assert await db.fetchval("SELECT COUNT(*) FROM events WHERE episode_id=$1", dead) == 0
        eid = await db.fetchval("SELECT id FROM episodes WHERE lineage_id=$1 AND generation=1", lid)
        t = await _types(eid)
        assert t[:3] == ["playbook.updated", "generation.started", "episode.started"] and t.count("playbook.updated") == 1
        assert await db.fetchval("SELECT status FROM lineages WHERE id=$1", lid) == "finished" and stub.reflects
    finally:
        await _cleanup(lid)


async def test_fast_pause_then_resume_keeps_one_loop_running(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub(monkeypatch, _Agents())
    async with _client() as c:
        lid = (await _create(c))["id"]
        await c.post(f"/api/lineages/{lid}/start", headers=f.auth())
        task = lineage.state(lid).task
        for _ in range(3):
            assert (await c.post(f"/api/lineages/{lid}/pause", headers=f.auth())).status_code == 200
            assert (await c.post(f"/api/lineages/{lid}/resume", headers=f.auth())).status_code == 200
            await asyncio.sleep(0.03)
            assert lineage.state(lid).task is task and not task.done()  # never respawned, never exited on 'paused'
        await asyncio.wait_for(task, 60)
    try:
        assert await db.fetchval("SELECT status FROM lineages WHERE id=$1", lid) == "finished"
        assert await db.fetchval("SELECT COUNT(*) FROM episodes WHERE lineage_id=$1 AND status='finished'", lid) == 2
    finally:
        await _cleanup(lid)


async def test_a_demo_generation_reflects_so_the_next_demo_starts_from_it(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _stub(monkeypatch, _Agents())
    async with _client() as c:
        lid = (await _create(c))["id"]
        await db.execute("UPDATE lineages SET status='finished' WHERE id=$1", lid)
        body = {"controller_mode": "enforce", "lineage_id": lid, "days": 1}
        e1 = (await c.post("/api/episodes", json=body, headers=f.auth())).json()["id"]
        await runner.step(e1)
        await asyncio.gather(*list(lineage._background))  # _finish reflected the demo in the background
        assert [a for a, b in stub.reflects] == ["red", "green", "blue"] and all(b["episode_id"] == e1 for _, b in stub.reflects)
        assert await db.fetchval("SELECT COUNT(*) FROM debriefs WHERE episode_id=$1 AND day IS NULL", e1) == 3
        red = await db.fetchrow("SELECT version, generation, source FROM playbooks WHERE lineage_id=$1 AND agent='red' ORDER BY version DESC LIMIT 1", lid)
        assert (red["generation"], red["source"]) == (1, "reflect")
        e2 = (await c.post("/api/episodes", json=body, headers=f.auth())).json()["id"]
    assert len(stub.reflects) == 3  # the next demo's creation found the reflection done: nobody asked twice
    started = await db.fetch("SELECT type, payload FROM events WHERE episode_id=$1 ORDER BY id", e2)
    assert [r["type"] for r in started] == ["playbook.updated", "generation.started"]
    assert started[0]["payload"]["source"] == "reflect" and started[1]["payload"]["playbook_versions"]["red"] == red["version"]


async def test_demo_reflection_lost_to_a_restart_is_finished_by_the_next_demo(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _stub(monkeypatch, _Agents())
    real, lost_once = lineage.reflect_demo_later, []

    def lost(lid: str, g: int) -> Any:
        if g == 1 and not lost_once:  # runner._finish's call for the demo: the process died before it ran
            lost_once.append(g)
            return None
        return real(lid, g)

    monkeypatch.setattr(lineage, "reflect_demo_later", lost)
    async with _client() as c:
        lid = (await _create(c))["id"]
        await db.execute("UPDATE lineages SET status='finished' WHERE id=$1", lid)
        body = {"controller_mode": "enforce", "lineage_id": lid, "days": 1}
        e1 = (await c.post("/api/episodes", json=body, headers=f.auth())).json()["id"]
        await runner.step(e1)
        assert stub.reflects == []
        r = await c.post("/api/episodes", json=body, headers=f.auth())
    assert r.status_code == 201 and [a for a, _ in stub.reflects] == ["red", "green", "blue"]
    assert await db.fetchval("SELECT 1 FROM playbooks WHERE lineage_id=$1 AND agent='red' AND source='reflect' AND generation=1", lid)


async def test_demo_reflection_stops_at_the_lineage_credit_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _stub(monkeypatch, _Agents())
    async with _client() as c:
        r = await c.post("/api/lineages", json={"base_seed": 9100, "config": {"generations": 1, "days": 1, "max_credits": 5}}, headers=f.auth())
        lid = r.json()["id"]
    await db.execute("UPDATE lineages SET status='finished' WHERE id=$1", lid)
    monkeypatch.setitem(lineage._reflect_spent, lid, 5.0)  # the lineage already spent its cap (earlier reflections)
    eid = await lineage.create_generation(lid, 1, seed=9101, days=1, mode="enforce")
    await runner.step(eid)
    await asyncio.gather(*list(lineage._background))
    assert stub.reflects == []  # no agent asked: every playbook kept
    assert not await db.fetchval("SELECT 1 FROM events WHERE episode_id=$1 AND type IN ('lineage.paused','error')", eid)


async def test_the_loops_own_generations_are_not_reflected_twice(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _stub(monkeypatch, _Agents())
    async with _client() as c:
        lid = (await _create(c))["id"]
        assert (await c.post(f"/api/lineages/{lid}/start", headers=f.auth())).status_code == 202
        await asyncio.wait_for(lineage.state(lid).task, 60)
    await asyncio.gather(*list(lineage._background))
    assert len(stub.reflects) == 6  # 2 generations × 3 agents, all by the loop
    await _cleanup(lid)


async def test_demo_creation_waits_at_most_the_cap_for_a_slow_reflection(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _stub(monkeypatch, _Agents())
    stub.block = asyncio.Event()  # blue's reflection hangs (a slow model)
    monkeypatch.setattr(lineage, "DEMO_REFLECT_WAIT_SEC", 0.2)
    async with _client() as c:
        lid = (await _create(c))["id"]
        await db.execute("UPDATE lineages SET status='finished' WHERE id=$1", lid)
        body = {"controller_mode": "enforce", "lineage_id": lid, "days": 1}
        e1 = (await c.post("/api/episodes", json=body, headers=f.auth())).json()["id"]
        await runner.step(e1)
        r = await asyncio.wait_for(c.post("/api/episodes", json=body, headers=f.auth()), 5)
        assert r.status_code == 201 and r.json()["generation"] == 2  # created from the playbooks as they were
        pending = lineage._demo_tasks[(lid, 1)]
        assert not pending.done()  # the reflection keeps going in the background, not cancelled by the timeout
        stub.block.set()
        await asyncio.wait_for(pending, 5)
    assert [a for a, _ in stub.reflects] == ["red", "green", "blue"]  # nobody asked twice


async def test_demo_turn_credits_count_toward_the_lineage_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _stub(monkeypatch, _Agents(credits=3.0))
    async with _client() as c:
        r = await c.post("/api/lineages", json={"base_seed": 9200, "config": {"generations": 1, "days": 1, "max_credits": 5}}, headers=f.auth())
        lid = r.json()["id"]
        await db.execute("UPDATE lineages SET status='finished' WHERE id=$1", lid)
        lineage._credits[lid] = 0.0  # a stale per-process total from before the demo
        eid = (await c.post("/api/episodes", json={"controller_mode": "enforce", "lineage_id": lid, "days": 1}, headers=f.auth())).json()["id"]
        await runner.step(eid)  # red + green turns at 3 credits each: 6 ≥ 5
        await asyncio.gather(*list(lineage._background))
    assert stub.reflects == []  # the demo's own turns used the cap up: no reflection
    assert await db.fetchval("SELECT status FROM episodes WHERE id=$1", eid) == "finished"  # the demo itself was never stopped
    assert not await db.fetchval("SELECT 1 FROM events WHERE episode_id=$1 AND type='lineage.paused'", eid)


async def test_a_demo_reflection_finishing_after_the_next_demo_started_is_discarded(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Late(_Agents):
        async def reflect(self, agent: str, body: dict[str, Any]) -> dict[str, Any]:
            if agent != "blue":
                return await super().reflect(agent, body)
            self.reflects.append((agent, body))
            assert self.block is not None
            await self.block.wait()  # a slow model: answers after the next demo already started
            return {"ok": True, "playbook": {"late": True}, "rationale": "late"}

    stub = _stub(monkeypatch, _Late())
    stub.block = asyncio.Event()
    monkeypatch.setattr(lineage, "DEMO_REFLECT_WAIT_SEC", 0.2)
    async with _client() as c:
        lid = (await _create(c))["id"]
        await db.execute("UPDATE lineages SET status='finished' WHERE id=$1", lid)
        body = {"controller_mode": "enforce", "lineage_id": lid, "days": 1}
        e1 = (await c.post("/api/episodes", json=body, headers=f.auth())).json()["id"]
        await runner.step(e1)
        e2 = (await c.post("/api/episodes", json=body, headers=f.auth())).json()["id"]
        pending = lineage._demo_tasks[(lid, 1)]
        with structlog.testing.capture_logs() as logs:
            stub.block.set()
            await asyncio.wait_for(pending, 5)
    assert not await db.fetchval("SELECT 1 FROM playbooks WHERE lineage_id=$1 AND agent='blue' AND source='reflect'", lid)
    assert await db.fetchval("SELECT MAX(version) FROM playbooks WHERE lineage_id=$1 AND agent='blue'", lid) == 0
    blue_updates = "SELECT COUNT(*) FROM events WHERE episode_id=$1 AND type='playbook.updated' AND payload->>'agent'='blue'"
    assert await db.fetchval(blue_updates, e1) == 0 and await db.fetchval(blue_updates, e2) == 0
    assert [(e["lineage_id"], e["generation"], e["agent"]) for e in logs if e["event"] == "demo_reflect_late_discarded"] == [(lid, 1, "blue")]
    assert (lid, 1) not in lineage._demo_tasks  # the finished task was dropped
    # red answered before the next demo existed: its version committed and the next demo announced it
    assert await db.fetchval("SELECT COUNT(*) FROM events WHERE episode_id=$1 AND type='playbook.updated' AND payload->>'agent'='red'", e2) == 1
