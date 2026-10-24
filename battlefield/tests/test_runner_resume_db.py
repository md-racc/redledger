"""DB: a day interrupted by a battlefield restart is resumed, not injected twice."""

from __future__ import annotations

from typing import Any

import pytest

from app import db, main
from app.events import bus
from app.orchestrator import agents, runner
from seed.company import seed_episode
from tests import factories as f

pytestmark = pytest.mark.usefixtures("pg")

SEED = 4242


class _Crash(Exception):
    """The process dies mid-day (here: during green's turn)."""


async def _legit_rows(eid: str, day: int) -> dict[str, int]:
    return {
        "invoices": await db.fetchval("SELECT COUNT(*) FROM invoices WHERE episode_id=$1 AND received_day=$2", eid, day),
        "purchase_orders": await db.fetchval("SELECT COUNT(*) FROM purchase_orders WHERE episode_id=$1 AND created_day=$2", eid, day),
        "expenses": await db.fetchval("SELECT COUNT(*) FROM expenses WHERE episode_id=$1 AND submitted_day=$2", eid, day),
        "bank_lines": await db.fetchval("SELECT COUNT(*) FROM bank_transactions WHERE episode_id=$1 AND day=$2", eid, day),
        "vendor_changes": await db.fetchval("SELECT COUNT(*) FROM vendor_changes WHERE episode_id=$1 AND requested_day=$2", eid, day),
        "vendors": await db.fetchval("SELECT COUNT(*) FROM vendors WHERE episode_id=$1 AND created_day=$2", eid, day),
    }


async def _count(eid: str, type_: str, day: int | None = None) -> int:
    return await db.fetchval("SELECT COUNT(*) FROM events WHERE episode_id=$1 AND type=$2 AND ($3::int IS NULL OR day=$3)", eid, type_, day)


