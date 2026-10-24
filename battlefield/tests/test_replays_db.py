"""DB: replays are persisted as real `replay_*` episodes, so catch-up, GET /events and the fe views work."""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import settings
from app.main import app
from tests import factories as f

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "episodes"


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bf")  # lifespan not run; `pg` owns the pool


def _small_fixture(n_days: int = 2, gap_sec: float = 1.0) -> list[dict[str, Any]]:
    evs: list[dict[str, Any]] = [
        {"day": 0, "type": "episode.started", "agent": "battlefield", "payload": {"controller_mode": "enforce", "days": n_days, "seed": 7}}
    ]
    for d in range(n_days):
        evs += [
            {"day": d, "type": "day.started", "agent": "battlefield", "payload": {"day": d, "legit_injected": {"invoices": 2}}},
            {
                "day": d,
                "type": "attack.launched",
                "agent": "battlefield",
                "payload": {
                    "attack_id": f"atk_{d}",
                    "scheme_id": "ghost_vendor",
                    "display_name": "Ghost Vendor",
                    "story": "s",
                    "target_amount": 100.0 * (d + 1),
                },
            },
            {"day": d, "type": "agent.thinking", "agent": "red", "payload": {"text": f"plan {d}"}},
            {
                "day": d,
                "type": "gate.verdict",
                "agent": "battlefield",
                "payload": {
                    "verdict_id": f"vd_{d}",
                    "agent": "green",
                    "action": "invoices.pay",
                    "verdict": "block",
                    "reason": "r",
                    "rules_fired": ["x"],
                    "enforced": True,
                },
            },
            {
                "day": d,
                "type": "ledger.mutation",
                "agent": "green",
                "payload": {"agent": "green", "action": "invoices.pay", "entity_type": "invoice", "entity_id": f"inv_{d}"},
            },
            {
                "day": d,
                "type": "attack.outcome",
                "agent": "battlefield",
                "payload": {"attack_id": f"atk_{d}", "scheme_id": "ghost_vendor", "outcome": "blocked", "amount_extracted": 0.0, "detected_day": d},
            },
            {
                "day": d,
                "type": "score.updated",
                "agent": "battlefield",
                "payload": {"dollars_extracted": 0.0, "dollars_blocked": 100.0 * (d + 1), "attacks_launched": d + 1, "attacks_caught": d + 1},
            },
            {"day": d, "type": "day.ended", "agent": "battlefield", "payload": {"day": d}},
        ]
    evs.append(
        {
            "day": n_days,
            "type": "episode.ended",
            "agent": "battlefield",
            "payload": {"final_score": {"dollars_blocked": 300.0, "attacks_launched": 2, "attacks_caught": 2}},
        }
    )
    t0 = 1_800_000_000.0
    for i, e in enumerate(evs):
        e["id"] = i + 1
        e["episode_id"] = "ep_original"
        e["ts"] = datetime.fromtimestamp(t0 + i * gap_sec, UTC).isoformat()
    return evs


def _write(dirpath: Path, name: str, evs: list[dict[str, Any]]) -> None:
    (dirpath / f"{name}.jsonl").write_text("\n".join(json.dumps(e) for e in evs) + "\n")


@pytest.fixture
def fixtures_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(settings, "fixtures_dir", str(tmp_path))
    return tmp_path


