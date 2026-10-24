"""Unit: POST /api/ws/ticket and WS /api/ws ticket/token auth. No DB."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import auth as auth_mod
from app.auth import WS_TICKET_TTL_SEC, issue_ws_ticket, verify_ws_ticket
from app.config import settings
from app.events import bus
from app.main import app
from tests.factories import AGENT_TOKEN, OPERATOR_TOKEN, auth

client = TestClient(app)  # no context manager: lifespan (DB pool) never runs
NOW = 1_800_000_000


@pytest.fixture(autouse=True)
def _fresh_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_mod, "_used_tickets", {})


# ---------- verify function ----------


def test_valid_ticket_once() -> None:
    t, exp = issue_ws_ticket("ep_1", now=NOW)
    assert exp == NOW + WS_TICKET_TTL_SEC
    assert t.startswith(f"ep_1.{exp}.")
    assert verify_ws_ticket(t, "ep_1", now=NOW + 1)


def test_reused_ticket_is_rejected() -> None:
    t, _ = issue_ws_ticket("ep_1", now=NOW)
    assert verify_ws_ticket(t, "ep_1", now=NOW)
    assert not verify_ws_ticket(t, "ep_1", now=NOW + 1)


def test_expired_ticket_is_rejected() -> None:
    t, exp = issue_ws_ticket("ep_1", now=NOW)
    assert not verify_ws_ticket(t, "ep_1", now=exp + 1)
    t2, exp2 = issue_ws_ticket("ep_1", now=NOW + 1)
    assert verify_ws_ticket(t2, "ep_1", now=exp2)  # still valid at exp itself


def test_wrong_episode_is_rejected() -> None:
    t, _ = issue_ws_ticket("ep_1", now=NOW)
    assert not verify_ws_ticket(t, "ep_2", now=NOW)
    assert not verify_ws_ticket(t, None, now=NOW)  # scoped ticket cannot subscribe to everything
    assert verify_ws_ticket(t, "ep_1", now=NOW)  # failed attempts did not burn it


def test_star_scope_matches_any_episode() -> None:
    t, _ = issue_ws_ticket(None, now=NOW)
    assert t.startswith("*.")
    assert verify_ws_ticket(t, "ep_42", now=NOW)
    t2, _ = issue_ws_ticket(None, now=NOW + 1)
    assert verify_ws_ticket(t2, None, now=NOW + 1)


def test_tampered_ticket_is_rejected() -> None:
    t, exp = issue_ws_ticket("ep_1", now=NOW)
    scope, exp_s, sig = t.rsplit(".", 2)
    flipped = sig[:-1] + ("0" if sig[-1] != "0" else "1")
    assert not verify_ws_ticket(f"{scope}.{exp_s}.{flipped}", "ep_1", now=NOW)
    assert not verify_ws_ticket(f"*.{exp_s}.{sig}", "ep_1", now=NOW)  # widened scope
    assert not verify_ws_ticket(f"{scope}.{exp + 3600}.{sig}", "ep_1", now=NOW)  # extended expiry
    assert verify_ws_ticket(t, "ep_1", now=NOW)


def test_ticket_signed_with_other_key_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "operator_token", "old-operator-token")
    t, _ = issue_ws_ticket("ep_1", now=NOW)
    monkeypatch.setattr(settings, "operator_token", OPERATOR_TOKEN)
    assert not verify_ws_ticket(t, "ep_1", now=NOW)


@pytest.mark.parametrize("junk", [None, "", "abc", "ep_1.notanint.deadbeef", "ep_1..", "..."])
def test_malformed_ticket_is_rejected(junk: str | None) -> None:
    assert not verify_ws_ticket(junk, "ep_1", now=NOW)


def test_used_set_is_pruned_of_expired_tickets() -> None:
    t, exp = issue_ws_ticket("ep_1", now=NOW)
    assert verify_ws_ticket(t, "ep_1", now=NOW)
    assert t in auth_mod._used_tickets
    verify_ws_ticket(None, "ep_1", now=exp + 1)
    assert t not in auth_mod._used_tickets


# ---------- POST /api/ws/ticket ----------


def test_ticket_route_is_operator_only() -> None:
    assert client.post("/api/ws/ticket", json={"episode_id": "ep_1"}, headers=auth("red", tool_use_id="tu_1")).status_code == 403
    assert client.post("/api/ws/ticket", json={"episode_id": "ep_1"}, headers=auth(token=AGENT_TOKEN)).status_code == 401
    assert client.post("/api/ws/ticket", json={"episode_id": "ep_1"}).status_code == 401


def test_ticket_route_issues_verifiable_ticket() -> None:
    before = int(time.time())
    r = client.post("/api/ws/ticket", json={"episode_id": "ep_1"}, headers=auth())
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"ticket", "expires_at"}
    exp = int(datetime.fromisoformat(body["expires_at"]).timestamp())
    assert before + WS_TICKET_TTL_SEC <= exp <= int(time.time()) + WS_TICKET_TTL_SEC
    assert body["ticket"].startswith(f"ep_1.{exp}.")
    assert verify_ws_ticket(body["ticket"], "ep_1")


def test_ticket_route_null_or_missing_body_is_star_scope() -> None:
    assert client.post("/api/ws/ticket", json={"episode_id": None}, headers=auth()).json()["ticket"].startswith("*.")
    assert client.post("/api/ws/ticket", headers=auth()).json()["ticket"].startswith("*.")


# ---------- WS /api/ws ----------


@pytest.fixture
def history(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    calls: list[tuple] = []

    async def fake_history(episode_id: str, after_id: int = 0, limit: int = 500) -> list[dict[str, Any]]:
        calls.append((episode_id, after_id))
        return [{"id": after_id + 1, "type": "day.started", "episode_id": episode_id}]

    monkeypatch.setattr(bus, "history", fake_history)
    return calls


def _rejected(url: str) -> int:
    with pytest.raises(WebSocketDisconnect) as e, client.websocket_connect(url):
        pass
    return e.value.code


def test_ws_with_ticket_round_trip(history: list) -> None:
    t = client.post("/api/ws/ticket", json={"episode_id": "ep_1"}, headers=auth()).json()["ticket"]
    with client.websocket_connect(f"/api/ws?episode_id=ep_1&after_id=3&ticket={t}") as ws:
        assert ws.receive_json() == {"id": 4, "type": "day.started", "episode_id": "ep_1"}
    assert history == [("ep_1", 3)]
    assert _rejected(f"/api/ws?episode_id=ep_1&ticket={t}") == 4401  # single use


def test_ws_with_operator_token(history: list) -> None:
    with client.websocket_connect(f"/api/ws?episode_id=ep_1&token={OPERATOR_TOKEN}") as ws:
        assert ws.receive_json()["type"] == "day.started"


def test_ws_rejections(history: list) -> None:
    assert _rejected("/api/ws?episode_id=ep_1") == 4401
    assert _rejected(f"/api/ws?episode_id=ep_1&token={AGENT_TOKEN}") == 4401
    t = client.post("/api/ws/ticket", json={"episode_id": "ep_1"}, headers=auth()).json()["ticket"]
    assert _rejected(f"/api/ws?episode_id=ep_2&ticket={t}") == 4401
    expired, _ = issue_ws_ticket("ep_1", now=time.time() - WS_TICKET_TTL_SEC - 5)
    assert _rejected(f"/api/ws?episode_id=ep_1&ticket={expired}") == 4401
    assert history == []