async def test_resume_after_restart_mid_day_does_not_inject_the_day_twice(monkeypatch: pytest.MonkeyPatch) -> None:
    eid = f.uid("ep")
    await db.execute("INSERT INTO episodes (id, seed, controller_mode, days, status, current_day) VALUES ($1,$2,'enforce',3,'running',1)", eid, SEED)
    await seed_episode(eid, SEED)
    await bus.emit(eid, 0, "episode.started", {"controller_mode": "enforce", "days": 3, "seed": SEED})  # day 0 already ran
    turns: list[tuple[str, int]] = []
    crash = {"on": True}

    async def turn(agent: str, episode_id: str, day: int, mode: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        turns.append((agent, day))
        if agent == "red":
            await f.attack(episode_id, day=day, scheme_id="ghost_vendor")  # what a red turn leaves behind
        if agent == "green" and crash["on"]:
            raise _Crash
        return {"ok": True, "summary": "stub", "duration_sec": 0}

    async def audit(episode_id: str, day: int, inputs: list | None = None) -> dict[str, Any]:
        return {"ok": True, "summary": "stub"}

    monkeypatch.setattr(agents, "turn", turn)
    monkeypatch.setattr(agents, "audit", audit)

    # day 1 starts, legit traffic lands, then the process dies during green's turn
    with pytest.raises(_Crash):
        await runner.run_day(eid)
    once = await _legit_rows(eid, 1)
    assert sum(once.values()) > 0 and await _count(eid, "day.started", 1) == 1
    assert await db.fetchval("SELECT current_day FROM episodes WHERE id=$1", eid) == 1  # still on the interrupted day

    # new process: no in-memory runner state; startup recovery pauses the episode
    runner._states.pop(eid, None)
    await main.recover_after_restart()
    assert await db.fetchval("SELECT status FROM episodes WHERE id=$1", eid) == "paused"

    # the human resumes: day 1 re-runs its turns but is not injected or announced again
    crash["on"] = False
    turns.clear()
    await runner.resume(eid)
    task = runner.state(eid).task
    assert task is not None
    await task
    assert await _legit_rows(eid, 1) == once
    assert await _count(eid, "day.started", 1) == 1 and await _count(eid, "day.ended", 1) == 1
    # red's turn had ended before the crash: skipped, no duplicate attack; green's was interrupted: re-run
    assert [t for t in turns if t[1] == 1] == [("green", 1)]
    assert await db.fetchval("SELECT COUNT(*) FROM attacks WHERE episode_id=$1 AND day_launched=1", eid) == 1
    turn_ended = await db.fetch(
        "SELECT payload->>'agent' AS agent, payload->>'summary' AS summary FROM events WHERE episode_id=$1 AND type='turn.ended' AND day=1 ORDER BY id", eid
    )
    # green's interrupted start is closed as superseded before its re-run ends normally: pairs stay balanced
    assert [(r["agent"], r["summary"] == runner.SUPERSEDED_ON_RESUME) for r in turn_ended] == [
        ("red", False),
        ("green", True),
        ("green", False),
        ("blue", False),
    ]
    assert await _count(eid, "episode.started") == 1  # announced on day 0, not again on resume
    # later days are untouched by the guard: day 2 started and injected normally
    assert await _count(eid, "day.started", 2) == 1 and sum((await _legit_rows(eid, 2)).values()) > 0
    ep = await db.fetchrow("SELECT status, current_day FROM episodes WHERE id=$1", eid)
    assert (ep["status"], ep["current_day"]) == ("finished", 3)
    runner._states.pop(eid, None)


async def test_a_fresh_day_still_injects(monkeypatch: pytest.MonkeyPatch) -> None:
    eid = f.uid("ep")
    await db.execute("INSERT INTO episodes (id, seed, controller_mode, days) VALUES ($1,$2,'shadow',2)", eid, SEED)
    await seed_episode(eid, SEED)

    async def turn(*_: Any, **__: Any) -> dict[str, Any]:
        return {"ok": True, "summary": "stub", "duration_sec": 0}

    async def audit(*_: Any, **__: Any) -> dict[str, Any]:
        return {"ok": True}

    monkeypatch.setattr(agents, "turn", turn)
    monkeypatch.setattr(agents, "audit", audit)
    await runner.run_day(eid)
    assert await _count(eid, "day.started", 0) == 1 and sum((await _legit_rows(eid, 0)).values()) > 0
    runner._states.pop(eid, None)


async def test_resume_on_day_zero_skips_started_turns_and_does_not_restart_the_episode(monkeypatch: pytest.MonkeyPatch) -> None:
    eid = f.uid("ep")
    await db.execute("INSERT INTO episodes (id, seed, controller_mode, days) VALUES ($1,$2,'enforce',1)", eid, SEED)
    await seed_episode(eid, SEED)
    turns: list[str] = []
    crash = {"on": True}

    async def turn(agent: str, episode_id: str, day: int, mode: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        turns.append(agent)
        if agent == "red":
            await f.attack(episode_id, day=day, scheme_id="ghost_vendor")
        return {"ok": True, "summary": "stub", "duration_sec": 0}

    async def audit(episode_id: str, day: int, inputs: list | None = None) -> dict[str, Any]:
        turns.append("blue")
        if crash["on"]:
            raise _Crash
        return {"ok": True, "summary": "stub"}

    monkeypatch.setattr(agents, "turn", turn)
    monkeypatch.setattr(agents, "audit", audit)

    # started normally, then the process dies during blue's audit on day 0
    await runner.start(eid)
    task = runner.state(eid).task
    assert task is not None
    await task  # the loop records the crash as a failed episode; a real crash leaves it `running`
    await db.execute("UPDATE episodes SET status='running' WHERE id=$1", eid)
    assert await _count(eid, "episode.started") == 1 and turns == ["red", "green", "blue"]

    runner._states.pop(eid, None)
    await main.recover_after_restart()
    crash["on"] = False
    turns.clear()
    await runner.resume(eid)
    task = runner.state(eid).task
    assert task is not None
    await task
    assert turns == []  # red and green had ended; blue's audit had started (flags/reports aren't idempotent)
    assert await _count(eid, "episode.started") == 1  # not announced again on resume
    assert await _count(eid, "day.started", 0) == 1 and await _count(eid, "day.ended", 0) == 1
    assert await db.fetchval("SELECT COUNT(*) FROM attacks WHERE episode_id=$1", eid) == 1
    assert await db.fetchval("SELECT status FROM episodes WHERE id=$1", eid) == "finished"
    runner._states.pop(eid, None)


@pytest.mark.parametrize("evidence", ["turn_started", "attack_only"])
async def test_crash_after_red_wrote_its_attack_resumes_with_one_attack(monkeypatch: pytest.MonkeyPatch, evidence: str) -> None:
    """Red declared its attack, then battlefield died before turn.ended(red): red is not re-run."""
    eid = f.uid("ep")
    await db.execute("INSERT INTO episodes (id, seed, controller_mode, days, status, current_day) VALUES ($1,$2,'enforce',3,'running',1)", eid, SEED)
    await seed_episode(eid, SEED)
    await bus.emit(eid, 0, "episode.started", {"controller_mode": "enforce", "days": 3, "seed": SEED})
    turns: list[tuple[str, int]] = []
    crash = {"on": True}

    async def turn(agent: str, episode_id: str, day: int, mode: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        turns.append((agent, day))
        if agent == "red":
            await f.attack(episode_id, day=day, scheme_id="ghost_vendor")
            if crash["on"]:
                raise _Crash  # died mid-turn: no turn.ended(red)
        return {"ok": True, "summary": "stub", "duration_sec": 0}

    async def audit(*_: Any, **__: Any) -> dict[str, Any]:
        return {"ok": True, "summary": "stub"}

    monkeypatch.setattr(agents, "turn", turn)
    monkeypatch.setattr(agents, "audit", audit)
    with pytest.raises(_Crash):
        await runner.run_day(eid)
    assert await _count(eid, "turn.ended", 1) == 0
    if evidence == "attack_only":  # e.g. events from before turn.started was recorded: the attack row alone is enough
        await db.execute("DELETE FROM events WHERE episode_id=$1 AND type='turn.started' AND day=1", eid)

    runner._states.pop(eid, None)
    await main.recover_after_restart()
    crash["on"] = False
    turns.clear()
    await runner.resume(eid)
    task = runner.state(eid).task
    assert task is not None
    await task
    assert await db.fetchval("SELECT COUNT(*) FROM attacks WHERE episode_id=$1 AND day_launched=1", eid) == 1
    assert [t for t in turns if t[1] == 1] == [("green", 1)]  # red skipped, green ran
    assert ("red", 2) in turns  # the next day is normal
    runner._states.pop(eid, None)