async def _wait_done(c: httpx.AsyncClient, ep: str, timeout: float = 15.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = (await c.get(f"/api/episodes/{ep}", headers=f.auth())).json()
        if row["status"] in ("finished", "failed"):
            return row
        await asyncio.sleep(0.05)
    raise AssertionError(f"replay {ep} did not finish")


def _strip(e: dict[str, Any]) -> tuple:
    return (e["day"], e["type"], e["agent"], e["payload"])


@pytest.mark.usefixtures("pg")
async def test_play_persists_events_in_order_under_a_new_episode(fixtures_dir: Path) -> None:
    evs = _small_fixture()
    _write(fixtures_dir, "tiny", evs)
    async with _client() as c:
        r = await c.post("/api/replays/tiny/play", json={"speed": 1000}, headers=f.auth())
        assert r.status_code == 202
        ep = r.json()["episode_id"]
        assert ep.startswith("replay_tiny_") and r.json()["events"] == len(evs)
        row = await _wait_done(c, ep)
        got = (await c.get("/api/events", params={"episode_id": ep}, headers=f.auth())).json()
        score = (await c.get(f"/api/episodes/{ep}/score", headers=f.auth())).json()
    assert row["status"] == "finished" and row["finished_at"]
    assert (row["seed"], row["controller_mode"], row["days"], row["current_day"]) == (7, "enforce", 2, 2)
    assert [_strip(e) for e in got] == [_strip(e) for e in evs]
    ids = [e["id"] for e in got]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)
    assert all(e["episode_id"] == ep and "replay" not in e for e in got)
    assert score["dollars_blocked"] == 300.0 and score["attacks_launched"] == 2 and score["dollars_extracted"] == 0.0


@pytest.mark.usefixtures("pg")
async def test_two_concurrent_plays_are_two_episodes(fixtures_dir: Path) -> None:
    evs = _small_fixture()
    _write(fixtures_dir, "tiny", evs)
    async with _client() as c:
        r1, r2 = await asyncio.gather(*(c.post("/api/replays/tiny/play", json={"speed": 1000}, headers=f.auth()) for _ in range(2)))
        e1, e2 = r1.json()["episode_id"], r2.json()["episode_id"]
        assert e1 != e2
        await _wait_done(c, e1)
        await _wait_done(c, e2)
        g1 = (await c.get("/api/events", params={"episode_id": e1}, headers=f.auth())).json()
        g2 = (await c.get("/api/events", params={"episode_id": e2}, headers=f.auth())).json()
    assert [_strip(e) for e in g1] == [_strip(e) for e in g2] == [_strip(e) for e in evs]
    assert not ({e["id"] for e in g1} & {e["id"] for e in g2})


@pytest.mark.usefixtures("pg")
async def test_custom_episode_id_validation_and_errors(fixtures_dir: Path) -> None:
    _write(fixtures_dir, "tiny", _small_fixture(n_days=1))
    (fixtures_dir / "broken.jsonl").write_text('{"type": "day.started", "day": 0}\nnot json\n')
    custom = f.uid("replay_custom")
    async with _client() as c:
        ok = await c.post("/api/replays/tiny/play", json={"speed": 0, "episode_id": custom}, headers=f.auth())
        assert ok.status_code == 202 and ok.json()["episode_id"] == custom
        await _wait_done(c, custom)
        dup = await c.post("/api/replays/tiny/play", json={"speed": 0, "episode_id": custom}, headers=f.auth())
        live_id = await c.post("/api/replays/tiny/play", json={"episode_id": "ep_live"}, headers=f.auth())
        missing = await c.post("/api/replays/nope/play", json={}, headers=f.auth())
        traversal = await c.post("/api/replays/..%2Ftiny/play", json={}, headers=f.auth())
        broken = await c.post("/api/replays/broken/play", json={"episode_id": f.uid("replay_broken")}, headers=f.auth())
    assert dup.status_code == 409
    assert live_id.status_code == 422  # never stream into (or create) a non-replay episode id
    assert missing.status_code == 404 and traversal.status_code == 404
    assert broken.status_code == 422 and "line 2" in broken.json()["detail"]
    assert await db.fetchval("SELECT count(*) FROM episodes WHERE id LIKE 'replay_broken%'") == 0


