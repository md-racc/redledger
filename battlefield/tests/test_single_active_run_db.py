"""DB: at most one active run per battlefield (orchestrator/active.py), and the agent busy-409 backstop."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator

import httpx
import pytest

from app import db
from app.config import settings
from app.main import app
from app.orchestrator import active, agents, lineage, runner
from tests import factories as f

pytestmark = pytest.mark.usefixtures("pg")


@pytest.fixture(autouse=True)
async def _quiet(pg: None, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    """The test DB is shared: nothing else may count as active while these run."""
    await db.execute("UPDATE episodes SET status='finished' WHERE status='running'")
    await db.execute("UPDATE lineages SET status='failed' WHERE status IN ('running','paused')")
    monkeypatch.setattr(lineage, "_control", asyncio.Lock())  # module-level lock binds to the first test's loop
    monkeypatch.setattr(settings, "day_pause_sec", 0.0)
    active._stepping.clear()
    yield
    active._stepping.clear()
    await db.execute("UPDATE episodes SET status='finished' WHERE status='running'")
    await db.execute("UPDATE lineages SET status='failed' WHERE status IN ('running','paused')")


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bf")


async def _episode(status: str = "created", *, eid: str | None = None, lineage_id: str | None = None, generation: int | None = None) -> str:
    eid = eid or f.uid("ep")
    await db.execute(
        "INSERT INTO episodes (id, seed, controller_mode, days, status, lineage_id, generation) VALUES ($1, 1, 'off', 1, $2, $3, $4)",
        eid,
        status,
        lineage_id,
        generation,
    )
    return eid


async def _lineage(status: str = "created", current_generation: int = 0) -> str:
    lid = f.uid("ln")
    await db.execute(
        "INSERT INTO lineages (id, base_seed, config, status, current_generation) VALUES ($1, 1, $2::jsonb, $3, $4)",
        lid,
        json.dumps({"generations": 1, "days": 1}),
        status,
        current_generation,
    )
    return lid


def _fake_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    """Flip status like the real runner without starting a day loop (the guard is what's under test)."""

    async def start(eid: str) -> None:
        await asyncio.sleep(0.01)  # widen the window two concurrent starts would race in
        await db.execute("UPDATE episodes SET status='running' WHERE id=$1", eid)

    monkeypatch.setattr(runner, "start", start)
    monkeypatch.setattr(runner, "resume", start)


async def _status(eid: str) -> str:
    return await db.fetchval("SELECT status FROM episodes WHERE id=$1", eid)


async def test_a_second_episode_start_is_refused_with_the_active_run(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_runner(monkeypatch)
    a, b = await _episode("running"), await _episode()
    async with _client() as c:
        r = await c.post(f"/api/episodes/{b}/start", headers=f.auth())
    assert r.status_code == 409
    assert r.json() == {"error": "another run is active", "episode_id": a, "lineage_id": None}
    assert await _status(b) == "created"


async def test_a_running_lineage_blocks_episodes_and_its_own_generation_does_not(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_runner(monkeypatch)
    lid = await _lineage("running", current_generation=1)
    gen = await _episode("running", lineage_id=lid, generation=1)
    plain = await _episode()
    async with _client() as c:
        r = await c.post(f"/api/episodes/{plain}/start", headers=f.auth())
    assert r.status_code == 409 and r.json()["lineage_id"] == lid and r.json()["episode_id"] == gen
    assert await active.blocker(episode_id=gen) is None  # the lineage's own run never blocks itself
    await db.execute("UPDATE episodes SET status='paused' WHERE id=$1", gen)  # between days: the lineage still holds the run
    b = await active.blocker(episode_id=plain)
    assert b is not None and b.lineage_id == lid and b.episode_id == gen


async def test_a_running_episode_blocks_lineage_start_and_resume(monkeypatch: pytest.MonkeyPatch) -> None:
    a = await _episode("running")
    created, paused = await _lineage("created"), await _lineage("paused")
    async with _client() as c:
        r1 = await c.post(f"/api/lineages/{created}/start", headers=f.auth())
        r2 = await c.post(f"/api/lineages/{paused}/resume", headers=f.auth())
    for r in (r1, r2):
        assert r.status_code == 409
        assert r.json() == {"error": "another run is active", "episode_id": a, "lineage_id": None}
    assert await db.fetchval("SELECT status FROM lineages WHERE id=$1", created) == "created"
    assert await db.fetchval("SELECT status FROM lineages WHERE id=$1", paused) == "paused"


async def test_concurrent_starts_let_exactly_one_win(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_runner(monkeypatch)
    eps = [await _episode() for _ in range(4)]
    async with _client() as c:
        rs = await asyncio.gather(*(c.post(f"/api/episodes/{e}/start", headers=f.auth()) for e in eps))
    assert sorted(r.status_code for r in rs) == [202, 409, 409, 409]
    assert [await _status(e) for e in eps].count("running") == 1


async def test_resuming_the_active_episode_itself_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_runner(monkeypatch)
    a = await _episode("running")
    async with _client() as c:
        r = await c.post(f"/api/episodes/{a}/resume", headers=f.auth())
    assert r.status_code == 200, r.text


async def test_replays_never_count_as_active(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_runner(monkeypatch)
    await _episode("running", eid=f.uid("replay"))
    b = await _episode()
    async with _client() as c:
        r = await c.post(f"/api/episodes/{b}/start", headers=f.auth())
    assert r.status_code == 202, r.text


async def test_a_manual_step_holds_the_run_until_its_day_ends(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_runner(monkeypatch)
    release = asyncio.Event()

    async def step(eid: str) -> dict:
        await release.wait()
        return {"day": 0}

    monkeypatch.setattr(runner, "step", step)
    a, b = await _episode("paused"), await _episode()
    async with _client() as c:
        stepping = asyncio.create_task(c.post(f"/api/episodes/{a}/step", headers=f.auth()))
        while a not in active._stepping:
            await asyncio.sleep(0.005)
        r = await c.post(f"/api/episodes/{b}/start", headers=f.auth())
        assert r.status_code == 409 and r.json()["episode_id"] == a
        release.set()
        assert (await stepping).status_code == 200
        r = await c.post(f"/api/episodes/{b}/start", headers=f.auth())
        assert r.status_code == 202, r.text


# ---------- backstop: an agent's busy 409 is retried briefly ----------


def _agent_client(responses: list[httpx.Response]) -> tuple[httpx.AsyncClient, list[int]]:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return responses[min(len(calls) - 1, len(responses) - 1)]

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), calls


async def test_a_busy_agent_is_retried_then_answers() -> None:
    busy = httpx.Response(409, json={"detail": "turn already in progress"})
    ok = httpx.Response(200, json={"ok": True})
    client, calls = _agent_client([busy, ok])
    async with client:
        r = await agents._post(client, "red", "/turn", {"episode_id": "ep_x"})
    assert r.status_code == 200 and len(calls) == 2


async def test_a_busy_agent_is_given_up_on_and_other_conflicts_are_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agents, "BUSY_RETRY_SEC", 0.8)
    client, calls = _agent_client([httpx.Response(409, json={"detail": "blue audit already in progress"})])
    t0 = time.monotonic()
    async with client:
        r = await agents._post(client, "blue", "/audit", {"episode_id": "ep_x"})
    assert r.status_code == 409 and 2 <= len(calls) <= 3 and time.monotonic() - t0 < 2.0
    other, calls2 = _agent_client([httpx.Response(409, json={"detail": "idempotency key reused"})])
    async with other:
        r = await agents._post(other, "red", "/turn", {"episode_id": "ep_x"})
    assert r.status_code == 409 and len(calls2) == 1
