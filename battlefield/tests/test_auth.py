"""Unit: bearer + Caller headers + allow(). No DB."""

from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.auth import Caller, allow, caller
from tests.factories import auth

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


client = TestClient(app)


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