@pytest.mark.usefixtures("pg")
async def test_runner_routes_refuse_replay_episodes(fixtures_dir: Path) -> None:
    _write(fixtures_dir, "tiny", _small_fixture(n_days=1))
    async with _client() as c:
        ep = (await c.post("/api/replays/tiny/play", json={"speed": 0}, headers=f.auth())).json()["episode_id"]
        await _wait_done(c, ep)
        h = f.auth()
        codes = [
            (await c.post(f"/api/episodes/{ep}/start", headers=h)).status_code,
            (await c.post(f"/api/episodes/{ep}/step", headers=h)).status_code,
            (await c.post(f"/api/episodes/{ep}/pause", headers=h)).status_code,
            (await c.post(f"/api/episodes/{ep}/resume", headers=h)).status_code,
            (await c.patch(f"/api/episodes/{ep}/controller", json={"mode": "off"}, headers=h)).status_code,
            (await c.post(f"/api/episodes/{ep}/attack", json={"scheme_id": "ghost_vendor"}, headers=h)).status_code,
        ]
    assert codes == [409] * 6
    # no ledger rows were ever created for the replay
    assert await db.fetchval("SELECT count(*) FROM vendors WHERE episode_id=$1", ep) == 0


@pytest.mark.usefixtures("pg")
async def test_fe_views_for_a_replay(fixtures_dir: Path, episode: str) -> None:
    _write(fixtures_dir, "tiny", _small_fixture())
    async with _client() as c:
        ep = (await c.post("/api/replays/tiny/play", json={"speed": 0}, headers=f.auth())).json()["episode_id"]
        await _wait_done(c, ep)
        h = f.auth()
        snap = (await c.get(f"/api/fe/episodes/{ep}/snapshot", headers=h)).json()
        tl = (await c.get(f"/api/fe/episodes/{ep}/timeline", headers=h)).json()
        attacks = (await c.get(f"/api/fe/episodes/{ep}/attacks", headers=h)).json()
        feed = (await c.get(f"/api/fe/episodes/{ep}/feed", headers=h)).json()
        thinking = (await c.get(f"/api/fe/episodes/{ep}/agents/red/thinking", headers=h)).json()
        cmp = (await c.get("/api/fe/compare", params={"a": episode, "b": ep}, headers=h)).json()
        verdicts = (await c.get(f"/api/fe/episodes/{ep}/verdicts", headers=h)).json()
    assert snap["score"]["dollars_blocked"] == 300.0 and snap["episode"]["id"] == ep
    assert [(t["day"], t["verdict_block"], t["payments_made"], t["invoices_received"], t["attacks_launched"], t["blocked_cumulative"]) for t in tl] == [
        (0, 1, 1, 2, 1, 100.0),
        (1, 1, 1, 2, 1, 200.0),
    ]
    assert tl[0]["cash_in"] is None
    assert [(a["id"], a["outcome"], a["day_launched"], a["target_amount"]) for a in attacks] == [("atk_0", "blocked", 0, 100.0), ("atk_1", "blocked", 1, 200.0)]
    assert {"attack.launched", "gate.verdict", "score.updated", "episode.ended"} <= {e["type"] for e in feed}
    assert [t["text"] for t in thinking] == ["plan 0", "plan 1"]
    assert cmp["b"]["score"]["dollars_blocked"] == 300.0 and len(cmp["b"]["attacks"]) == 2 and len(cmp["b"]["timeline"]) == 2
    assert cmp["delta"]["dollars_blocked"] == 300.0
    assert verdicts == []  # table-derived: empty for replays (documented)


@pytest.mark.usefixtures("pg")
async def test_sample_fixture_replays_completely(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "fixtures_dir", str(FIXTURES))
    lines = [json.loads(x) for x in (FIXTURES / "sample-enforce-4d.jsonl").read_text().splitlines() if x.strip()]
    async with _client() as c:
        ep = (await c.post("/api/replays/sample-enforce-4d/play", json={"speed": 0}, headers=f.auth())).json()["episode_id"]
        row = await _wait_done(c, ep)
        got = (await c.get("/api/events", params={"episode_id": ep, "limit": 5000}, headers=f.auth())).json()
    assert row["status"] == "finished" and row["current_day"] == 4
    assert [_strip(e) for e in got] == [_strip(e) for e in lines]


# ---------- WS catch-up: real lifespan (pool lives in the TestClient's loop) ----------


