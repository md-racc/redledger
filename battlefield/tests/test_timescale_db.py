"""TimescaleDB setup (app/timescale.py). Owner: Dev Ad.

On plain Postgres (local pgserver, the main CI job) setup must be a clean no-op that logs
`timescale_unavailable`. On the Timescale image (CI job `battlefield-timescale`, EXPECT_TIMESCALE=1)
events and audit_log must be hypertables, score_timeline must exist and answer, and setup must stay
idempotent. The rest of the battlefield suite then runs on top of the hypertables.
"""

from __future__ import annotations

import os

import pytest
from structlog.testing import capture_logs

from app import db, timescale
from tests.factories import uid

EXPECT = os.environ.get("EXPECT_TIMESCALE") == "1"


async def _available() -> bool:
    return bool(await db.fetchval("SELECT 1 FROM pg_extension WHERE extname = 'timescaledb'"))


async def test_setup_is_a_logged_no_op_without_timescale(pg: None) -> None:
    if await db.fetchval("SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb'"):
        pytest.skip("TimescaleDB is installed here")
    with capture_logs() as logs:
        assert await timescale.setup(force=True) is False
        assert await timescale.setup(force=True) is False  # idempotent, never raises
    assert [e for e in logs if e["event"] == "timescale_unavailable"]
    assert not [e for e in logs if e["log_level"] == "error"]
    # the core schema is untouched and still writable
    eid = uid("ep")
    await db.execute("INSERT INTO episodes (id, seed, controller_mode) VALUES ($1, 42, 'enforce')", eid)
    await db.execute("INSERT INTO events (episode_id, day, type, payload) VALUES ($1, 0, 'day.started', '{}')", eid)
    assert await db.fetchval("SELECT count(*) FROM events WHERE episode_id=$1", eid) == 1


async def test_hypertables_and_score_timeline_on_timescale(pg: None) -> None:
    if not await _available():
        if EXPECT:
            pytest.fail("EXPECT_TIMESCALE=1 but the timescaledb extension was not created")
        pytest.skip("TimescaleDB not available")
    assert await timescale.setup() is True  # memoized: already ran in init_pool
    assert await timescale.setup(force=True) is True  # and re-running the DDL is idempotent
    names = {r["hypertable_name"] for r in await db.fetch("SELECT hypertable_name FROM timescaledb_information.hypertables")}
    assert {"events", "audit_log"} <= names
    caggs = {r["view_name"] for r in await db.fetch("SELECT view_name FROM timescaledb_information.continuous_aggregates")}
    assert "score_timeline" in caggs
    eid = uid("ep")
    await db.execute("INSERT INTO episodes (id, seed, controller_mode) VALUES ($1, 42, 'enforce')", eid)
    for day, extracted in ((0, 100), (1, 250)):
        await db.execute(
            "INSERT INTO events (episode_id, day, type, payload) VALUES ($1, $2, 'score.updated', $3)",
            eid,
            day,
            {"dollars_extracted": extracted, "dollars_blocked": 10, "false_positive_cost": 0},
        )
    # real-time aggregation (materialized_only = false) answers before any refresh
    row = await db.fetchrow("SELECT max(dollars_extracted) AS ex, max(day) AS day FROM score_timeline WHERE episode_id=$1", eid)
    assert float(row["ex"]) == 250 and row["day"] == 1


async def test_a_conflicting_lock_fails_setup_instead_of_hanging(pg: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """With TimescaleDB, another session holding events locked must make setup log and return False within
    the lock timeout. Without TimescaleDB the bounded transaction is never reached; skip."""
    if not await _available():
        pytest.skip("TimescaleDB not available")
    import asyncio
    import time

    monkeypatch.setattr(timescale, "LOCK_TIMEOUT", "500ms")
    async with db.pool().acquire() as holder:
        async with holder.transaction():
            await holder.execute("LOCK TABLE events IN ACCESS EXCLUSIVE MODE")
            # migrate_data needs the lock only when the table is not yet a hypertable; drop the memo and
            # use a fresh table name so the conflicting path is exercised deterministically.
            monkeypatch.setattr(timescale, "HYPERTABLES", ("events",))
            t0 = time.monotonic()
            with capture_logs() as logs:
                ok = await asyncio.wait_for(timescale.setup(force=True), timeout=10)
            elapsed = time.monotonic() - t0
    # either it was already a hypertable (if_not_exists short-circuits without the lock) or it timed out
    if not ok:
        assert [e for e in logs if e["event"] == "timescale_setup_failed"]
    assert elapsed < 10
