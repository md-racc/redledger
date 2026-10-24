"""TimescaleDB, when the database has it. Owner: Dev Ad.

`events` and `audit_log` are append-only and read on a time axis, so on a Timescale image they become
hypertables (keyed `(id, ts)` in contracts/schema.sql for this), and a continuous aggregate,
`score_timeline`, keeps per-episode score over time from `score.updated` events.

Everything here is optional and guarded: on a plain postgres:16 image `setup()` logs
`timescale_unavailable` and returns False; any failure is logged and startup continues. A data
directory created by a plain image has no `shared_preload_libraries = 'timescaledb'`, so the first
boot on the Timescale image sets it with ALTER SYSTEM and logs `timescale_restart_required`; the
hypertables follow on the next Postgres restart. Every statement is idempotent.
"""

from __future__ import annotations

import structlog

from . import db

log = structlog.get_logger(__name__)

HYPERTABLES = ("events", "audit_log")

# Bounds on setup's DDL (AGENTS.md §3 inv. 10): create_hypertable(migrate_data) takes ACCESS EXCLUSIVE on
# events/audit_log, so a conflicting lock must fail setup (logged), never hang startup.
LOCK_TIMEOUT = "5s"
STATEMENT_TIMEOUT = "120s"  # generous: migrate_data copies existing rows into chunks

_done: set[int] = set()  # id(pool) for which setup already ran in this process

SCORE_TIMELINE = """
CREATE MATERIALIZED VIEW IF NOT EXISTS score_timeline
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT episode_id,
       time_bucket(INTERVAL '1 minute', ts) AS bucket,
       max(day) AS day,
       max((payload->>'dollars_extracted')::numeric) AS dollars_extracted,
       max((payload->>'dollars_blocked')::numeric) AS dollars_blocked,
       max((payload->>'false_positive_cost')::numeric) AS false_positive_cost
FROM events
WHERE type = 'score.updated'
GROUP BY episode_id, bucket
WITH NO DATA
"""


async def setup(*, force: bool = False) -> bool:
    """Make the hypertables and the continuous aggregate if TimescaleDB is usable. Never raises.
    Runs once per pool per process (`force=True` re-runs it, e.g. to check idempotency)."""
    key = id(db.pool())
    if key in _done and not force:
        return True
    try:
        async with db.pool().acquire() as conn:
            if not await conn.fetchval("SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb'"):
                log.info("timescale_unavailable", reason="extension not installed (plain postgres image)")
                return False
            preload = await conn.fetchval("SELECT current_setting('shared_preload_libraries')") or ""
            if "timescaledb" not in [p.strip() for p in preload.split(",")]:
                # a data dir initialised by a plain image: preload it for the next start, nothing more now
                libs = ",".join([p.strip() for p in preload.split(",") if p.strip()] + ["timescaledb"])
                await conn.execute(f"ALTER SYSTEM SET shared_preload_libraries = '{libs}'")
                await conn.execute("ALTER SYSTEM SET timescaledb.telemetry_level = 'off'")
                log.warning("timescale_restart_required", shared_preload_libraries=libs)
                return False
            await conn.execute("ALTER SYSTEM SET timescaledb.telemetry_level = 'off'")  # not allowed in a transaction
            await conn.execute("SELECT pg_reload_conf()")
            async with conn.transaction():
                await conn.execute(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'")
                await conn.execute(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'")
                await conn.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
                for table in HYPERTABLES:
                    await conn.execute(f"SELECT create_hypertable('{table}', 'ts', migrate_data => true, if_not_exists => true)")
            log.info("timescale_hypertables", tables=list(HYPERTABLES))
    except Exception as e:  # optional feature (incl. a lock/statement timeout): log and carry on
        log.error("timescale_setup_failed", error=str(e))
        return False
    await _score_timeline()
    _done.add(key)
    return True


async def _score_timeline() -> None:
    try:
        async with db.pool().acquire() as conn:
            await conn.execute(f"SET lock_timeout = '{LOCK_TIMEOUT}'")
            await conn.execute(f"SET statement_timeout = '{STATEMENT_TIMEOUT}'")
            await conn.execute(SCORE_TIMELINE)  # CREATE MATERIALIZED VIEW ... continuous: not in a transaction
            await conn.execute(
                "SELECT add_continuous_aggregate_policy('score_timeline', start_offset => INTERVAL '30 days', "
                "end_offset => INTERVAL '1 minute', schedule_interval => INTERVAL '1 minute', if_not_exists => true)"
            )
            await conn.execute("RESET lock_timeout")
            await conn.execute("RESET statement_timeout")
        log.info("timescale_score_timeline")
    except Exception as e:  # the hypertables stand without it
        log.error("timescale_score_timeline_failed", error=str(e))
