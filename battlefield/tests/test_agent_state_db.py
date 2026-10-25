"""DB: PUT /api/state/{key} is audited like every agent write (AGENTS.md invariant 5)."""

from __future__ import annotations

import json

import httpx
import pytest

from app import db
from app.main import app
from tests import factories as f

pytestmark = pytest.mark.usefixtures("pg")


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bf", timeout=30)


async def test_put_state_writes_one_audit_row_with_the_key_not_the_value(episode: str) -> None:
    value = {"plan": "x" * 500, "n": 3}
    async with _client() as cl:
        r = await cl.put("/api/state/memory", json=value, headers=f.auth("red", episode=episode, day=2, tool_use_id="tu_state_1"))
        assert r.status_code == 200 and r.json() == {"ok": True}
        assert (await cl.get("/api/state/memory", headers=f.auth("red", episode=episode, day=2))).json() == value
    rows = await db.fetch("SELECT agent, day, action, tool_use_id, args, result, http_status FROM audit_log WHERE episode_id=$1", episode)
    assert len(rows) == 1
    (row,) = rows
    assert (row["agent"], row["day"], row["action"], row["tool_use_id"], row["http_status"]) == ("red", 2, "state.put", "tu_state_1", 200)
    assert row["args"] == {"key": "memory", "bytes": len(json.dumps(value))}  # size only, never the value
    assert row["result"] == {"ok": True}
