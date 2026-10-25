"""/api/fe/episodes/{id}/controls: the controls assessment report.

DB tests build a small enforce episode by hand (one scheme per gap reason, a false positive, an approved legit
escalation, an audit flag) and check the report against it. The builder and the event gatherer are also tested
without a database, on the recorded demo episode (docs/recordings), which is what the frontend mock fixture is made of.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from app import db
from app.api.frontend import _facts_from_events, build_controls_report
from app.main import app
from app.scoring import score
from tests import factories as f

GROUND_TRUTH_KEYS = {"origin", "entity_origin", "origin_of_source"}
RECORDING = Path(__file__).resolve().parents[2] / "docs" / "recordings" / "demo-enforce-redblue-live.jsonl"


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bf", timeout=30)


def _keys(x: Any) -> set[str]:
    if isinstance(x, dict):
        return set(x) | {k for v in x.values() for k in _keys(v)}
    if isinstance(x, list):
        return {k for v in x for k in _keys(v)}
    return set()


async def _verdict(
    ep: str, entity_type: str, entity_id: str, verdict: str, rules: list[str], *, amount: float | None = None, day: int = 1, enforced: bool = True
) -> str:
    return await f.insert(
        "verdicts",
        episode_id=ep,
        idempotency_key=f.uid("tu"),
        day=day,
        agent="green",
        action=f"{entity_type}s.pay" if entity_type != "vendor_change" else "vendor_changes.approve",
        entity_type=entity_type,
        entity_id=entity_id,
        amount=amount,
        verdict=verdict,
        reason=f"{verdict} by {','.join(rules) or 'none'}",
        rules_fired=rules,
        enforced=enforced,
    )


async def _escalation(ep: str, verdict_id: str, status: str) -> str:
    eid = f.uid("esc")
    await db.execute("INSERT INTO escalations (id, episode_id, verdict_id, status, expires_at) VALUES ($1,$2,$3,$4, now())", eid, ep, verdict_id, status)
    return eid


async def _build(ep: str) -> dict[str, Any]:
    """An enforce run with every kind of row the report reads. Returns the ids the assertions need."""
    ids: dict[str, Any] = {}
    # ghost_vendor: a red vendor's invoice paid with only a note -> gap "note only"
    a = ids["gv"] = await f.attack(ep, day=0, scheme_id="ghost_vendor", target_amount=4380.0)
    gv_vendor = await f.vendor(ep, origin="red", bank_account="ACCT-GHOST")
    inv = ids["gv_inv"] = await f.invoice(ep, gv_vendor, amount=4380.0, origin="red", status="paid", attack_id=a, day=0)
    await f.payment(ep, inv, amount=4380.0, to_account="ACCT-GHOST", day=0, origin_of_source="red")
    ids["gv_vd"] = await _verdict(ep, "invoice", inv, "allow", ["vendor_age_lt_7d"], amount=4380.0, day=0)

    # ghost_employee: red expenses blocked by no_hr_record -> caught, no gap
    a = ids["ge"] = await f.attack(ep, day=1, scheme_id="ghost_employee", target_amount=700.0)
    emp = await f.insert(
        "employees", episode_id=ep, name="Ghost", role="contractor", salary=1, bank_account="EMP-G", start_day=1, origin="red", hr_record=False
    )
    for amt in (300.0, 400.0):
        exp = await f.expense(ep, emp, amount=amt, origin="red", status="blocked", attack_id=a)
        await _verdict(ep, "expense", exp, "block", ["no_hr_record"], amount=amt)

    # duplicate_invoice: escalated, a human approved it, paid -> gap "escalation approved"
    real = await f.vendor(ep)
    a = ids["dup"] = await f.attack(ep, day=2, scheme_id="duplicate_invoice", target_amount=1200.0)
    inv = await f.invoice(ep, real, amount=1200.0, origin="red", status="paid", attack_id=a, day=2)
    await f.payment(ep, inv, amount=1200.0, to_account="ACCT-OLD", day=2, origin_of_source="red")
    vd = await _verdict(ep, "invoice", inv, "escalate", ["duplicate_amount_match"], amount=1200.0, day=2)
    ids["dup_esc"] = await _escalation(ep, vd, "approved")

    # expense_inflation: paid with no rule, blue flagged it afterwards -> gap "audit only"
    a = ids["ei"] = await f.attack(ep, day=3, scheme_id="expense_inflation", target_amount=346.15)
    emp2 = await f.employee(ep)
    exp = await f.expense(ep, emp2, amount=346.15, origin="red", status="paid", attack_id=a)
    await f.insert("payments", episode_id=ep, expense_id=exp, amount=346.15, to_account="EMP-1", paid_day=3, paid_by="green", origin_of_source="red")
    await _verdict(ep, "expense", exp, "allow", [], amount=346.15, day=3)
    ids["ei_flag"] = await f.flag(ep, "expense", exp, day=4)

    # bank_swap: the change escalated and timed out (blocked) -> blocked, no money left
    sw_vendor = await f.vendor(ep)
    a = ids["bs"] = await f.attack(ep, day=3, scheme_id="bank_swap", target_amount=8000.0)
    ch = await f.change(ep, sw_vendor, day=3, status="blocked", resolved_day=3, attack_id=a)
    vd = await _verdict(ep, "vendor_change", ch, "escalate", ["bank_change_with_open_invoices"], day=3)
    await _escalation(ep, vd, "timeout")

    # legit work: one blocked (false positive), one escalated and approved, one clean
    legit = await f.vendor(ep)
    fp = ids["fp_inv"] = await f.invoice(ep, legit, amount=2500.0, status="blocked", day=1)
    await _verdict(ep, "invoice", fp, "block", ["near_threshold"], amount=2500.0)
    esc_inv = ids["legit_esc_inv"] = await f.invoice(ep, legit, amount=900.0, status="paid", day=2)
    vd = await _verdict(ep, "invoice", esc_inv, "escalate", ["near_threshold"], amount=900.0, day=2)
    await _escalation(ep, vd, "approved")
    ok = await f.invoice(ep, legit, amount=100.0, status="paid", day=2)
    await _verdict(ep, "invoice", ok, "allow", ["vendor_age_lt_7d"], amount=100.0, day=2)

    await db.execute("INSERT INTO reports (id, episode_id, day, markdown, posted_by) VALUES ($1,$2,0,'# r','blue')", f.uid("rpt"), ep)
    await db.execute("UPDATE episodes SET days=5, current_day=5, status='finished' WHERE id=$1", ep)
    await score.resolve_attacks(ep, 5)
    return ids


async def test_controls_report_for_a_finished_run(episode: str) -> None:
    ids = await _build(episode)
    async with _client() as c:
        r = await c.get(f"/api/fe/episodes/{episode}/controls", headers=f.auth())
        assert r.status_code == 200, r.text
        rep = r.json()
        sc = (await c.get(f"/api/episodes/{episode}/score", headers=f.auth())).json()

    assert not (_keys(rep) & GROUND_TRUTH_KEYS)
    assert rep["final"] is True and rep["source"] == "ledger"
    assert rep["episode"]["id"] == episode and rep["episode"]["controller_mode"] == "enforce" and rep["episode"]["seed"] == 42
    assert rep["score"] == sc
    # ghost vendor paid to its own (red) account; duplicate and inflated expense paid to real parties
    assert (rep["lost"], rep["to_attacker_accounts"], rep["to_real_parties"]) == (sc["dollars_extracted"], 4380.0, round(1200 + 346.15, 2))

    controls = {c["control_id"]: c for c in rep["controls"]}
    hr = controls["no_hr_record"]
    assert (hr["fired"], hr["blocks"], hr["effect"], hr["schemes"]) == (2, 2, "block", ["ghost_employee"])
    assert hr["on_fraud"] == {"n": 2, "dollars": 700.0, "stopped": 2} and hr["on_legit"]["n"] == 0
    age = controls["vendor_age_lt_7d"]
    assert (age["notes"], age["effect"]) == (2, "note")
    assert age["on_fraud"] == {"n": 1, "dollars": 4380.0, "stopped": 0} and age["on_legit"] == {"n": 1, "dollars": 100.0, "stopped": 0}
    near = controls["near_threshold"]
    assert (near["blocks"], near["escalations"], near["on_fraud"]["n"], near["on_legit"]["n"]) == (1, 1, 0, 2)
    assert controls["bank_change_with_open_invoices"]["effect"] == "escalate"
    assert controls["bank_change_with_open_invoices"]["schemes"] == ["bank_swap"]

    schemes = {s["scheme_id"]: s for s in rep["schemes"]}
    assert list(schemes) == ["ghost_vendor", "ghost_employee", "duplicate_invoice", "expense_inflation", "bank_swap"]
    assert schemes["ghost_vendor"]["extracted"] == 4380.0 and schemes["ghost_vendor"]["outcomes"]["extracted"] == 1
    assert schemes["ghost_employee"]["outcomes"]["blocked"] == 1 and schemes["ghost_employee"]["caught_by"] == ["no_hr_record"]
    assert schemes["ghost_employee"]["detection_latency_days"] == 0
    assert schemes["bank_swap"]["outcomes"]["blocked"] == 1 and schemes["bank_swap"]["escalations"]["timeout"] == 1
    assert schemes["expense_inflation"]["flags"] == 1

    gaps = {g["scheme_id"]: g["why"] for g in rep["gaps"]}
    assert gaps == {"ghost_vendor": "note only", "duplicate_invoice": "escalation approved", "expense_inflation": "audit only"}
    assert [g["scheme_id"] for g in rep["gaps"]] == ["ghost_vendor", "duplicate_invoice", "expense_inflation"]  # biggest loss first

    fp = rep["false_positives"]
    assert fp["cost"] == sc["false_positive_cost"] and fp["legit_blocked"] == sc["legit_blocked"] == 1 and fp["legit_escalated"] == 1
    items = {i["entity_id"]: i for i in fp["items"]}
    assert items[ids["fp_inv"]]["verdict"] == "block" and items[ids["fp_inv"]]["rules"] == ["near_threshold"]
    assert items[ids["fp_inv"]]["cost"] == round(2500 * fp["penalty"]["rate"] + fp["penalty"]["flat"], 2)
    assert items[ids["legit_esc_inv"]]["verdict"] == "escalate"
    assert round(sum(i["cost"] for i in fp["items"]), 2) == fp["cost"]

    assert rep["audit"] == {"flags_raised": 1, "flags_on_fraud": 1, "flags_on_legit": 0, "vendors_frozen": 0, "fraud_vendors_frozen": 0, "reports": 1}
    ev = {e["scheme_id"]: e for e in rep["evidence"]}
    assert ev["ghost_vendor"]["attack_ids"] == [ids["gv"]] and ev["ghost_vendor"]["verdict_ids"] == [ids["gv_vd"]]
    assert ev["duplicate_invoice"]["escalation_ids"] == [ids["dup_esc"]] and ev["expense_inflation"]["flag_ids"] == [ids["ei_flag"]]
    assert ids["gv_inv"] in ev["ghost_vendor"]["entity_ids"]
    assert rep["totals"]["attempted"] == round(4380 + 700 + 1200 + 346.15 + 8000, 2) and rep["totals"]["schemes_with_loss"] == 3


async def test_controls_report_while_running_is_not_final_and_unknown_episode_is_404(episode: str) -> None:
    await db.execute("UPDATE episodes SET status='running' WHERE id=$1", episode)
    async with _client() as c:
        r = await c.get(f"/api/fe/episodes/{episode}/controls", headers=f.auth())
        assert r.status_code == 200 and r.json()["final"] is False
        assert r.json()["controls"] == [] and r.json()["schemes"] == [] and r.json()["gaps"] == []
        assert (await c.get("/api/fe/episodes/ep_nope/controls", headers=f.auth())).status_code == 404
        assert (await c.get(f"/api/fe/episodes/{episode}/controls")).status_code == 401
        assert (await c.get(f"/api/fe/episodes/{episode}/controls", headers=f.auth("red", episode=episode))).status_code in (401, 403)


async def test_controls_report_for_a_replay_comes_from_its_events(pg: None) -> None:
    rep_id = f.uid("replay_ctl")
    await db.execute("INSERT INTO episodes (id, seed, controller_mode, days, status, current_day) VALUES ($1, 42, 'enforce', 6, 'finished', 6)", rep_id)
    for e in (json.loads(line) for line in RECORDING.read_text().splitlines() if line.strip()):
        await db.execute(
            "INSERT INTO events (episode_id, day, type, agent, payload) VALUES ($1,$2,$3,$4,$5)", rep_id, e["day"], e["type"], e["agent"], e["payload"]
        )
    async with _client() as c:
        r = await c.get(f"/api/fe/episodes/{rep_id}/controls", headers=f.auth())
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["source"] == "events" and rep["final"] is True and not (_keys(rep) & GROUND_TRUTH_KEYS)
    assert rep["score"]["dollars_extracted"] == 20350.37
    assert rep["lost"] == 20350.37 and rep["to_attacker_accounts"] is None and rep["to_real_parties"] is None  # no payee accounts in events
    assert {g["scheme_id"]: g["why"] for g in rep["gaps"]}["ghost_vendor"] == "note only"


# ---------- no database ----------


def _recorded_report() -> dict[str, Any]:
    evs = [json.loads(line) for line in RECORDING.read_text().splitlines() if line.strip()]
    end = next(e for e in evs if e["type"] == "episode.ended")
    ep = {"id": evs[0]["episode_id"], "seed": 42, "controller_mode": "enforce", "days": 6, "status": "finished", "current_day": 6}
    return build_controls_report(ep, end["payload"]["final_score"], _facts_from_events(ep["id"], evs), fp_rate=0.02, fp_flat=50.0)


def test_recorded_demo_reads_as_the_demo_did() -> None:
    rep = _recorded_report()
    assert not (_keys(rep) & GROUND_TRUTH_KEYS)
    schemes = {s["scheme_id"]: s for s in rep["schemes"]}
    assert schemes["ghost_vendor"]["extracted"] == 4380.0 and schemes["threshold_split"]["extracted"] == 13800.0
    assert schemes["bank_swap"]["outcomes"]["partial"] == 1 and schemes["bank_swap"]["caught_by"] == ["bank_change_with_open_invoices"]
    assert schemes["ghost_employee"]["outcomes"]["blocked"] == 1 and schemes["ghost_employee"]["caught_by"] == ["no_hr_record"]
    gaps = {g["scheme_id"]: g for g in rep["gaps"]}
    assert gaps["ghost_vendor"]["why"] == "note only" and gaps["ghost_vendor"]["controls_on_paid"] == ["vendor_age_lt_7d"]
    assert gaps["threshold_split"]["why"] == "note only"
    assert gaps["bank_swap"]["why"] == "no control fired" and gaps["bank_swap"]["caught_elsewhere"] == ["bank_change_with_open_invoices"]
    assert gaps["expense_inflation"]["why"] == "no control fired"
    assert rep["false_positives"]["cost"] == 50.0 and rep["false_positives"]["legit_blocked"] == 1
    assert rep["false_positives"]["items"][0]["entity_type"] == "vendor_change"
    assert rep["controls"][0]["control_id"] == "no_hr_record"


def test_shadow_blocks_that_did_not_stop_the_money_are_not_enforced() -> None:
    facts = {
        "source": "ledger",
        "attacks": [
            {
                "id": "atk_1",
                "scheme_id": "ghost_vendor",
                "display_name": "Ghost Vendor",
                "day_launched": 0,
                "target_amount": 100.0,
                "outcome": "extracted",
                "amount_extracted": 100.0,
                "detected_day": 0,
            }
        ],
        "fraud": {"inv_1": "atk_1"},
        "paid": {"atk_1": {"inv_1"}},
        "legit": {"inv_2": {"entity_type": "invoice", "amount": 1000.0, "ended_blocked": False}},
        "verdicts": [
            {
                "id": "vd_1",
                "day": 0,
                "action": "invoices.pay",
                "entity_type": "invoice",
                "entity_id": "inv_1",
                "amount": 100.0,
                "verdict": "block",
                "reason": "r",
                "rules": ["learned:young_vendor_any_amount"],
                "enforced": False,
            },
            {
                "id": "vd_2",
                "day": 0,
                "action": "invoices.pay",
                "entity_type": "invoice",
                "entity_id": "inv_2",
                "amount": 1000.0,
                "verdict": "block",
                "reason": "r",
                "rules": ["learned:young_vendor_any_amount"],
                "enforced": False,
            },
        ],
        "escalations": {},
        "flags": [],
        "frozen": set(),
        "reports": 0,
    }
    ep = {"id": "ep_x", "status": "running", "controller_mode": "shadow"}
    rep = build_controls_report(ep, {"false_positive_cost": 70.0}, facts, fp_rate=0.02, fp_flat=50.0)
    assert rep["final"] is False
    assert rep["gaps"][0]["why"] == "not enforced"
    (c,) = rep["controls"]
    assert c["learned"] is True and c["effect"] == "block" and c["on_fraud"]["stopped"] == 1 and c["on_legit"]["stopped"] == 1
    (item,) = rep["false_positives"]["items"]
    assert item["enforced"] is False and item["cost"] == 70.0


async def test_lost_money_is_split_by_where_it_landed(episode: str) -> None:
    """Ghost vendor: paid to the red vendor's own account (attacker). Blocked bank swap: the fake invoice was still paid,
    into the vendor's real account (real party). Approved bank swap: a legit invoice diverted to the swapped-in account
    (attacker). Duplicate on a real vendor: real party."""
    gv = await f.attack(episode, day=0, scheme_id="ghost_vendor", target_amount=4380.0)
    ghost = await f.vendor(episode, origin="red", bank_account="ACCT-GHOST")
    inv = await f.invoice(episode, ghost, amount=4380.0, origin="red", status="paid", attack_id=gv)
    await f.payment(episode, inv, amount=4380.0, to_account="ACCT-GHOST", day=0, origin_of_source="red")

    blocked = await f.attack(episode, day=1, scheme_id="bank_swap", target_amount=1824.22)
    real = await f.vendor(episode, bank_account="ACCT-REAL")
    await f.change(episode, real, day=1, status="blocked", resolved_day=1, new_value="ACCT-RED-1", attack_id=blocked)
    inv = await f.invoice(episode, real, amount=1824.22, origin="red", status="paid", attack_id=blocked, day=1)
    await f.payment(episode, inv, amount=1824.22, to_account="ACCT-REAL", day=1, origin_of_source="red")

    swapped = await f.attack(episode, day=2, scheme_id="bank_swap", target_amount=900.0)
    victim = await f.vendor(episode, bank_account="ACCT-RED-2")  # approve_change already wrote the new account
    await f.change(episode, victim, day=2, status="approved", resolved_day=2, new_value="ACCT-RED-2", attack_id=swapped)
    legit = await f.invoice(episode, victim, amount=900.0, status="paid", day=2)
    await f.payment(episode, legit, amount=900.0, to_account="ACCT-RED-2", day=3)

    dup = await f.attack(episode, day=3, scheme_id="duplicate_invoice", target_amount=500.0)
    inv = await f.invoice(episode, real, amount=500.0, origin="red", status="paid", attack_id=dup, day=3)
    await f.payment(episode, inv, amount=500.0, to_account="ACCT-REAL", day=3, origin_of_source="red")

    await db.execute("UPDATE episodes SET days=5, current_day=5, status='finished' WHERE id=$1", episode)
    await score.resolve_attacks(episode, 5)
    async with _client() as c:
        rep = (await c.get(f"/api/fe/episodes/{episode}/controls", headers=f.auth())).json()
    assert not (_keys(rep) & GROUND_TRUTH_KEYS)
    # #207: a blocked swap's decoy paid into the real account scores $0, so it is in neither part
    assert rep["lost"] == rep["score"]["dollars_extracted"] == round(4380 + 900 + 500, 2)
    assert rep["to_attacker_accounts"] == 4380 + 900
    assert rep["to_real_parties"] == 500
    schemes = {s["scheme_id"]: s for s in rep["schemes"]}
    assert (schemes["ghost_vendor"]["lost"], schemes["ghost_vendor"]["to_attacker_accounts"], schemes["ghost_vendor"]["to_real_parties"]) == (4380, 4380, 0)
    assert schemes["bank_swap"]["lost"] == 900
    assert (schemes["bank_swap"]["to_attacker_accounts"], schemes["bank_swap"]["to_real_parties"]) == (900, 0)
    assert (schemes["duplicate_invoice"]["to_attacker_accounts"], schemes["duplicate_invoice"]["to_real_parties"]) == (0, 500)
    for s in rep["schemes"]:
        assert round(s["to_attacker_accounts"] + s["to_real_parties"], 2) == s["lost"] == s["extracted"]
    assert rep["unattributed"] == 0


async def test_unattributed_red_payment_reconciles_the_scheme_table(episode: str) -> None:
    """A red invoice paid before red declared any attack has no attack_id: it is lost money no scheme row carries."""
    gv = await f.attack(episode, day=0, scheme_id="ghost_vendor", target_amount=1000.0)
    ghost = await f.vendor(episode, origin="red", bank_account="ACCT-GHOST")
    inv = await f.invoice(episode, ghost, amount=1000.0, origin="red", status="paid", attack_id=gv)
    await f.payment(episode, inv, amount=1000.0, to_account="ACCT-GHOST", day=0, origin_of_source="red")
    stray = await f.invoice(episode, ghost, amount=250.5, origin="red", status="paid")
    await f.payment(episode, stray, amount=250.5, to_account="ACCT-GHOST", day=0, origin_of_source="red")
    await db.execute("UPDATE episodes SET status='finished' WHERE id=$1", episode)
    await score.resolve_attacks(episode, 1)
    async with _client() as c:
        rep = (await c.get(f"/api/fe/episodes/{episode}/controls", headers=f.auth())).json()
    assert rep["lost"] == 1250.5 and rep["unattributed"] == 250.5
    assert round(sum(s["lost"] for s in rep["schemes"]) + rep["unattributed"], 2) == rep["lost"]
    assert (rep["to_attacker_accounts"], rep["to_real_parties"]) == (1250.5, 0)


async def test_false_positives_agree_with_the_score_for_a_diverted_invoice_in_shadow(episode: str) -> None:
    """Shadow: a would-have block on a legit invoice before the red swap went live; the invoice was then paid into the
    swapped account. score.compute still charges it (it was not stopped while the swap was live), so the report must too."""
    await db.execute("UPDATE episodes SET controller_mode='shadow', status='finished' WHERE id=$1", episode)
    atk = await f.attack(episode, day=1, scheme_id="bank_swap", target_amount=900.0)
    victim = await f.vendor(episode, bank_account="ACCT-RED")
    await f.change(episode, victim, day=2, status="approved", resolved_day=2, new_value="ACCT-RED", attack_id=atk)
    inv = await f.invoice(episode, victim, amount=900.0, status="paid", day=1)
    await _verdict(episode, "invoice", inv, "block", ["near_threshold"], amount=900.0, day=1, enforced=False)
    await f.payment(episode, inv, amount=900.0, to_account="ACCT-RED", day=3)
    await score.resolve_attacks(episode, 4)
    async with _client() as c:
        rep = (await c.get(f"/api/fe/episodes/{episode}/controls", headers=f.auth())).json()
    sc, fp = rep["score"], rep["false_positives"]
    assert sc["legit_blocked"] == fp["legit_blocked"] == 1 and fp["legit_escalated"] == 0
    assert round(sum(i["cost"] for i in fp["items"]), 2) == fp["cost"] == sc["false_positive_cost"] > 0
    assert [i["entity_id"] for i in fp["items"]] == [inv] and fp["items"][0]["enforced"] is False
    assert rep["lost"] == 900 and rep["to_attacker_accounts"] == 900 and rep["to_real_parties"] == 0


async def test_schemes_use_live_attack_scores_not_stale_stored_columns(episode: str) -> None:
    """Prod, ep_d9b561111d60 after #207: the bank_swap row still said partial / $1,824.22 (stored before #207) while
    score.compute scores the blocked swap's decoy, paid to the vendor's real account, as $0. Rows must come from the
    same live evaluation as the top level, so unattributed is never negative."""
    gv = await f.attack(episode, day=0, scheme_id="ghost_vendor", target_amount=4380.0, outcome="extracted", amount_extracted=4380.0)
    ghost = await f.vendor(episode, origin="red", bank_account="ACCT-GHOST")
    inv = await f.invoice(episode, ghost, amount=4380.0, origin="red", status="paid", attack_id=gv)
    await f.payment(episode, inv, amount=4380.0, to_account="ACCT-GHOST", day=0, origin_of_source="red")

    # stored before the scoring change: partial, $1,824.22 extracted
    bs = await f.attack(episode, day=1, scheme_id="bank_swap", target_amount=1824.22, outcome="partial", amount_extracted=1824.22, detected_day=1)
    real = await f.vendor(episode, bank_account="ACCT-REAL")
    ch = await f.change(episode, real, day=1, status="blocked", resolved_day=1, new_value="ACCT-RED", attack_id=bs)
    await _verdict(episode, "vendor_change", ch, "escalate", ["bank_change_with_open_invoices"], day=1)
    decoy = await f.invoice(episode, real, amount=1824.22, origin="red", status="paid", attack_id=bs, day=1)
    await f.payment(episode, decoy, amount=1824.22, to_account="ACCT-REAL", day=1, origin_of_source="red")
    await db.execute("UPDATE episodes SET days=6, current_day=6, status='finished' WHERE id=$1", episode)

    async with _client() as c:
        rep = (await c.get(f"/api/fe/episodes/{episode}/controls", headers=f.auth())).json()
    assert rep["score"]["dollars_extracted"] == rep["lost"] == 4380.0
    schemes = {s["scheme_id"]: s for s in rep["schemes"]}
    swap = schemes["bank_swap"]
    assert (swap["lost"], swap["extracted"], swap["to_attacker_accounts"], swap["to_real_parties"]) == (0, 0, 0, 0)
    assert swap["outcomes"]["blocked"] == 1 and swap["outcomes"]["partial"] == 0
    assert swap["caught_by"] == ["bank_change_with_open_invoices"] and swap["detection_latency_days"] == 0
    assert "bank_swap" not in {g["scheme_id"] for g in rep["gaps"]}
    assert rep["unattributed"] >= 0
    assert rep["unattributed"] == 0 and round(sum(s["lost"] for s in rep["schemes"]), 2) == rep["lost"]
    assert (rep["to_attacker_accounts"], rep["to_real_parties"]) == (4380.0, 0)
    # a read view: the stored columns are left as they were
    row = await db.fetchrow("SELECT outcome, amount_extracted FROM attacks WHERE id=$1", bs)
    assert (row["outcome"], float(row["amount_extracted"])) == ("partial", 1824.22)
