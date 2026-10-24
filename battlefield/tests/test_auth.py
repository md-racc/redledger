"""Unit: role tokens (agent vs operator) + bearer + Caller headers + allow(). No DB."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app import main
from app.auth import Caller, allow, bearer, caller
from app.config import settings
from app.events import bus
from tests.factories import AGENT_TOKEN, OPERATOR_TOKEN, auth

app = FastAPI()


@app.get("/read")
def read(c: Caller = Depends(caller)) -> dict:
    return {"agent": c.agent, "episode_id": c.episode_id, "day": c.day, "hide": c.hide}


@app.post("/write")
def write(c: Caller = Depends(caller)) -> dict:
    return {"tool_use_id": c.tool_use_id}


@app.get("/red_or_operator")
def red_or_operator(c: Caller = Depends(allow("red"))) -> dict:
    return {"agent": c.agent}


@app.get("/agents_only")
def agents_only(c: Caller = Depends(allow("red", "green", operator=False))) -> dict:
    return {"agent": c.agent}


@app.get("/operator_only", dependencies=[Depends(bearer)])
def operator_only() -> dict:
    return {"ok": True}


client = TestClient(app)
real = TestClient(main.app)  # no context manager: lifespan (DB pool) never runs


def test_missing_or_bad_token_is_401() -> None:
    assert client.get("/read").status_code == 401
    assert client.get("/read", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_operator_sees_everything() -> None:
    r = client.get("/read", headers=auth())
    assert r.status_code == 200
    assert r.json() == {"agent": None, "episode_id": None, "day": None, "hide": False}


def test_agent_caller_hides_provenance() -> None:
    r = client.get("/read", headers=auth("green", episode="ep_1", day=3))
    assert r.status_code == 200
    assert r.json() == {"agent": "green", "episode_id": "ep_1", "day": 3, "hide": True}


def test_unknown_agent_is_400() -> None:
    r = client.get("/read", headers=auth("purple"))
    assert r.status_code == 400
    assert "unknown X-Agent" in r.json()["detail"]


def test_agent_without_episode_or_day_is_400() -> None:
    assert client.get("/read", headers=auth("red", episode=None)).status_code == 400
    assert client.get("/read", headers=auth("red", day=None)).status_code == 400


def test_agent_write_requires_tool_use_id() -> None:
    assert client.post("/write", headers=auth("red")).status_code == 400
    r = client.post("/write", headers=auth("red", tool_use_id="toolu_1"))
    assert r.status_code == 200 and r.json() == {"tool_use_id": "toolu_1"}


def test_operator_write_needs_no_tool_use_id() -> None:
    assert client.post("/write", headers=auth()).status_code == 200


def test_allow_rejects_other_agents_with_403() -> None:
    assert client.get("/red_or_operator", headers=auth("red")).status_code == 200
    assert client.get("/red_or_operator", headers=auth("blue")).status_code == 403
    assert client.get("/red_or_operator", headers=auth()).status_code == 200


def test_allow_operator_false_rejects_operator() -> None:
    assert client.get("/agents_only", headers=auth()).status_code == 403
    assert client.get("/agents_only", headers=auth("green")).status_code == 200
    assert client.get("/agents_only", headers=auth("blue")).status_code == 403


# ---------- role tokens ----------


def test_operator_token_with_x_agent_is_401() -> None:
    assert client.get("/read", headers=auth("red", token=OPERATOR_TOKEN)).status_code == 401
    assert client.post("/write", headers=auth("red", tool_use_id="tu_1", token=OPERATOR_TOKEN)).status_code == 401
    assert client.get("/operator_only", headers=auth("red", token=OPERATOR_TOKEN)).status_code == 401


def test_agent_token_without_x_agent_is_401() -> None:
    assert client.get("/read", headers=auth(token=AGENT_TOKEN)).status_code == 401
    assert client.post("/write", headers=auth(token=AGENT_TOKEN)).status_code == 401
    assert client.get("/operator_only", headers=auth(token=AGENT_TOKEN)).status_code == 401


def test_token_check_precedes_header_validation() -> None:
    # a wrong-role token is 401 even when the agent headers are also bad
    assert client.get("/read", headers=auth("purple", token=OPERATOR_TOKEN)).status_code == 401
    assert client.get("/read", headers=auth("red", episode=None, token=OPERATOR_TOKEN)).status_code == 401


def test_malformed_authorization_is_401() -> None:
    assert client.get("/read", headers={"Authorization": OPERATOR_TOKEN}).status_code == 401
    assert client.get("/read", headers={"Authorization": f"Basic {OPERATOR_TOKEN}"}).status_code == 401


def test_bearer_is_operator_only() -> None:
    assert client.get("/operator_only", headers=auth()).status_code == 200
    r = client.get("/operator_only", headers=auth("blue"))  # right token for an agent, wrong route
    assert r.status_code == 403
    assert client.get("/operator_only").status_code == 401


def test_legacy_equal_tokens_keep_both_roles_working(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "agent_token", "legacy")
    monkeypatch.setattr(settings, "operator_token", "legacy")
    assert client.get("/read", headers=auth("green", token="legacy")).json()["agent"] == "green"
    assert client.get("/read", headers=auth(token="legacy")).json()["agent"] is None
    assert client.get("/operator_only", headers=auth(token="legacy")).status_code == 200
    assert client.get("/operator_only", headers=auth("green", token="legacy")).status_code == 403
    assert client.get("/read", headers=auth(token="other")).status_code == 401


# ---------- real routes ----------


@pytest.fixture
def history(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    calls: list[tuple] = []

    async def fake_history(episode_id: str, after_id: int = 0, limit: int = 500) -> list[dict[str, Any]]:
        calls.append((episode_id, after_id, limit))
        return [{"id": 1, "type": "day.started"}]

    monkeypatch.setattr(bus, "history", fake_history)
    return calls


def test_get_events_is_operator_only(history: list) -> None:
    assert real.get("/api/events", params={"episode_id": "ep_1"}, headers=auth("blue")).status_code == 403
    assert real.get("/api/events", params={"episode_id": "ep_1"}, headers=auth("red", token=OPERATOR_TOKEN)).status_code == 401
    assert real.get("/api/events", params={"episode_id": "ep_1"}, headers=auth(token=AGENT_TOKEN)).status_code == 401
    assert history == []
    r = real.get("/api/events", params={"episode_id": "ep_1", "after_id": 5}, headers=auth())
    assert r.status_code == 200 and r.json() == [{"id": 1, "type": "day.started"}]
    assert history == [("ep_1", 5, 500)]


def test_post_inputs_accepts_both_roles() -> None:
    body = {"episode_id": "ep_1", "target": "purple"}  # 422 is raised after auth, before the DB
    assert real.post("/api/inputs", json=body, headers=auth()).status_code == 422
    assert real.post("/api/inputs", json=body, headers=auth("blue", tool_use_id="tu_1")).status_code == 422
    assert real.post("/api/inputs", json=body, headers=auth(token=AGENT_TOKEN)).status_code == 401
    assert real.post("/api/inputs", json=body, headers=auth("blue", tool_use_id="tu_1", token=OPERATOR_TOKEN)).status_code == 401


def test_control_plane_rejects_agents() -> None:
    assert real.get("/api/episodes", headers=auth(token=AGENT_TOKEN)).status_code == 401
    assert real.get("/api/episodes", headers=auth("red")).status_code == 403