def test_ws_after_id_0_mid_replay_gets_history_then_live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    monkeypatch.setattr(settings, "database_url", url)
    monkeypatch.setattr(settings, "schema_path", "/nonexistent/schema.sql")
    monkeypatch.setattr(settings, "fixtures_dir", str(tmp_path))
    evs = _small_fixture(n_days=2, gap_sec=1.0)  # 19 events, 1 s apart; speed 20 → ~50 ms each
    _write(tmp_path, "slow", evs)
    with TestClient(app) as c:
        ep = c.post("/api/replays/slow/play", json={"speed": 20}, headers=f.auth()).json()["episode_id"]
        deadline = time.monotonic() + 10
        before: list[dict[str, Any]] = []
        while len(before) < 3 and time.monotonic() < deadline:
            before = c.get("/api/events", params={"episode_id": ep}, headers=f.auth()).json()
            time.sleep(0.02)
        assert 3 <= len(before) < len(evs), "connect mid-replay"
        ticket = c.post("/api/ws/ticket", json={"episode_id": ep}, headers=f.auth()).json()["ticket"]
        seen: dict[int, dict[str, Any]] = {}
        arrival: list[int] = []
        with c.websocket_connect(f"/api/ws?episode_id={ep}&ticket={ticket}&after_id=0") as ws:
            while len(seen) < len(evs):
                m = ws.receive_json()
                if m["type"] != "ping":
                    arrival.append(m["id"])
                    seen.setdefault(m["id"], m)  # the WS may send an event both from history and live; clients dedupe by id
        while c.get(f"/api/episodes/{ep}", headers=f.auth()).json()["status"] == "running" and time.monotonic() < deadline:
            time.sleep(0.02)
    ordered = [seen[i] for i in sorted(seen)]
    assert [_strip(e) for e in ordered] == [_strip(e) for e in evs]
    assert arrival[: len(before)] == [e["id"] for e in before]  # history first, then live frames
    assert max(seen) > max(e["id"] for e in before)


