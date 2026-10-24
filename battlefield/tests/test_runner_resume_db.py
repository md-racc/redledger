"""DB: a day interrupted by a battlefield restart is resumed, not injected twice."""

from __future__ import annotations

from typing import Any

import pytest

from app import db, main
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
    turns: list[tuple[str, int]] = []
    crash = {"on": True}

    async def turn(agent: str, episode_id: str, day: int, mode: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        turns.append((agent, day))
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
    assert ("red", 1) in turns and ("green", 1) in turns  # the interrupted day's turns ran again
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
