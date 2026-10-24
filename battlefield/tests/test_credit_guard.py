"""Credit guard: pause an episode once its Factory credit spend reaches MAX_CREDITS_PER_EPISODE.

Pure-function cases, a monkeypatched unit tier (no DB), and one DB-tier test of the restart seed.
"""

from __future__ import annotations

from typing import Any

import pytest

from app import db
from app.config import settings
from app.events import bus
from app.orchestrator import agents, runner
from tests.factories import uid

# ---------- pure ----------


@pytest.mark.parametrize(
    ("total", "limit", "tripped"),
    [
        (100.0, 0.0, False),  # limit 0 disables the guard
        (100.0, -1.0, False),  # negative limit also disables
        (0.4, 0.5, False),  # below
        (0.5, 0.5, True),  # equal trips
        (0.6, 0.5, True),  # above
        (0.0, 0.001, False),  # nothing spent yet
    ],
)
def test_credit_guard_tripped(total: float, limit: float, tripped: bool) -> None:
    assert runner.credit_guard_tripped(total, limit) is tripped


@pytest.mark.parametrize(("raw", "spent"), [(None, 0.0), (1, 1.0), (0.25, 0.25), ("0.5", 0.5), ("junk", 0.0), (True, 0.0), (-3, 0.0)])
def test_credits_of(raw: Any, spent: float) -> None:
    assert runner.credits_of(raw) == spent


def test_none_credits_never_trip() -> None:
    assert not runner.credit_guard_tripped(0.0 + runner.credits_of(None), 0.001)


# ---------- unit (fake db + bus) ----------


class FakeWorld:
    def __init__(self, status: str = "running", seeded_sum: float = 0.0) -> None:
        self.status = status
        self.seeded_sum = seeded_sum
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.turn_credits: Any = None

    async def emit(self, episode_id: str, day: int, type_: str, payload: dict[str, Any] | None = None, **_: Any) -> dict[str, Any]:
        self.events.append((type_, payload or {}))
        return {}

    async def execute(self, sql: str, *args: Any) -> str:
        if "status='paused'" in sql:
            self.status = "paused"
        elif "status='running'" in sql:
            self.status = "running"
        return "UPDATE 1"

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any]:
        return {"current_day": 3}

    async def fetchval(self, sql: str, *args: Any) -> Any:
        if "SUM(" in sql:
            return self.seeded_sum
        if "SELECT status" in sql:
            return self.status
        raise AssertionError(sql)

    async def fetch(self, sql: str, *args: Any) -> list[Any]:
        return []

    async def turn(self, agent: str, episode_id: str, day: int, mode: str, options: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "summary": "did things", "duration_sec": 1.0, "usage": {"factory_credits": self.turn_credits}}

    def types(self) -> list[str]:
        return [t for t, _ in self.events]

    def errors(self) -> list[dict[str, Any]]:
        return [p for t, p in self.events if t == "error"]


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> FakeWorld:
    w = FakeWorld()
    for name in ("execute", "fetchrow", "fetchval", "fetch"):
        monkeypatch.setattr(db, name, getattr(w, name))
    monkeypatch.setattr(bus, "emit", w.emit)
    monkeypatch.setattr(agents, "turn", w.turn)
    monkeypatch.setitem(settings.__dict__, "max_credits_per_episode", 0.001)
    return w


async def _seeded(world: FakeWorld) -> str:
    eid = uid("ep")
    await runner._seed_credits(eid)
    return eid


async def test_turn_over_limit_pauses_and_emits_error(world: FakeWorld) -> None:
    eid = await _seeded(world)
    world.turn_credits = 1
    await runner._turn(eid, 3, "red", "enforce", {})

    assert world.types() == ["turn.started", "turn.ended", "error", "episode.paused"]
    turn_ended = world.events[1][1]
    assert turn_ended["factory_credits"] == 1
    assert world.errors() == [{"where": "credit_guard", "message": "episode paused at 1 credits (limit 0.001)"}]
    assert world.status == "paused"
    assert not runner.state(eid).pause.is_set()  # the loop blocks before the next day


