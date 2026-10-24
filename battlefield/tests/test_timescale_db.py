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
        assert await timescale.setup() is False
        assert await timescale.setup() is False  # idempotent, never raises
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
    assert await timescale.setup() is True  # already ran in init_pool: idempotent
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
