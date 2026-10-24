"""DB: GET /api/lineages/{id}/export, the lineage log bundle."""

from __future__ import annotations

import json

import httpx
import pytest

from app import db
from app.main import app
from tests import factories as f

pytestmark = pytest.mark.usefixtures("pg")

OP = {"Authorization": f"Bearer {f.OPERATOR_TOKEN}"}


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bf")


async def _event(ep: str, day: int, type_: str, payload: dict) -> None:
    await db.execute("INSERT INTO events (episode_id, day, type, agent, payload) VALUES ($1,$2,$3,'battlefield',$4)", ep, day, type_, payload)


async def _playbook(ln: str, agent: str, version: int, generation: int, source: str, *, ep: str | None = None, day: int | None = None) -> None:
    await db.execute(
        "INSERT INTO playbooks (lineage_id, agent, version, parent_version, generation, episode_id, day, source, content, rationale) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)",
        ln,
        agent,
        version,
        None if version == 0 else version - 1,
        generation,
        ep,
        day,
        source,
        {"v": version},
        f"r{version}",
    )


async def _lineage() -> tuple[str, list[str]]:
    """Two runner generations + one demo generation, each with a little of everything."""
    ln = f.uid("ln")
    await db.execute("INSERT INTO lineages (id, base_seed, config, status, current_generation) VALUES ($1, 42, $2, 'finished', 3)", ln, {"generations": 2})
    for a in ("red", "green", "blue"):
        await _playbook(ln, a, 0, 0, "seed")
    eps = []
    for g in (1, 2, 3):
        ep = f.uid("ep")
        eps.append(ep)
        await db.execute(
            "INSERT INTO episodes (id, seed, controller_mode, days, status, lineage_id, generation) VALUES ($1,$2,'enforce',2,'finished',$3,$4)",
            ep,
            42 + g,
            ln,
            g,
        )
        await _event(ep, 0, "generation.started", {"lineage_id": ln, "generation": g})
        await _event(ep, 0, "turn.ended", {"agent": "red", "ok": True, "factory_credits": 1.5})
        await _event(ep, 1, "turn.ended", {"agent": "blue", "ok": True, "factory_credits": None})
        await _event(ep, 1, "generation.ended", {"lineage_id": ln, "generation": g})
        await db.execute(
            "INSERT INTO audit_log (episode_id, day, agent, action, args, result, http_status) VALUES ($1, 0, 'red', 'invoices.create', '{}', '{}', 201)", ep
        )
        aid = await f.attack(ep, day=0, scheme_id="ghost_vendor")
        await f.verdict(ep, "invoice", f.uid("inv"), day=1)
        await db.execute(
            "INSERT INTO debriefs (lineage_id, generation, episode_id, day, agent, payload) VALUES ($1,$2,$3,NULL,'blue',$4)", ln, g, ep, {"aar": g}
        )
        await db.execute(
            "INSERT INTO debriefs (lineage_id, generation, episode_id, day, agent, payload) VALUES ($1,$2,$3,0,'red',$4)", ln, g, ep, {"items": [aid]}
        )
        await _playbook(ln, "red", g, g, "turn", ep=ep, day=0)
    return ln, eps


async def test_export_bundle_shape_and_order() -> None:
    ln, eps = await _lineage()
    async with _client() as c:
        r = await c.get(f"/api/lineages/{ln}/export", headers=OP)
    assert r.status_code == 200, r.text
    b = r.json()
    assert set(b) == {"lineage", "playbooks", "generations"}
    assert b["lineage"]["id"] == ln and b["lineage"]["config"] == {"generations": 2}
    assert [g["generation"] for g in b["generations"]] == [1, 2, 3]  # the demo generation (3) included
    assert [g["episode_id"] for g in b["generations"]] == eps
    assert [g["seed"] for g in b["generations"]] == [43, 44, 45]
    g1 = b["generations"][0]
    assert set(g1) == {
        "generation",
        "episode_id",
        "seed",
        "status",
        "episode",
        "score",
        "credits",
        "events",
        "audit_log",
        "verdicts",
        "attacks",
        "debriefs",
        "playbooks",
    }
    assert [e["type"] for e in g1["events"]] == ["generation.started", "turn.ended", "turn.ended", "generation.ended"]
    assert g1["credits"] == {
        "by_day": [{"day": 0, "agent": "red", "factory_credits": 1.5}, {"day": 1, "agent": "blue", "factory_credits": 0.0}],
        "total": {"red": 1.5, "green": 0.0, "blue": 0.0},
    }
    assert len(g1["audit_log"]) == 1 and len(g1["verdicts"]) == 1
    assert g1["attacks"][0]["scheme_id"] == "ghost_vendor" and "outcome" in g1["attacks"][0]  # ground truth, operator view
    assert [d["day"] for d in g1["debriefs"]] == [0, None]  # daily first, the after-action review last
    assert g1["debriefs"][1]["payload"] == {"aar": 1}
    assert set(g1["score"]) >= {"dollars_extracted", "dollars_blocked", "false_positive_cost"}
    # per generation: versions written in it; top level: the whole history incl. the v0 seeds
    assert [p["version"] for p in g1["playbooks"]["red"]] == [1] and g1["playbooks"]["green"] == []
    assert [p["version"] for p in b["playbooks"]["red"]] == [0, 1, 2, 3]
    assert [p["source"] for p in b["playbooks"]["blue"]] == ["seed"]
    json.dumps(b)  # plain JSON all the way down


async def test_export_one_generation() -> None:
    ln, eps = await _lineage()
    async with _client() as c:
        r = await c.get(f"/api/lineages/{ln}/export", params={"generation": 2}, headers=OP)
    assert r.status_code == 200
    assert [g["episode_id"] for g in r.json()["generations"]] == [eps[1]]


async def test_export_is_operator_only_and_404s() -> None:
    ln, eps = await _lineage()
    async with _client() as c:
        assert (await c.get(f"/api/lineages/{ln}/export")).status_code == 401
        assert (await c.get(f"/api/lineages/{ln}/export", headers=f.auth("blue", episode=eps[0], day=1))).status_code in (401, 403)
        assert (await c.get("/api/lineages/ln_nope/export", headers=OP)).status_code == 404


async def test_export_of_a_lineage_with_no_generations() -> None:
    ln = f.uid("ln")
    await db.execute("INSERT INTO lineages (id, base_seed, config) VALUES ($1, 7, '{}'::jsonb)", ln)
    async with _client() as c:
        r = await c.get(f"/api/lineages/{ln}/export", headers=OP)
    assert r.status_code == 200
    assert r.json()["generations"] == [] and r.json()["playbooks"] == {"red": [], "green": [], "blue": []}
