"""DB: POST /api/inputs — agents stay inside their own episode and are audited; the operator is unchanged."""

from __future__ import annotations

import uuid

import httpx
import pytest

from app import db
from app.main import app
from tests import factories as f

pytestmark = pytest.mark.usefixtures("pg")


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bf", timeout=30)


def _h(agent: str, episode: str) -> dict[str, str]:
    return f.auth(agent, episode=episode, day=1, tool_use_id=f"tu_{uuid.uuid4().hex}")


async def _inputs(episode: str) -> list:
    return await db.fetch("SELECT target, source, payload FROM inputs WHERE episode_id=$1 ORDER BY id", episode)


async def _audit(episode: str) -> list:
    return await db.fetch("SELECT agent, action, http_status, result FROM audit_log WHERE episode_id=$1 ORDER BY id", episode)


async def test_agent_input_into_its_own_episode_is_queued_and_audited(episode: str) -> None:
    async with _client() as cl:
        r = await cl.post("/api/inputs", json={"episode_id": episode, "target": "green", "payload": {"note": "hi"}}, headers=_h("red", episode))
    assert r.status_code == 201
    rows = await _inputs(episode)
    assert [(x["target"], x["source"], x["payload"]) for x in rows] == [("green", "red", {"note": "hi"})]
    audit = await _audit(episode)
    assert [(x["agent"], x["action"], x["http_status"]) for x in audit] == [("red", "inputs.post", 201)]
    assert audit[0]["result"] == {"id": r.json()["id"]}


async def test_agent_input_into_another_episode_is_refused_and_audited(episode: str) -> None:
    other = f.uid("ep")
    await db.execute("INSERT INTO episodes (id, seed, controller_mode, days) VALUES ($1, 1, 'enforce', 3)", other)
    async with _client() as cl:
        r = await cl.post("/api/inputs", json={"episode_id": other, "target": "green", "payload": {}}, headers=_h("red", episode))
    assert r.status_code == 403
    assert await _inputs(episode) == [] and await _inputs(other) == []
    audit = await _audit(episode)
    assert [(x["agent"], x["action"], x["http_status"]) for x in audit] == [("red", "inputs.post", 403)]
    assert audit[0]["result"] == {"error": "episode_id must match X-Episode"}


async def test_agent_bad_target_is_audited(episode: str) -> None:
    async with _client() as cl:
        r = await cl.post("/api/inputs", json={"episode_id": episode, "target": "purple"}, headers=_h("blue", episode))
    assert r.status_code == 422
    assert [(x["agent"], x["http_status"]) for x in await _audit(episode)] == [("blue", 422)]


async def test_operator_may_address_any_episode_and_is_not_audited(episode: str) -> None:
    async with _client() as cl:
        r = await cl.post("/api/inputs", json={"episode_id": episode, "target": "red", "source": "judge", "payload": {"x": 1}}, headers=f.auth())
    assert r.status_code == 201
    assert [(x["target"], x["source"]) for x in await _inputs(episode)] == [("red", "judge")]
    assert await _audit(episode) == []
