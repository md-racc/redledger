"""Unit: POST /api/ws/ticket and WS /api/ws ticket/token auth. No DB."""

from __future__ import annotations

import hashlib
import hmac
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


def _flip(h: str) -> str:
    return h[:-1] + ("0" if h[-1] != "0" else "1")


def test_tampered_ticket_is_rejected() -> None:
    t, exp = issue_ws_ticket("ep_1", now=NOW)
    scope, exp_s, nonce, sig = t.split(".")
    assert not verify_ws_ticket(f"{scope}.{exp_s}.{nonce}.{_flip(sig)}", "ep_1", now=NOW)
    assert not verify_ws_ticket(f"*.{exp_s}.{nonce}.{sig}", "ep_1", now=NOW)  # widened scope
    assert not verify_ws_ticket(f"{scope}.{exp + 3600}.{nonce}.{sig}", "ep_1", now=NOW)  # extended expiry
    assert verify_ws_ticket(t, "ep_1", now=NOW)


def test_tampered_nonce_is_rejected() -> None:
    t, _ = issue_ws_ticket("ep_1", now=NOW)
    scope, exp_s, nonce, sig = t.split(".")
    assert not verify_ws_ticket(f"{scope}.{exp_s}.{_flip(nonce)}.{sig}", "ep_1", now=NOW)
    assert verify_ws_ticket(t, "ep_1", now=NOW)


@pytest.mark.parametrize("bad", [lambda s: s.upper(), lambda s: s[:-1], lambda s: s + "0", lambda s: " " + s[1:], lambda s: "g" + s[1:]])
def test_noncanonical_nonce_is_rejected(bad: Any) -> None:
    t, exp = issue_ws_ticket("ep_1", now=NOW)
    scope, exp_s, nonce, _ = t.split(".")
    alt = bad(nonce)
    # even correctly signed over the altered nonce, a non-canonical nonce never verifies
    assert not verify_ws_ticket(f"{scope}.{exp_s}.{alt}.{auth_mod._ticket_sig(scope, exp, alt)}", "ep_1", now=NOW)
    assert verify_ws_ticket(t, "ep_1", now=NOW)


def test_two_tickets_same_second_differ_and_each_works_once() -> None:
    t1, exp1 = issue_ws_ticket("ep_1", now=NOW)
    t2, exp2 = issue_ws_ticket("ep_1", now=NOW)
    assert exp1 == exp2 and t1 != t2
    assert verify_ws_ticket(t1, "ep_1", now=NOW)
    assert verify_ws_ticket(t2, "ep_1", now=NOW)
    assert not verify_ws_ticket(t1, "ep_1", now=NOW)
    assert not verify_ws_ticket(t2, "ep_1", now=NOW)


def test_old_three_part_ticket_is_rejected() -> None:
    exp = NOW + WS_TICKET_TTL_SEC
    old_sig = hmac.new(OPERATOR_TOKEN.encode(), f"ep_1|{exp}".encode(), hashlib.sha256).hexdigest()
    assert not verify_ws_ticket(f"ep_1.{exp}.{old_sig}", "ep_1", now=NOW)


def test_ticket_signed_with_other_key_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "operator_token", "old-operator-token")
    t, _ = issue_ws_ticket("ep_1", now=NOW)
    monkeypatch.setattr(settings, "operator_token", OPERATOR_TOKEN)
    assert not verify_ws_ticket(t, "ep_1", now=NOW)


@pytest.mark.parametrize("junk", [None, "", "abc", "ep_1.notanint.deadbeef", "ep_1..", "...", "....", "ep_1.1.2.3.4"])
def test_malformed_ticket_is_rejected(junk: str | None) -> None:
    assert not verify_ws_ticket(junk, "ep_1", now=NOW)


def test_used_set_is_pruned_of_expired_tickets() -> None:
    t, exp = issue_ws_ticket("ep_1", now=NOW)
    nonce = t.split(".")[2]
    assert verify_ws_ticket(t, "ep_1", now=NOW)
    assert f"ep_1|{exp}|{nonce}" in auth_mod._used_tickets
    verify_ws_ticket(None, "ep_1", now=exp + 1)
    assert f"ep_1|{exp}|{nonce}" not in auth_mod._used_tickets


@pytest.mark.parametrize("spell", ["0{e}", "00{e}", "+{e}", " {e}", "{e} ", "\t{e}", "{e}\n", "{s}_{r}"])
def test_noncanonical_exp_cannot_replay(spell: str) -> None:
    t, exp = issue_ws_ticket("ep_1", now=NOW)
    scope, exp_s, nonce, sig = t.split(".")
    spelled = spell.format(e=exp_s, s=exp_s[:2], r=exp_s[2:])
    assert int(spelled) == exp  # a naive int() parse sees the same, validly signed, exp
    alt = f"{scope}.{spelled}.{nonce}.{sig}"
    assert not verify_ws_ticket(alt, "ep_1", now=NOW)  # rejected even before first use
    assert verify_ws_ticket(t, "ep_1", now=NOW)
    assert not verify_ws_ticket(alt, "ep_1", now=NOW)  # and cannot replay after it


