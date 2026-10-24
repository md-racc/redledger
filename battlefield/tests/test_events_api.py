"""Unit: POST /api/events validates types before touching the DB."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.events import bus
from app.main import app
from tests.factories import auth

client = TestClient(app)  # no context manager: lifespan (DB pool) never runs


@pytest.fixture
def emitted(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    calls: list[tuple] = []

    async def fake_emit_many(episode_id: str, day: int, agent: str, items: list[dict[str, Any]]) -> int:
        calls.append((episode_id, day, agent, items))
        return len(items)

    monkeypatch.setattr(bus, "emit_many", fake_emit_many)
    return calls


@pytest.mark.parametrize("bad", ["gate.verdict", "attack.launched", "score.updated", "ledger.mutation", "agentx.thing"])
def test_non_agent_types_are_422(bad: str, emitted: list) -> None:
    r = client.post("/api/events", json=[{"type": "agent.thinking", "payload": {}}, {"type": bad}], headers=auth("red", tool_use_id="tu_1"))
    assert r.status_code == 422
    assert bad in r.json()["detail"]
    assert emitted == []


def test_agent_and_custom_types_are_accepted(emitted: list) -> None:
    items = [{"type": "agent.thinking", "payload": {"text": "hi"}}, {"type": "agent.tool_call"}, {"type": "x.red.plan", "payload": {"n": 1}}]
    r = client.post("/api/events", json=items, headers=auth("red", episode="ep_9", day=2, tool_use_id="tu_1"))
    assert r.status_code == 202
    assert r.json() == {"accepted": 3}
    assert len(emitted) == 1
    ep, day, agent, sent = emitted[0]
    assert (ep, day, agent) == ("ep_9", 2, "red")
    assert [i["type"] for i in sent] == ["agent.thinking", "agent.tool_call", "x.red.plan"]


def test_operator_may_not_post_events(emitted: list) -> None:
    r = client.post("/api/events", json=[{"type": "agent.thinking"}], headers=auth())
    assert r.status_code == 403
    assert emitted == []


def test_malformed_body_is_422(emitted: list) -> None:
    r = client.post("/api/events", json=[{"payload": {}}], headers=auth("blue", tool_use_id="tu_1"))
    assert r.status_code == 422
    assert emitted == []
