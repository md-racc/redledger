"""DB: a turn skipped on resume (started before a restart, never ended) gets exactly one closing
`turn.ended {ok: false}`, so turn.started/turn.ended pairs stay balanced and no credits are charged."""

from __future__ import annotations

from typing import Any

import pytest

from app import db, main
from app.events import bus
from app.orchestrator import agents, runner
from seed.company import seed_episode
from tests import factories as f

pytestmark = pytest.mark.usefixtures("pg")

SEED = 4243


class _Crash(Exception):
    pass


async def _pairs(eid: str, day: int) -> dict[str, tuple[int, int]]:
    rows = await db.fetch(
        "SELECT payload->>'agent' AS agent, type FROM events WHERE episode_id=$1 AND day=$2 AND type IN ('turn.started','turn.ended')", eid, day
    )
    out: dict[str, list[int]] = {}
    for r in rows:
        out.setdefault(r["agent"], [0, 0])[0 if r["type"] == "turn.started" else 1] += 1
    return {k: (v[0], v[1]) for k, v in out.items()}


async def _ended(eid: str, day: int, agent: str) -> list[dict[str, Any]]:
    rows = await db.fetch(
        "SELECT payload FROM events WHERE episode_id=$1 AND day=$2 AND type='turn.ended' AND payload->>'agent'=$3 ORDER BY id", eid, day, agent
    )
    return [r["payload"] for r in rows]


async def _resume(eid: str) -> None:
    runner._states.pop(eid, None)
    await main.recover_after_restart()
    await runner.resume(eid)
    task = runner.state(eid).task
    assert task is not None
    await task
    runner._states.pop(eid, None)


async def _running_episode(days: int = 3, current_day: int = 1) -> str:
    eid = f.uid("ep")
    await db.execute(
        "INSERT INTO episodes (id, seed, controller_mode, days, status, current_day) VALUES ($1,$2,'enforce',$3,'running',$4)", eid, SEED, days, current_day
    )
    await seed_episode(eid, SEED)
    await bus.emit(eid, 0, "episode.started", {"controller_mode": "enforce", "days": days, "seed": SEED})
    return eid


async def test_red_turn_interrupted_mid_turn_is_closed_once_on_resume(monkeypatch: pytest.MonkeyPatch) -> None:
    eid = await _running_episode()
    crash = {"on": True}

    async def turn(agent: str, episode_id: str, day: int, mode: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        if agent == "red":
            await f.attack(episode_id, day=day, scheme_id="ghost_vendor")
            if crash["on"]:
                raise _Crash  # died mid-turn: turn.started(red) without turn.ended(red)
        return {"ok": True, "summary": "stub", "duration_sec": 0, "usage": {"factory_credits": 7}}

    async def audit(*_: Any, **__: Any) -> dict[str, Any]:
        return {"ok": True, "summary": "stub"}

    monkeypatch.setattr(agents, "turn", turn)
    monkeypatch.setattr(agents, "audit", audit)
    with pytest.raises(_Crash):
        await runner.run_day(eid)
    assert await _pairs(eid, 1) == {"red": (1, 0)}

    crash["on"] = False
    await _resume(eid)
    assert await _ended(eid, 1, "red") == [{"agent": "red", "ok": False, "summary": runner.SKIPPED_ON_RESUME, "duration_sec": 0}]
    assert await _pairs(eid, 1) == {"red": (1, 1), "green": (1, 1), "blue": (1, 1)}
    # the next day is normal: red ran and was charged as usual
    assert (await _ended(eid, 2, "red"))[0]["ok"] is True

    # closing again (another restart on an already-closed day) emits nothing
    await runner._close_skipped_turn(eid, 1, "red")
    assert len(await _ended(eid, 1, "red")) == 1


async def test_blue_audit_interrupted_on_day_zero_is_closed_once(monkeypatch: pytest.MonkeyPatch) -> None:
    eid = f.uid("ep")
    await db.execute("INSERT INTO episodes (id, seed, controller_mode, days) VALUES ($1,$2,'enforce',1)", eid, SEED)
    await seed_episode(eid, SEED)
    crash = {"on": True}

    async def turn(agent: str, episode_id: str, day: int, mode: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"ok": True, "summary": "stub", "duration_sec": 0}

    async def audit(*_: Any, **__: Any) -> dict[str, Any]:
        if crash["on"]:
            raise _Crash
        return {"ok": True, "summary": "stub"}

    monkeypatch.setattr(agents, "turn", turn)
    monkeypatch.setattr(agents, "audit", audit)
    await runner.start(eid)
    task = runner.state(eid).task
    assert task is not None
    await task  # the loop records the crash as failed; a real crash leaves the episode `running`
    await db.execute("UPDATE episodes SET status='running' WHERE id=$1", eid)
    assert (await _pairs(eid, 0))["blue"] == (1, 0)

    crash["on"] = False
    await _resume(eid)
    blue = await _ended(eid, 0, "blue")
    assert len(blue) == 1 and blue[0]["ok"] is False and blue[0]["summary"] == runner.SKIPPED_ON_RESUME
    assert "factory_credits" not in blue[0]
    assert await _pairs(eid, 0) == {"red": (1, 1), "green": (1, 1), "blue": (1, 1)}


async def test_red_skipped_on_attack_evidence_alone_gets_no_closing_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """No turn.started(red) was recorded (only the attack row): nothing to close, nothing emitted."""
    eid = await _running_episode()
    await f.attack(eid, day=1, scheme_id="ghost_vendor")
    await bus.emit(eid, 1, "day.started", {"day": 1, "legit_injected": {}})  # the day had begun before the crash

    async def turn(agent: str, *_: Any, **__: Any) -> dict[str, Any]:
        return {"ok": True, "summary": "stub", "duration_sec": 0}

    async def audit(*_: Any, **__: Any) -> dict[str, Any]:
        return {"ok": True, "summary": "stub"}

    monkeypatch.setattr(agents, "turn", turn)
    monkeypatch.setattr(agents, "audit", audit)
    await _resume(eid)
    assert await _ended(eid, 1, "red") == []
    assert "red" not in await _pairs(eid, 1)