@pytest.mark.parametrize("bad", [lambda s: s.upper(), lambda s: " " + s, lambda s: s + "00", lambda s: s[:-1]])
def test_noncanonical_sig_is_rejected(bad: Any) -> None:
    t, _ = issue_ws_ticket("ep_1", now=NOW)
    scope, exp_s, nonce, sig = t.split(".")
    assert not verify_ws_ticket(f"{scope}.{exp_s}.{nonce}.{bad(sig)}", "ep_1", now=NOW)
    assert verify_ws_ticket(t, "ep_1", now=NOW)


@pytest.mark.parametrize("scope", ["ep 1", "ep.1", "ep|1", "x" * 65, "**", " ep_1"])
def test_bad_scope_is_rejected(scope: str) -> None:
    with pytest.raises(ValueError):
        issue_ws_ticket(scope, now=NOW)
    exp = NOW + WS_TICKET_TTL_SEC
    nonce = "0123456789abcdef"
    assert not verify_ws_ticket(f"{scope}.{exp}.{nonce}.{auth_mod._ticket_sig(scope, exp, nonce)}", scope, now=NOW)


def test_scope_charset_allows_real_ids() -> None:
    for eid in ("ep_0123456789ab", "replay_sample-enforce-4d", "x" * 64):
        t, _ = issue_ws_ticket(eid, now=NOW)
        assert verify_ws_ticket(t, eid, now=NOW)


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


def test_ticket_route_rejects_bad_episode_id() -> None:
    assert client.post("/api/ws/ticket", json={"episode_id": "ep.1"}, headers=auth()).status_code == 422


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
    # the server accepts, then closes with 4401 (a pre-accept close would be an HTTP 403)
    with client.websocket_connect(url) as ws, pytest.raises(WebSocketDisconnect) as e:
        ws.receive_text()
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


def test_two_route_tickets_in_the_same_second_both_connect(history: list) -> None:
    t1 = client.post("/api/ws/ticket", json={"episode_id": "ep_1"}, headers=auth()).json()["ticket"]
    t2 = client.post("/api/ws/ticket", json={"episode_id": "ep_1"}, headers=auth()).json()["ticket"]
    assert t1 != t2
    for t in (t1, t2):
        with client.websocket_connect(f"/api/ws?episode_id=ep_1&after_id=0&ticket={t}") as ws:
            assert ws.receive_json()["id"] == 1
    assert _rejected(f"/api/ws?episode_id=ep_1&ticket={t1}") == 4401
    assert _rejected(f"/api/ws?episode_id=ep_1&ticket={t2}") == 4401


def test_ws_old_format_ticket_is_4401(history: list) -> None:
    exp = int(time.time()) + WS_TICKET_TTL_SEC
    old_sig = hmac.new(OPERATOR_TOKEN.encode(), f"ep_1|{exp}".encode(), hashlib.sha256).hexdigest()
    assert _rejected(f"/api/ws?episode_id=ep_1&ticket=ep_1.{exp}.{old_sig}") == 4401
    assert history == []


def test_ws_drops_live_duplicates_of_catch_up_frames(monkeypatch: pytest.MonkeyPatch) -> None:
    """Events emitted between subscribe and the history read are both in history and queued live."""

    def ev(i: int) -> dict[str, Any]:
        return {"id": i, "type": "day.started", "episode_id": "ep_1"}

    async def racy_history(episode_id: str, after_id: int = 0, limit: int = 500) -> list[dict[str, Any]]:
        bus._broadcast(episode_id, ev(2))  # stale: at/below after_id, the client already has it
        bus._broadcast(episode_id, ev(4))  # emitted in the window: also in the history below
        bus._broadcast(episode_id, ev(5))  # emitted after the history read: live only
        return [ev(3), ev(4)]

    monkeypatch.setattr(bus, "history", racy_history)
    with client.websocket_connect(f"/api/ws?episode_id=ep_1&after_id=2&token={OPERATOR_TOKEN}") as ws:
        got = [ws.receive_json()["id"] for _ in range(3)]
    assert got == [3, 4, 5]


def test_ws_all_episodes_stream_is_not_filtered(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_history(*a: Any, **k: Any) -> list[dict[str, Any]]:
        raise AssertionError("no history without episode_id")

    monkeypatch.setattr(bus, "history", no_history)
    real_subscribe = bus.subscribe

    def subscribe_and_queue(episode_id: str | None):
        q = real_subscribe(episode_id)
        q.put_nowait({"id": 1, "type": "day.started", "episode_id": "ep_9"})
        return q

    monkeypatch.setattr(bus, "subscribe", subscribe_and_queue)
    with client.websocket_connect(f"/api/ws?token={OPERATOR_TOKEN}") as ws:
        assert ws.receive_json()["id"] == 1
