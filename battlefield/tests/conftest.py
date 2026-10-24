"""Shared fixtures. Owner: Dev Ad.

Two tiers:
  - unit tests: no database. They use the FastAPI app without running its lifespan (TestClient
    without the context manager, or httpx ASGITransport) and monkeypatch the DB-touching seams.
  - DB tests: request the `pg` fixture. Skipped unless TEST_DATABASE_URL points at a Postgres 16
    the tests may write to. Each test gets a fresh episode id, so tests never see each other's rows.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest

from app import db, turns
from app.config import settings
from tests.factories import AGENT_TOKEN, OPERATOR_TOKEN, uid


@pytest.fixture(autouse=True)
def _tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "agent_token", AGENT_TOKEN)
    monkeypatch.setattr(settings, "operator_token", OPERATOR_TOKEN)


@pytest.fixture(autouse=True)
def _no_turn_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests call agent write routes directly, outside any orchestrator turn. The active-turn guard
    (app/turns.py) has its own tests, which switch it back on with the `turn_guard` fixture."""
    monkeypatch.setattr(turns, "ENFORCE", False)


@pytest.fixture
def turn_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(turns, "ENFORCE", True)


# ---------- DB tier ----------


@pytest.fixture
async def pg(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    """Function-scoped asyncpg pool on TEST_DATABASE_URL (same event loop as the test)."""
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    monkeypatch.setattr(settings, "database_url", url)
    # force the fallback path in apply_schema: contracts/schema.sql (+ contracts/ext/*/*.sql)
    monkeypatch.setattr(settings, "schema_path", "/nonexistent/schema.sql")
    await db.init_pool()
    try:
        yield
    finally:
        await db.close_pool()
        monkeypatch.setattr(db, "_pool", None)


@pytest.fixture
async def episode(pg: None) -> str:
    eid = uid("ep")
    await db.execute("INSERT INTO episodes (id, seed, controller_mode) VALUES ($1, 42, 'enforce')", eid)
    return eid