async def test_rest_of_day_does_not_trip_again(world: FakeWorld) -> None:
    eid = await _seeded(world)
    world.turn_credits = 1
    await runner._turn(eid, 3, "red", "enforce", {})
    world.events.clear()
    await runner._turn(eid, 3, "green", "enforce", {})
    assert world.types() == ["turn.started", "turn.ended"]
    assert runner.state(eid).credits_total == 2.0


async def test_resume_rearms_on_next_spend_only(world: FakeWorld, monkeypatch: pytest.MonkeyPatch) -> None:
    eid = await _seeded(world)
    world.turn_credits = 1
    await runner._turn(eid, 3, "red", "enforce", {})
    st = runner.state(eid)

    async def no_loop(episode_id: str) -> None:  # resume() starts the loop task when none runs
        return None

    monkeypatch.setattr(runner, "start", no_loop)
    await runner.resume(eid)
    assert world.status == "running" and st.credit_guard_armed

    world.events.clear()
    world.turn_credits = None  # a free turn does not re-trip
    await runner._turn(eid, 4, "red", "enforce", {})
    assert "error" not in world.types()

    world.turn_credits = 0.5  # the next paid turn does
    await runner._turn(eid, 4, "green", "enforce", {})
    assert world.errors()[-1]["message"] == "episode paused at 1.5 credits (limit 0.001)"
    assert world.status == "paused"


async def test_limit_zero_disables(world: FakeWorld, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(settings.__dict__, "max_credits_per_episode", 0.0)
    eid = await _seeded(world)
    world.turn_credits = 1000
    await runner._turn(eid, 3, "red", "enforce", {})
    assert "error" not in world.types() and world.status == "running"


async def test_dry_run_none_credits_never_trip(world: FakeWorld) -> None:
    eid = await _seeded(world)
    world.turn_credits = None
    for agent in ("red", "green"):
        await runner._turn(eid, 3, agent, "enforce", {})
    assert "error" not in world.types()
    assert runner.state(eid).credits_total == 0.0


async def test_seed_from_prior_turns_after_restart(world: FakeWorld) -> None:
    world.seeded_sum = 0.0009
    eid = await _seeded(world)
    world.turn_credits = 0.0002
    await runner._turn(eid, 3, "red", "enforce", {})
    assert world.errors() and world.errors()[0]["where"] == "credit_guard"


async def test_already_paused_step_emits_error_without_second_pause(world: FakeWorld) -> None:
    world.status = "paused"
    eid = await _seeded(world)
    world.turn_credits = 1
    await runner._turn(eid, 3, "red", "enforce", {})
    assert world.types() == ["turn.started", "turn.ended", "error"]
    assert not runner.state(eid).pause.is_set()


# ---------- DB tier ----------


async def test_db_seed_and_pause(episode: str, monkeypatch: pytest.MonkeyPatch) -> None:
    async def turn(agent: str, episode_id: str, day: int, mode: str, options: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "summary": "", "duration_sec": 0, "usage": {"factory_credits": 1}}

    monkeypatch.setattr(agents, "turn", turn)
    monkeypatch.setitem(settings.__dict__, "max_credits_per_episode", 2.5)
    await db.execute("UPDATE episodes SET status='running' WHERE id=$1", episode)
    # spend recorded before a "restart": one paid turn, one DRY_RUN turn with null credits
    await bus.emit(episode, 0, "turn.ended", {"agent": "red", "ok": True, "factory_credits": 2})
    await bus.emit(episode, 0, "turn.ended", {"agent": "green", "ok": True, "factory_credits": None})

    await runner._seed_credits(episode)
    assert runner.state(episode).credits_total == 2.0
    await runner._turn(episode, 1, "red", "enforce", {})

    assert await db.fetchval("SELECT status FROM episodes WHERE id=$1", episode) == "paused"
    rows = await db.fetch("SELECT type, payload FROM events WHERE episode_id=$1 AND type IN ('error','episode.paused') ORDER BY id", episode)
    assert [r["type"] for r in rows] == ["error", "episode.paused"]
    payload = rows[0]["payload"]
    assert payload == {"where": "credit_guard", "message": "episode paused at 3 credits (limit 2.5)"}
