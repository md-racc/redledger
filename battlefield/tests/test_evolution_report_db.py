"""DB: the evolution report and lineage timeline (docs/EVOLUTION-DESIGN.md §7, /api/fe/lineages/*).

Builds one deterministic lineage directly in the DB (fixed ids) and compares both documents to the
golden fixtures R develops against: battlefield/fixtures/lineages/sample-{report,timeline}.json.
Regenerate them after an intended change with UPDATE_GOLDEN=1.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
import pytest

from app import db
from app.main import app
from tests import factories as f

pytestmark = pytest.mark.usefixtures("pg")

LN = "ln_rpt_sample"
EPS = {1: "ep_rpt_g1", 2: "ep_rpt_g2", 3: "ep_rpt_g3"}
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "lineages"
CONFIG = {
    "generations": 2,
    "days": 3,
    "controller_mode": "enforce",
    "reveal_days": 3,
    "reveal_generations": 2,
    "headless": {"escalation_timeout_sec": 5, "escalation_policy": "block"},
    "max_credits": 0.0,
}


@pytest.fixture(autouse=True)
def _no_git_sha(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GIT_SHA", raising=False)  # the golden run card has git_sha null


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bf")


async def _wipe() -> None:
    ids = list(EPS.values())
    await db.execute("DELETE FROM events WHERE episode_id = ANY($1::text[])", ids)
    await db.execute("DELETE FROM debriefs WHERE lineage_id=$1", LN)
    await db.execute("DELETE FROM escalations WHERE episode_id = ANY($1::text[])", ids)
    for t in ("payments", "verdicts", "flags", "invoices", "expenses", "vendor_changes", "attacks", "vendors"):
        await db.execute(f"DELETE FROM {t} WHERE episode_id = ANY($1::text[])", ids)
    await db.execute("DELETE FROM episodes WHERE id = ANY($1::text[])", ids)
    await db.execute("DELETE FROM lineages WHERE id=$1", LN)


async def _event(ep: str, day: int, type_: str, payload: dict[str, Any], agent: str | None = None) -> None:
    await db.execute("INSERT INTO events (episode_id, day, type, agent, payload) VALUES ($1,$2,$3,$4,$5)", ep, day, type_, agent, payload)


async def _playbook(agent: str, version: int, generation: int, source: str, content: dict[str, Any], rationale: str = "", **cols: Any) -> None:
    await db.execute(
        "INSERT INTO playbooks (lineage_id, agent, version, parent_version, generation, episode_id, day, source, content, rationale) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)",
        LN,
        agent,
        version,
        version - 1 if version else None,
        generation,
        cols.get("episode_id"),
        cols.get("day"),
        source,
        content,
        rationale,
    )


async def _debrief(g: int, agent: str, day: int | None, items: int) -> None:
    await db.execute(
        "INSERT INTO debriefs (lineage_id, generation, episode_id, day, agent, payload) VALUES ($1,$2,$3,$4,$5,$6)",
        LN,
        g,
        EPS[g],
        day,
        agent,
        {"items": [{"kind": "attack", "n": i} for i in range(items)]},
    )


async def _invoice(ep: str, vid: str, iid: str, amount: float, *, origin: str, status: str, attack_id: str | None = None) -> str:
    return await f.insert(
        "invoices",
        id=iid,
        episode_id=ep,
        vendor_id=vid,
        amount=amount,
        invoice_number=f"INV-{iid}",
        received_day=0,
        due_day=30,
        status=status,
        status_day=1,
        origin=origin,
        attack_id=attack_id,
    )


async def _verdict(ep: str, vid: str, entity_id: str, verdict: str, rules: list[str], day: int = 1) -> None:
    await f.insert(
        "verdicts",
        id=vid,
        episode_id=ep,
        idempotency_key=f"tu_{vid}",
        day=day,
        agent="green",
        action="invoices.pay",
        entity_type="invoice",
        entity_id=entity_id,
        verdict=verdict,
        reason="test",
        rules_fired=rules,
        enforced=True,
    )


async def build(status: str = "finished") -> None:
    """2 headless generations + 1 demo. Red adapts (duplicate_invoice dropped, an evolved scheme appears),
    blue learns `learned:ghost_vendor`, one legit block in generation 1."""
    await _wipe()
    await db.execute("INSERT INTO lineages (id, name, base_seed, config, status, current_generation) VALUES ($1,'sample',42,$2,$3,3)", LN, CONFIG, status)
    for g, seed in ((1, 43), (2, 44), (3, 50)):
        await db.execute(
            "INSERT INTO episodes (id, seed, controller_mode, days, status, current_day, lineage_id, generation) VALUES ($1,$2,'enforce',3,'finished',3,$3,$4)",
            EPS[g],
            seed,
            LN,
            g,
        )

    e1, e2, e3 = EPS[1], EPS[2], EPS[3]
    # generation 1: ghost_vendor extracted, duplicate_invoice blocked, one legit invoice blocked
    rv = await f.insert(
        "vendors", id="ven_rpt_r1", episode_id=e1, name="Ghost LLC", bank_account="ACCT-RED", bank_routing="1", created_day=0, origin="red", status="active"
    )
    sv = await f.insert(
        "vendors", id="ven_rpt_s1", episode_id=e1, name="Real Co", bank_account="ACCT-S", bank_routing="1", created_day=-90, origin="sim", status="active"
    )
    a1 = await f.attack(e1, day=0, scheme_id="ghost_vendor", target_amount=3000, id="att_rpt_a1", outcome="extracted", amount_extracted=3000)
    a2 = await f.attack(e1, day=1, scheme_id="duplicate_invoice", target_amount=2000, id="att_rpt_a2", outcome="blocked", detected_day=1)
    i1 = await _invoice(e1, rv, "inv_rpt_i1", 3000, origin="red", status="paid", attack_id=a1)
    i2 = await _invoice(e1, sv, "inv_rpt_i2", 2000, origin="red", status="blocked", attack_id=a2)
    l1 = await _invoice(e1, sv, "inv_rpt_l1", 1000, origin="sim", status="blocked")
    await f.insert(
        "payments", id="pay_rpt_p1", episode_id=e1, invoice_id=i1, amount=3000, to_account="ACCT-RED", paid_day=1, paid_by="green", origin_of_source="red"
    )
    await _verdict(e1, "ver_rpt_v1", i1, "allow", [])
    await _verdict(e1, "ver_rpt_v2", i2, "block", ["duplicate_amount_match", "near_threshold"])
    await _verdict(e1, "ver_rpt_v3", l1, "block", ["near_threshold"])
    # generation 2: blue's learned rule catches ghost_vendor; an evolved split gets through
    rv2 = await f.insert(
        "vendors", id="ven_rpt_r2", episode_id=e2, name="Ghost 2", bank_account="ACCT-R2", bank_routing="1", created_day=0, origin="red", status="active"
    )
    b1 = await f.attack(e2, day=0, scheme_id="ghost_vendor", target_amount=3000, id="att_rpt_b1", outcome="blocked", detected_day=0)
    b2 = await f.attack(
        e2,
        day=1,
        scheme_id="evolved:split_v2",
        target_amount=4000,
        id="att_rpt_b2",
        outcome="extracted",
        amount_extracted=4000,
        params={"parent": "threshold_split"},
    )
    j1 = await _invoice(e2, rv2, "inv_rpt_j1", 3000, origin="red", status="blocked", attack_id=b1)
    j2 = await _invoice(e2, rv2, "inv_rpt_j2", 4000, origin="red", status="paid", attack_id=b2)
    await f.insert(
        "payments", id="pay_rpt_p2", episode_id=e2, invoice_id=j2, amount=4000, to_account="ACCT-R2", paid_day=1, paid_by="green", origin_of_source="red"
    )
    await _verdict(e2, "ver_rpt_w1", j1, "block", ["learned:ghost_vendor", "vendor_age_lt_7d"], day=0)

    # credits, green actions, disclosures
    for ep, red, blue in ((e1, 1.5, 0.5), (e2, 2.0, 1.0)):
        await _event(ep, 0, "turn.ended", {"agent": "red", "ok": True, "factory_credits": red})
        await _event(ep, 0, "turn.ended", {"agent": "blue", "ok": True, "factory_credits": blue})
        await _event(ep, 1, "ledger.mutation", {"agent": "green", "action": "invoices.pay"}, agent="green")
    await _event(e3, 0, "turn.ended", {"agent": "red", "ok": True, "factory_credits": None})
    for g in (1, 2):
        for agent in ("red", "green", "blue"):
            await _debrief(g, agent, 0, 1)
            await _debrief(g, agent, 1, 2 if agent == "blue" else 1)
            await _debrief(g, agent, None, 3)
    await _debrief(3, "red", 0, 1)

    # playbooks: seeds, a turn write and reflections
    for agent in ("red", "green", "blue"):
        await _playbook(agent, 0, 0, "seed", {})
    await _playbook("red", 1, 1, "turn", {"avoid": []}, "watching", episode_id=e1, day=1)
    await _playbook("red", 2, 1, "reflect", {"avoid": ["duplicate_invoice"], "favour": {"ghost_vendor": 2}}, "duplicate_invoice blocked")
    await _playbook("blue", 1, 1, "reflect", {"learned": ["ghost_vendor"], "near_band": 0.95}, "ghost_vendor got past me")
    await _playbook("red", 3, 2, "reflect", {"avoid": ["duplicate_invoice", "ghost_vendor"], "favour": {"evolved:split_v2": 1}}, "ghost_vendor caught")


async def _get(path: str, **headers: str) -> httpx.Response:
    async with _client() as c:
        return await c.get(path, headers=headers or f.auth())


def _golden(name: str, doc: dict[str, Any]) -> dict[str, Any]:
    path = FIXTURES / name
    if os.environ.get("UPDATE_GOLDEN"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    return json.loads(path.read_text())


async def test_report_matches_golden_and_is_deterministic() -> None:
    await build()
    try:
        r1, r2 = await _get(f"/api/fe/lineages/{LN}/report"), await _get(f"/api/fe/lineages/{LN}/report")
        assert r1.status_code == 200, r1.text
        rep = r1.json()
        assert rep == r2.json()
        assert rep == _golden("sample-report.json", rep)

        assert rep["partial"] is False
        card = rep["run_card"]
        assert card["seeds"] == [43, 44, 50] and card["generations"] == 2 and card["demo_generations"] == [3]
        assert card["credits"] == [
            {"generation": 1, "factory_credits": 2.0},
            {"generation": 2, "factory_credits": 3.0},
            {"generation": 3, "factory_credits": 0.0},
        ]
        g1, g2, g3 = rep["generations"]
        assert (g1["demo"], g2["demo"], g3["demo"]) == (False, False, True)
        assert g1["score"]["dollars_extracted"] == 3000 and g1["score"]["dollars_blocked"] == 2000 and g1["score"]["legit_blocked"] == 1
        assert g1["red_mix"] == {
            "duplicate_invoice": {"launched": 1, "outcomes": {"blocked": 1}, "amount_extracted": 0.0, "target_amount": 2000.0},
            "ghost_vendor": {"launched": 1, "outcomes": {"extracted": 1}, "amount_extracted": 3000.0, "target_amount": 3000.0},
        }
        near = next(r for r in g1["blue_rules"] if r["rule_id"] == "near_threshold")
        assert (near["fired"], near["on_red"], near["on_legit"], near["precision"], near["attacks_hit"], near["recall"]) == (2, 1, 1, 0.5, 1, 0.5)
        assert g1["who_beat_whom"]["ghost_vendor"] == {"attacks": 1, "caught": 0, "missed": 1, "rules": {}}
        assert g1["who_beat_whom"]["duplicate_invoice"]["rules"] == {"duplicate_amount_match": 1, "near_threshold": 1}
        assert g2["who_beat_whom"]["ghost_vendor"] == {"attacks": 1, "caught": 1, "missed": 0, "rules": {"learned:ghost_vendor": 1, "vendor_age_lt_7d": 1}}
        assert g1["green"] == {"actions": 1, "legit_processed": 0, "legit_blocked": 1, "fraud_paid": 3000.0}
        assert g1["disclosures"]["blue"] == {"daily": 2, "aar": 1, "items": 6}
        assert rep["red"]["evolved_schemes"] == [{"scheme_id": "evolved:split_v2", "first_generation": 2, "parent": "threshold_split"}]
        assert rep["blue"]["learned_rules"] == [{"rule_id": "learned:ghost_vendor", "first_generation": 2}]
        assert {r["rule_id"] for r in rep["blue"]["retired_rules"]} == {"duplicate_amount_match", "near_threshold"}  # the demo fired none
        red = rep["playbooks"]["red"]
        assert [v["version"] for v in red] == [0, 1, 2, 3]
        assert red[2]["diff"] == {"added": {"favour": {"ghost_vendor": 2}}, "removed": {}, "changed": {"avoid": {"from": [], "to": ["duplicate_invoice"]}}}
        assert red[3]["diff"]["added"] == {"favour.evolved:split_v2": 1} and red[3]["diff"]["removed"] == {"favour.ghost_vendor": 2}
    finally:
        await _wipe()


async def test_timeline_orders_versions_around_generations() -> None:
    await build()
    try:
        r = await _get(f"/api/fe/lineages/{LN}/timeline")
        assert r.status_code == 200, r.text
        tl = r.json()
        assert tl == _golden("sample-timeline.json", tl)
        order = [(e["kind"], e.get("agent"), e.get("version"), e["generation"]) for e in tl["entries"]]
        assert order == [
            ("playbook", "blue", 0, 0),
            ("playbook", "green", 0, 0),
            ("playbook", "red", 0, 0),
            ("playbook", "red", 1, 1),  # written during generation 1's turns
            ("generation", None, None, 1),
            ("playbook", "blue", 1, 1),  # reflections on generation 1
            ("playbook", "red", 2, 1),
            ("generation", None, None, 2),
            ("playbook", "red", 3, 2),
            ("generation", None, None, 3),
        ]
        assert tl["generations"][0]["debriefs"]["red"] == {"daily": 2, "aar": 1}
        assert "content" not in tl["entries"][0] and "created_at" not in json.dumps(tl)
    finally:
        await _wipe()


async def test_partial_while_running_unknown_404_and_operator_only() -> None:
    await build(status="running")
    try:
        assert (await _get(f"/api/fe/lineages/{LN}/report")).json()["partial"] is True
        assert (await _get(f"/api/fe/lineages/{LN}/timeline")).json()["partial"] is True
        for path in ("report", "timeline"):
            assert (await _get(f"/api/fe/lineages/ln_nope/{path}")).status_code == 404
            assert (await _get(f"/api/fe/lineages/{LN}/{path}", **f.auth("blue", episode=EPS[1]))).status_code in (401, 403)
            assert (await _get(f"/api/fe/lineages/{LN}/{path}", Authorization="Bearer wrong")).status_code == 401
    finally:
        await _wipe()
