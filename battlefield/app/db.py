"""asyncpg pool + tiny helpers. Raw SQL on purpose: one weekend, one schema file. Owner: Dev Ad."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import asyncpg
import structlog

from .config import settings

log = structlog.get_logger(__name__)

_pool: asyncpg.Pool | None = None

# never shown to agents. created_by distinguishes seed vs mid-episode vendors, which is provenance.
HIDDEN_COLUMNS = {"origin", "attack_id", "origin_of_source", "created_by"}


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


async def init_pool() -> None:
    global _pool
    _pool = await asyncpg.create_pool(settings.database_url, min_size=2, max_size=10, init=_init_conn)
    await apply_schema()
    from . import timescale  # lazy: it uses this module's pool

    await timescale.setup()  # hypertables + score_timeline when the image has TimescaleDB; else a log line


async def _init_conn(conn: asyncpg.Connection) -> None:
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")
    await conn.set_type_codec("json", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def close_pool() -> None:
    if _pool:
        await _pool.close()


def pool() -> asyncpg.Pool:
    assert _pool is not None, "db not initialised"
    return _pool


async def apply_schema() -> None:
    path = Path(settings.schema_path)
    if not path.exists():
        path = Path(__file__).resolve().parents[2] / "contracts" / "schema.sql"
    sql = path.read_text()
    async with pool().acquire() as conn:
        await conn.execute(sql)
        # team-owned extension schemas: contracts/ext/<area>/*.sql, tables prefixed <area>_
        ext_root = path.resolve().parent / "ext"
        for ext in sorted(ext_root.glob("*/*.sql")) if ext_root.exists() else []:
            try:
                await conn.execute(ext.read_text())
                log.info("ext_schema_applied", path=str(ext.relative_to(ext_root)))
            except Exception as e:  # a broken extension must not take the core down
                log.error("ext_schema_failed", path=str(ext), error=str(e))
    log.info("schema_applied", path=str(path))


def _jsonable(v: Any) -> Any:
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def row_to_dict(row: asyncpg.Record | None, *, hide: bool = False) -> dict[str, Any] | None:
    if row is None:
        return None
    d = {k: _jsonable(v) for k, v in dict(row).items()}
    if hide:
        for k in HIDDEN_COLUMNS:
            d.pop(k, None)
    return d


def rows_to_list(rows: list[asyncpg.Record], *, hide: bool = False) -> list[dict[str, Any]]:
    return [row_to_dict(r, hide=hide) for r in rows]  # type: ignore[misc]


async def fetch(sql: str, *args: Any) -> list[asyncpg.Record]:
    async with pool().acquire() as conn:
        return await conn.fetch(sql, *args)


async def fetchrow(sql: str, *args: Any) -> asyncpg.Record | None:
    async with pool().acquire() as conn:
        return await conn.fetchrow(sql, *args)


async def fetchval(sql: str, *args: Any) -> Any:
    async with pool().acquire() as conn:
        return await conn.fetchval(sql, *args)


async def execute(sql: str, *args: Any) -> str:
    async with pool().acquire() as conn:
        return await conn.execute(sql, *args)