@pytest.mark.usefixtures("pg")
async def test_unreadable_or_escaping_fixtures_create_no_episode(fixtures_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
    outside = tmp_path_factory.mktemp("outside") / "secret.jsonl"
    _write(outside.parent, "secret", _small_fixture(n_days=1))
    (fixtures_dir / "escape.jsonl").symlink_to(outside)
    _write(fixtures_dir, "real", _small_fixture(n_days=1))
    (fixtures_dir / "inside.jsonl").symlink_to(fixtures_dir / "real.jsonl")
    (fixtures_dir / "adir.jsonl").mkdir()
    (fixtures_dir / "binary.jsonl").write_bytes(b'{"type": "x"}\n\xff\xfe\n')
    (fixtures_dir / "badpayload.jsonl").write_text('{"type": "day.started", "payload": [1]}\n')
    run = f.uid("x")  # ids unique per run: the test DB is reused across runs
    async with _client() as c:
        h = f.auth()
        codes = {
            name: (await c.post(f"/api/replays/{name}/play", json={"speed": 0, "episode_id": f"replay_{name}_{run}"}, headers=h)).status_code
            for name in ("escape", "adir", "binary", "badpayload", "inside")
        }
        await _wait_done(c, f"replay_inside_{run}")
    assert codes == {"escape": 404, "adir": 422, "binary": 422, "badpayload": 422, "inside": 202}
    made = await db.fetch("SELECT id FROM episodes WHERE id = ANY($1::text[])", [f"replay_{n}_{run}" for n in codes])
    assert [r["id"] for r in made] == [f"replay_inside_{run}"]


@pytest.mark.usefixtures("pg")
async def test_fe_views_survive_odd_payloads(episode: str) -> None:
    rep = f.uid("replay_odd")
    await db.execute("INSERT INTO episodes (id, seed, controller_mode, days, current_day) VALUES ($1, 1, 'shadow', 2, 2)", rep)
    odd = [
        ("day.started", {"day": 0, "legit_injected": None}),
        ("day.started", {"day": 1, "legit_injected": [1, 2]}),
        ("attack.launched", {"attack_id": {"x": 1}, "target_amount": "lots", "story": None}),
        ("attack.launched", {"attack_id": "atk_ok", "target_amount": None, "display_name": 5}),
        ("attack.outcome", {"attack_id": "atk_ok", "amount_extracted": "x", "outcome": "blocked"}),
        ("gate.verdict", {"verdict": None, "amount": "12", "reason": {"r": 1}}),
        ("gate.verdict", {"verdict": "block", "amount": "12", "reason": None}),
        ("escalation.opened", {"amount": "x", "reason": 3}),
        ("flag.raised", {"reason": ["a"]}),
        ("vendor.frozen", {"reason": None}),
        ("turn.ended", {"agent": "red", "factory_credits": "a lot", "duration_sec": "slow"}),
        ("turn.ended", {"agent": "red", "factory_credits": 1.5, "duration_sec": 2}),
        ("score.updated", {"dollars_blocked": "x", "dollars_extracted": None}),
    ]
    for ep in (episode, rep):
        for t, p in odd:
            await db.execute("INSERT INTO events (episode_id, day, type, agent, payload) VALUES ($1, 0, $2, 'battlefield', $3)", ep, t, p)
        for raw in ("[1, 2]", '"str"', "null", "3"):  # non-object payloads stored by some other path
            await db.execute(
                "INSERT INTO events (episode_id, day, type, agent, payload) VALUES ($1, 0, 'score.updated', 'battlefield', $2::text::jsonb)", ep, raw
            )
    async with _client() as c:
        h = f.auth()
        for ep in (episode, rep):
            for path in ("snapshot", "timeline", "attacks", "agents/activity", "feed?include_verdict_allows=true", "agents/red/thinking"):
                r = await c.get(f"/api/fe/episodes/{ep}/{path}", headers=h)
                assert r.status_code == 200, (ep, path, r.text[:200])
            assert (await c.get(f"/api/episodes/{ep}/score", headers=h)).status_code == 200
        cmp = await c.get("/api/fe/compare", params={"a": episode, "b": rep}, headers=h)
        attacks = (await c.get(f"/api/fe/episodes/{rep}/attacks", headers=h)).json()
        turns = (await c.get(f"/api/fe/episodes/{rep}/agents/activity", headers=h)).json()["turns"]
    assert cmp.status_code == 200
    assert [(a["id"], a["outcome"], a["amount_extracted"]) for a in attacks] == [("atk_ok", "blocked", 0.0)]
    assert turns == [{"agent": "red", "day": 0, "credits": 1.5, "seconds": 2.0}]


def test_lifespan_shutdown_marks_running_replay_failed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    monkeypatch.setattr(settings, "database_url", url)
    monkeypatch.setattr(settings, "schema_path", "/nonexistent/schema.sql")
    monkeypatch.setattr(settings, "fixtures_dir", str(tmp_path))
    _write(tmp_path, "slow", _small_fixture(n_days=2, gap_sec=10.0))  # 3 s (capped) per event at speed 1
    with TestClient(app) as c:
        ep = c.post("/api/replays/slow/play", json={"speed": 1}, headers=f.auth()).json()["episode_id"]
        deadline = time.monotonic() + 5
        while not c.get("/api/events", params={"episode_id": ep}, headers=f.auth()).json() and time.monotonic() < deadline:
            time.sleep(0.02)
    # lifespan exit cancelled the replay before closing the pool; read the result with a fresh pool

    async def check() -> tuple[str, list[tuple[str, dict]]]:
        await db.init_pool()
        try:
            status = await db.fetchval("SELECT status FROM episodes WHERE id=$1", ep)
            evs = await db.fetch("SELECT type, payload FROM events WHERE episode_id=$1 ORDER BY id", ep)
            return status, [(r["type"], r["payload"]) for r in evs]
        finally:
            await db.close_pool()
            monkeypatch.setattr(db, "_pool", None)

    status, evs = asyncio.run(check())
    assert status == "failed"
    assert evs[0][0] == "episode.started" and evs[-1][0] == "error" and "cancelled" in evs[-1][1]["message"]
    assert len(evs) < 10
