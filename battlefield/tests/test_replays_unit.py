"""Unit: replay fixture parsing and replay episode ids (no DB)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from app.api import control
from app.auth import TICKET_SCOPE_RE


@pytest.mark.parametrize("name", ["sample-enforce-4d", "weird name.v2", "x" * 200])
def test_new_replay_id_is_unique_and_a_valid_ticket_scope(name: str) -> None:
    a, b = control.new_replay_id(name), control.new_replay_id(name)
    assert a != b
    assert a.startswith(control.REPLAY_PREFIX) and control.is_replay(a)
    assert TICKET_SCOPE_RE.fullmatch(a) and len(a) <= 64


def test_live_episode_ids_are_not_replays() -> None:
    assert not control.is_replay("ep_e5c5c1a83029")


def test_load_fixture_skips_blank_and_ping_and_normalizes_day(tmp_path: Path) -> None:
    p = tmp_path / "f.jsonl"
    p.write_text('{"type": "episode.started", "payload": {}}\n\n{"type": "ping"}\n{"type": "day.started", "day": "2"}\n')
    evs = control._load_fixture(p)
    assert [(e["type"], e["day"]) for e in evs] == [("episode.started", 0), ("day.started", 2)]


@pytest.mark.parametrize("bad", ["nope", "[1, 2]", '{"day": 1}', '{"type": "x", "day": "z"}'])
def test_load_fixture_rejects_bad_lines(tmp_path: Path, bad: str) -> None:
    p = tmp_path / "f.jsonl"
    p.write_text('{"type": "episode.started"}\n' + bad + "\n")
    with pytest.raises(HTTPException) as e:
        control._load_fixture(p)
    assert e.value.status_code == 422 and "line 2" in e.value.detail
