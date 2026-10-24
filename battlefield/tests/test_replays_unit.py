"""Unit: replay fixture parsing, ids, score, failure/cancel bookkeeping, agent guard (no DB)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import db
from app.api import control
from app.auth import TICKET_SCOPE_RE
from app.events import bus
from app.main import app
from tests.factories import auth


@pytest.mark.parametrize("name", ["sample-enforce-4d", "weird name.v2", "x" * 200])
def test_new_replay_id_is_unique_and_a_valid_ticket_scope(name: str) -> None:
    a, b = control.new_replay_id(name), control.new_replay_id(name)
    assert a != b
    assert a.startswith(control.REPLAY_PREFIX) and control.is_replay(a)
    assert TICKET_SCOPE_RE.fullmatch(a) and len(a) <= 64


def test_live_episode_ids_are_not_replays() -> None:
    assert not control.is_replay("ep_e5c5c1a83029")


def test_load_fixture_skips_blank_and_ping_and_normalizes(tmp_path: Path) -> None:
    p = tmp_path / "f.jsonl"
    p.write_text(
        '{"type": "episode.started", "payload": {}}\n\n{"type": "ping"}\n'
        '{"type": "day.started", "day": 2, "payload": null, "agent": null}\n{"type": "x.red.y", "day": null, "agent": "red"}\n'
    )
    evs = control._load_fixture(p)
    assert [(e["type"], e["day"], e["payload"], e["agent"]) for e in evs] == [
        ("episode.started", 0, {}, "battlefield"),
        ("day.started", 2, {}, None),
        ("x.red.y", 0, {}, "red"),
    ]


@pytest.mark.parametrize(
    "bad",
    [
        "nope",
        "[1, 2]",
        '{"day": 1}',
        '{"type": ""}',
        '{"type": 5}',
        '{"type": "x", "day": "z"}',
        '{"type": "x", "day": "2"}',
        '{"type": "x", "day": 1.5}',
        '{"type": "x", "day": true}',
        f'{{"type": "x", "day": {2**31 - 1}}}',
        f'{{"type": "x", "day": {-(2**31) - 1}}}',
        '{"type": "x", "payload": [1]}',
        '{"type": "x", "payload": "s"}',
        '{"type": "x", "agent": 3}',
        '{"type": "x", "agent": {"a": 1}}',
        '{"type": "x", "payload": {"t": "a\\u0000b"}}',
        '{"type": "x", "payload": {"l": [{"a\\u0000": 1}]}}',
    ],
)
def test_load_fixture_rejects_bad_lines(tmp_path: Path, bad: str) -> None:
    p = tmp_path / "f.jsonl"
    p.write_text('{"type": "episode.started"}\n' + bad + "\n")
    with pytest.raises(HTTPException) as e:
        control._load_fixture(p)
    assert e.value.status_code == 422 and "line 2" in e.value.detail


def test_load_fixture_accepts_int_range_edges(tmp_path: Path) -> None:
    p = tmp_path / "f.jsonl"
    p.write_text(f'{{"type": "a", "day": {-(2**31)}}}\n{{"type": "b", "day": {2**31 - 2}}}\n')
    assert [e["day"] for e in control._load_fixture(p)] == [-(2**31), 2**31 - 2]


@pytest.mark.parametrize("kind", ["dir", "binary", "missing"])
def test_load_fixture_unreadable_is_422(tmp_path: Path, kind: str) -> None:
    p = tmp_path / "f.jsonl"
    if kind == "dir":
        p.mkdir()
    elif kind == "binary":
        p.write_bytes(b'{"type": "x"}\n\xff\xfe\n')
    with pytest.raises(HTTPException) as e:
        control._load_fixture(p)
    assert e.value.status_code == 422


# ---------- score from events ----------


@pytest.mark.parametrize(
    ("row", "expected_blocked"),
    [
        (None, 0.0),
        ({"type": "score.updated", "payload": [1, 2]}, 0.0),
        ({"type": "score.updated", "payload": {"dollars_blocked": "lots", "attacks_launched": True}}, 0.0),
        ({"type": "score.updated", "payload": {"dollars_blocked": 12.5, "junk": 1}}, 12.5),
        ({"type": "episode.ended", "payload": {"final_score": "n/a"}}, 0.0),
        ({"type": "episode.ended", "payload": {"final_score": {"dollars_blocked": 7}}}, 7),
    ],
)
async def test_replay_score_keeps_only_well_typed_fields(monkeypatch: pytest.MonkeyPatch, row: dict | None, expected_blocked: float) -> None:
    async def fake_fetchrow(*a: Any) -> dict | None:
        return row

    monkeypatch.setattr(db, "fetchrow", fake_fetchrow)
    sc = await control.replay_score("replay_x")
    assert set(sc) == set(control._ZERO_SCORE)
    assert sc["dollars_blocked"] == expected_blocked
    assert sc["attacks_launched"] == 0


# ---------- failure / cancellation bookkeeping ----------


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> dict[str, list]:
    rec: dict[str, list] = {"sql": [], "emits": []}

    async def fake_execute(sql: str, *args: Any) -> str:
        rec["sql"].append((sql, args))
        return "OK"

    async def fake_emit(episode_id: str, day: int, type_: str, payload: dict | None = None, *, agent: str | None = "battlefield") -> dict:
        if type_ == "error" and day != 0:
            raise ValueError("value out of int32 range")  # what asyncpg says for an out-of-range day
        rec["emits"].append((episode_id, day, type_, payload))
        return {}

    monkeypatch.setattr(db, "execute", fake_execute)
    monkeypatch.setattr(bus, "emit", fake_emit)
    return rec


async def test_failure_event_falls_back_to_day_0(recorder: dict[str, list]) -> None:
    await control._record_failure("replay_x", 99, "boom")
    assert any("status='failed'" in sql for sql, _ in recorder["sql"])
    assert recorder["emits"] == [("replay_x", 0, "error", {"where": "replay", "message": "boom"})]


async def test_cancelled_replay_marks_failed_and_reraises(recorder: dict[str, list], monkeypatch: pytest.MonkeyPatch) -> None:
    evs = [
        {"type": "day.started", "day": 0, "payload": {}, "agent": "battlefield", "ts": "2026-01-01T00:00:00+00:00"},
        {"type": "day.ended", "day": 0, "payload": {}, "agent": "battlefield", "ts": "2026-01-01T00:00:10+00:00"},
    ]
    monkeypatch.setattr(control, "_replay_tasks", set())
    task = asyncio.create_task(control._stream_fixture(evs, "replay_c", 1.0))  # sleeps 3 s (capped) before event 2
    control._replay_tasks.add(task)
    await asyncio.sleep(0.05)
    await control.shutdown_replays(timeout=2)
    assert task.cancelled()
    assert [e[2] for e in recorder["emits"]] == ["day.started", "error"]
    assert "cancelled" in recorder["emits"][-1][3]["message"]
    assert any("status='failed'" in sql for sql, _ in recorder["sql"])
    assert not any("status='finished'" in sql for sql, _ in recorder["sql"])


async def test_shutdown_with_no_replays_is_a_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(control, "_replay_tasks", set())
    await control.shutdown_replays()


# ---------- agents never touch replay episodes ----------


@pytest.mark.parametrize(("method", "path"), [("GET", "/api/vendors"), ("POST", "/api/invoices/inv_1/pay"), ("POST", "/api/events")])
def test_agent_requests_into_replay_episodes_are_403(method: str, path: str) -> None:
    client = TestClient(app)  # no lifespan: the 403 happens before any DB access
    r = client.request(
        method, path, json=[] if path == "/api/events" else {}, headers=auth("green", episode="replay_sample_ab12cd34", day=1, tool_use_id="tu_1")
    )
    assert r.status_code == 403
    assert "replay" in r.json()["detail"]


def test_auth_replay_guard_matches_control_prefix() -> None:
    assert control.REPLAY_PREFIX == "replay_"
