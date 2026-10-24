"""DB: the human-in-the-loop escalation path end to end through the real routes.

Green's gated request is held in one task while the operator resolves through
POST /api/escalations/{id}/resolve in another, both against the same ASGI app (README §3
"Escalation", contracts/events.md escalation.*, ledger-api.yaml /escalations).
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
import pytest

from app import db
from app.auth import Caller
from app.config import settings
from app.gate import gatekeeper as gate
from app.main import app
from app.scoring import score
from tests import factories as f

pytestmark = pytest.mark.usefixtures("pg")

OP = f.auth()  # operator


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bf", timeout=30)


def _key() -> str:
    return f"tu_{uuid.uuid4().hex}"


def _green(episode: str, key: str, day: int = 1) -> dict[str, str]:
    return f.auth("green", episode=episode, day=day, tool_use_id=key)


@pytest.fixture
def short_hold(monkeypatch: pytest.MonkeyPatch) -> float:
    monkeypatch.setattr(settings, "escalation_timeout_sec", 2)
    return 2.0


@pytest.fixture
def blue_escalates(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Stand-in for POST blue/gate that escalates everything."""
    asked: list[dict[str, Any]] = []

    async def ask(c: Caller, mode: str, action: str, et: str | None, eid: str | None, amount: float | None, args: dict, context: dict):
        asked.append({"key": c.tool_use_id, "action": action, "entity_id": eid, "mode": mode})
        return "escalate", "Needs human review: near_threshold.", 0.9, ["near_threshold"]

    monkeypatch.setattr(gate, "_ask_blue", ask)
    return asked


async def _open_escalation(cl: httpx.AsyncClient, episode: str, *, timeout: float = 5.0) -> dict[str, Any]:
    """Poll the operator queue until exactly one escalation is open for the episode."""
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        r = await cl.get("/api/escalations", params={"episode_id": episode}, headers=OP)
        assert r.status_code == 200
        if r.json():
            (esc,) = r.json()
            return esc
        await asyncio.sleep(0.02)
    raise AssertionError("no escalation opened")


async def _events(episode: str, *types: str) -> list[dict[str, Any]]:
    rows = await db.fetch("SELECT type, agent, payload FROM events WHERE episode_id=$1 AND type = ANY($2::text[]) ORDER BY id", episode, list(types))
    return [dict(r) for r in rows]


async def _audit(episode: str, key: str) -> list[tuple[str, int, str | None]]:
    rows = await db.fetch("SELECT action, http_status, verdict_id FROM audit_log WHERE episode_id=$1 AND tool_use_id=$2 ORDER BY id", episode, key)
    return [(r["action"], r["http_status"], r["verdict_id"]) for r in rows]


ORDER = ("gate.verdict", "escalation.opened", "escalation.resolved", "ledger.mutation")


# ---------- 1-3: approve / block / timeout ----------


async def test_enforce_escalate_then_approve_proceeds_once(episode: str, blue_escalates: list, short_hold: float) -> None:
    vid = await f.vendor(episode)
    inv = await f.invoice(episode, vid, amount=4_900.0, status="approved")
    key = _key()
    async with _client() as cl:
        held = asyncio.create_task(cl.post(f"/api/invoices/{inv}/pay", headers=_green(episode, key)))
        esc = await _open_escalation(cl, episode)
        assert not held.done()  # green's request is being held
        assert esc["status"] == "open" and esc["action"] == "invoices.pay" and float(esc["amount"]) == 4_900.0 and esc["entity_id"] == inv
        assert esc["reason"] == "Needs human review: near_threshold." and esc["expires_at"]
        r = await cl.post(f"/api/escalations/{esc['id']}/resolve", json={"decision": "approve", "by": "judge-1"}, headers=OP)
        assert r.status_code == 200
        resp = await held
    assert resp.status_code == 200, resp.text
    assert resp.json()["invoice_id"] == inv and "origin" not in resp.json() and "origin_of_source" not in resp.json()

    assert await db.fetchval("SELECT COUNT(*) FROM payments WHERE invoice_id=$1", inv) == 1
    assert await db.fetchval("SELECT status FROM invoices WHERE id=$1", inv) == "paid"
    row = await db.fetchrow("SELECT * FROM escalations WHERE id=$1", esc["id"])
    assert (row["status"], row["resolved_by"]) == ("approved", "judge-1") and row["resolved_at"] is not None
    v = await db.fetchrow("SELECT * FROM verdicts WHERE id=$1", esc["verdict_id"])
    assert (v["verdict"], v["enforced"], v["idempotency_key"], v["entity_id"]) == ("escalate", True, key, inv)
    assert await _audit(episode, key) == [("invoices.pay", 200, v["id"])]

    evs = await _events(episode, *ORDER)
    assert [e["type"] for e in evs] == list(ORDER)
    opened, resolved, mutation = evs[1]["payload"], evs[2], evs[3]["payload"]
    assert opened["escalation_id"] == esc["id"] and opened["verdict_id"] == v["id"] and opened["entity_id"] == inv and opened["amount"] == 4_900.0
    assert resolved["payload"] == {"escalation_id": esc["id"], "decision": "approve", "by": "judge-1"} and resolved["agent"] == "human"
    assert mutation["verdict_id"] == v["id"] and mutation["action"] == "invoices.pay"
    assert len(blue_escalates) == 1


async def test_enforce_escalate_then_block_is_403_and_marks_entity_blocked(episode: str, blue_escalates: list, short_hold: float) -> None:
    vid = await f.vendor(episode)
    inv = await f.invoice(episode, vid, amount=4_800.0)
    key = _key()
    async with _client() as cl:
        held = asyncio.create_task(cl.post(f"/api/invoices/{inv}/approve", headers=_green(episode, key)))
        esc = await _open_escalation(cl, episode)
        r = await cl.post(f"/api/escalations/{esc['id']}/resolve", json={"decision": "block", "by": "judge-2"}, headers=OP)
        assert r.status_code == 200
        resp = await held
    assert resp.status_code == 403
    body = resp.json()
    assert body["verdict"] == "block" and body["reason"] == "escalated; block" and body["verdict_id"] == esc["verdict_id"]
    assert await db.fetchval("SELECT status FROM invoices WHERE id=$1", inv) == "blocked"
    assert await db.fetchval("SELECT status_day FROM invoices WHERE id=$1", inv) == 1
    assert (await db.fetchrow("SELECT status, resolved_by FROM escalations WHERE id=$1", esc["id"]))[:] == ("blocked", "judge-2")
    assert await _audit(episode, key) == [("invoices.approve", 403, esc["verdict_id"])]
    evs = await _events(episode, *ORDER)
    assert [e["type"] for e in evs] == ["gate.verdict", "escalation.opened", "escalation.resolved"]  # no ledger.mutation
    assert evs[2]["payload"]["decision"] == "block"


async def test_enforce_escalate_with_no_decision_times_out_to_block(episode: str, blue_escalates: list, short_hold: float) -> None:
    vid = await f.vendor(episode)
    ch = await f.change(episode, vid, origin="sim")
    key = _key()
    async with _client() as cl:
        t0 = asyncio.get_running_loop().time()
        resp = await cl.post(f"/api/vendor_changes/{ch}/approve", headers=_green(episode, key))
        waited = asyncio.get_running_loop().time() - t0
    assert resp.status_code == 403 and resp.json()["reason"] == "escalated; timeout"
    assert short_hold <= waited < short_hold + 2
    assert await db.fetchval("SELECT status FROM vendor_changes WHERE id=$1", ch) == "blocked"
    assert await db.fetchval("SELECT bank_account FROM vendors WHERE id=$1", vid) == "ACCT-OLD"
    row = await db.fetchrow("SELECT * FROM escalations WHERE episode_id=$1", episode)
    assert row["status"] == "timeout" and row["resolved_at"] is not None and row["resolved_by"] is None
    evs = await _events(episode, *ORDER)
    assert [e["type"] for e in evs] == ["gate.verdict", "escalation.opened", "escalation.resolved"]
    assert evs[2]["payload"] == {"escalation_id": row["id"], "decision": "timeout", "by": "system"}
    assert not gate._escalation_waiters  # the waiter is cleaned up


# ---------- 4: resolve edge cases ----------


async def test_resolve_twice_unknown_bad_decision_and_after_timeout(episode: str, blue_escalates: list, short_hold: float) -> None:
    vid = await f.vendor(episode)
    a = await f.invoice(episode, vid, amount=4_850.0)
    b = await f.invoice(episode, vid, amount=4_860.0)
    async with _client() as cl:
        held = asyncio.create_task(cl.post(f"/api/invoices/{a}/approve", headers=_green(episode, _key())))
        esc = await _open_escalation(cl, episode)
        bad = await cl.post(f"/api/escalations/{esc['id']}/resolve", json={"decision": "maybe"}, headers=OP)
        assert bad.status_code == 422
        assert (await cl.post(f"/api/escalations/{esc['id']}/resolve", json={"decision": "approve"}, headers=OP)).status_code == 200
        assert (await held).status_code == 200
        again = await cl.post(f"/api/escalations/{esc['id']}/resolve", json={"decision": "block"}, headers=OP)
        assert again.status_code == 409
        assert (await db.fetchval("SELECT status FROM escalations WHERE id=$1", esc["id"])) == "approved"  # the second decision did not stick
        assert (await db.fetchval("SELECT resolved_by FROM escalations WHERE id=$1", esc["id"])) == "judge"  # `by` defaults to judge
        unknown = await cl.post("/api/escalations/esc_nope/resolve", json={"decision": "approve"}, headers=OP)
        assert unknown.status_code == 409  # the route does not distinguish unknown from resolved (contract lists only 409)

        timed = await cl.post(f"/api/invoices/{b}/approve", headers=_green(episode, _key()))
        assert timed.status_code == 403
        late_id = await db.fetchval("SELECT e.id FROM escalations e JOIN verdicts v ON v.id=e.verdict_id WHERE v.entity_id=$1", b)
        late = await cl.post(f"/api/escalations/{late_id}/resolve", json={"decision": "approve"}, headers=OP)
        assert late.status_code == 409
        # agents cannot resolve: operator-only route
        assert (await cl.post(f"/api/escalations/{late_id}/resolve", json={"decision": "approve"}, headers=f.auth("green", episode=episode))).status_code == 403
    assert await db.fetchval("SELECT status FROM invoices WHERE id=$1", b) == "blocked"
    resolved = [e["payload"]["decision"] for e in await _events(episode, "escalation.resolved")]
    assert resolved == ["approve", "timeout"]


async def test_operator_list_filters_by_status(episode: str, blue_escalates: list, short_hold: float) -> None:
    vid = await f.vendor(episode)
    inv = await f.invoice(episode, vid, amount=4_870.0)
    async with _client() as cl:
        assert (await cl.post(f"/api/invoices/{inv}/approve", headers=_green(episode, _key()))).status_code == 403
        assert (await cl.get("/api/escalations", params={"episode_id": episode}, headers=OP)).json() == []
        rows = (await cl.get("/api/escalations", params={"episode_id": episode, "status": "all"}, headers=OP)).json()
        assert [r["status"] for r in rows] == ["timeout"]
        assert (await cl.get("/api/escalations", params={"episode_id": episode, "status": "timeout"}, headers=OP)).json()[0]["id"] == rows[0]["id"]


# ---------- 5: blue unreachable in enforce ----------


async def test_blue_unreachable_in_enforce_escalates_and_approve_proceeds(episode: str, monkeypatch: pytest.MonkeyPatch, short_hold: float) -> None:
    monkeypatch.setattr(settings, "blue_url", "http://127.0.0.1:9")  # discard port: connection refused
    monkeypatch.setattr(settings, "gate_timeout_sec", 1)
    vid = await f.vendor(episode)
    inv = await f.invoice(episode, vid, amount=1_200.0)
    key = _key()
    async with _client() as cl:
        held = asyncio.create_task(cl.post(f"/api/invoices/{inv}/approve", headers=_green(episode, key)))
        esc = await _open_escalation(cl, episode)
        assert esc["reason"].startswith("controller unavailable (") and esc["reason"].endswith("defaulted to escalate")
        assert (await cl.post(f"/api/escalations/{esc['id']}/resolve", json={"decision": "approve"}, headers=OP)).status_code == 200
        resp = await held
    assert resp.status_code == 200 and await db.fetchval("SELECT status FROM invoices WHERE id=$1", inv) == "approved"
    v = await db.fetchrow("SELECT verdict, rules_fired, enforced FROM verdicts WHERE id=$1", esc["verdict_id"])
    assert (v["verdict"], list(v["rules_fired"]), v["enforced"]) == ("escalate", ["gate_timeout"], True)


async def test_blue_unreachable_in_enforce_times_out_to_block(episode: str, monkeypatch: pytest.MonkeyPatch, short_hold: float) -> None:
    monkeypatch.setattr(settings, "blue_url", "http://127.0.0.1:9")
    monkeypatch.setattr(settings, "gate_timeout_sec", 1)
    vid = await f.vendor(episode)
    inv = await f.invoice(episode, vid, amount=1_200.0)
    async with _client() as cl:
        resp = await cl.post(f"/api/invoices/{inv}/approve", headers=_green(episode, _key()))
    assert resp.status_code == 403 and resp.json()["reason"] == "escalated; timeout"
    assert await db.fetchval("SELECT status FROM escalations WHERE episode_id=$1", episode) == "timeout"


# ---------- shadow: escalate is recorded, nothing held ----------


async def test_shadow_escalate_is_recorded_not_held(episode: str, blue_escalates: list, short_hold: float) -> None:
    await db.execute("UPDATE episodes SET controller_mode='shadow' WHERE id=$1", episode)
    vid = await f.vendor(episode)
    inv = await f.invoice(episode, vid, amount=4_900.0)
    async with _client() as cl:
        t0 = asyncio.get_running_loop().time()
        resp = await cl.post(f"/api/invoices/{inv}/approve", headers=_green(episode, _key()))
        assert asyncio.get_running_loop().time() - t0 < 1.0
    assert resp.status_code == 200 and await db.fetchval("SELECT status FROM invoices WHERE id=$1", inv) == "approved"
    assert await db.fetchval("SELECT COUNT(*) FROM escalations WHERE episode_id=$1", episode) == 0
    v = await db.fetchrow("SELECT verdict, enforced FROM verdicts WHERE episode_id=$1", episode)
    assert (v["verdict"], v["enforced"]) == ("escalate", False)
    assert blue_escalates[0]["mode"] == "shadow"
    assert [e["type"] for e in await _events(episode, *ORDER)] == ["gate.verdict", "ledger.mutation"]


# ---------- 7: scoring and the frontend view ----------


async def _escalate_and(cl: httpx.AsyncClient, episode: str, path: str, decision: str | None) -> httpx.Response:
    held = asyncio.create_task(cl.post(path, headers=_green(episode, _key())))
    if decision is not None:
        esc = await _open_escalation(cl, episode)
        assert (await cl.post(f"/api/escalations/{esc['id']}/resolve", json={"decision": decision}, headers=OP)).status_code == 200
    return await held


@pytest.mark.parametrize(
    ("decision", "status", "outcome", "blocked"),
    [("approve", 200, "flagged", 0.0), ("block", 403, "blocked", 4_900.0), (None, 403, "blocked", 4_900.0)],
    ids=["approve", "block", "timeout"],
)
async def test_red_invoice_escalated_scores(
    episode: str, blue_escalates: list, short_hold: float, decision: str | None, status: int, outcome: str, blocked: float
) -> None:
    vid = await f.vendor(episode, origin="red")
    atk = await f.attack(episode, day=1, scheme_id="ghost_vendor", target_amount=4_900.0)
    inv = await f.invoice(episode, vid, amount=4_900.0, origin="red", attack_id=atk, day=1)
    async with _client() as cl:
        assert (await _escalate_and(cl, episode, f"/api/invoices/{inv}/approve", decision)).status_code == status
    await score.resolve_attacks(episode, 1)
    a = await db.fetchrow("SELECT outcome, detected_day, amount_extracted FROM attacks WHERE id=$1", atk)
    assert (a["outcome"], a["detected_day"], float(a["amount_extracted"])) == (outcome, 1, 0.0)  # the escalate verdict is the detection
    s = await score.compute(episode)
    assert (s["attacks_caught"], s["dollars_blocked"], s["dollars_extracted"], s["false_positive_cost"]) == (1, blocked, 0.0, 0.0)


async def test_red_invoice_escalated_approved_then_paid_is_extracted(episode: str, blue_escalates: list, short_hold: float) -> None:
    vid = await f.vendor(episode, origin="red")
    atk = await f.attack(episode, day=1, scheme_id="ghost_vendor", target_amount=4_900.0)
    inv = await f.invoice(episode, vid, amount=4_900.0, origin="red", attack_id=atk, day=1)
    async with _client() as cl:
        assert (await _escalate_and(cl, episode, f"/api/invoices/{inv}/approve", "approve")).status_code == 200
        assert (await _escalate_and(cl, episode, f"/api/invoices/{inv}/pay", "approve")).status_code == 200
    await score.resolve_attacks(episode, 1)
    a = await db.fetchrow("SELECT outcome, detected_day FROM attacks WHERE id=$1", atk)
    assert (a["outcome"], a["detected_day"]) == ("extracted", 1)  # the human waved it through: not caught
    s = await score.compute(episode)
    assert (s["attacks_caught"], s["dollars_extracted"]) == (0, 4_900.0)


@pytest.mark.parametrize(("decision", "fp_cost", "legit_blocked"), [("approve", 50.0, 0), ("block", 4_900 * 0.02 + 50.0, 1), (None, 4_900 * 0.02 + 50.0, 1)])
async def test_sim_invoice_escalated_is_a_false_positive_once(
    episode: str, blue_escalates: list, short_hold: float, decision: str | None, fp_cost: float, legit_blocked: int
) -> None:
    """A legit invoice is charged once by its worst outcome: escalated then approved = the flat penalty;
    escalated then blocked or timed out = the blocked cost (rate x amount + flat), not both."""
    vid = await f.vendor(episode)
    inv = await f.invoice(episode, vid, amount=4_900.0, day=1)
    async with _client() as cl:
        await _escalate_and(cl, episode, f"/api/invoices/{inv}/approve", decision)
        if decision == "approve":  # escalated again at pay time and approved: still one item, one charge
            assert (await _escalate_and(cl, episode, f"/api/invoices/{inv}/pay", "approve")).status_code == 200
    s = await score.compute(episode)
    assert s["false_positive_cost"] == pytest.approx(fp_cost) and s["legit_blocked"] == legit_blocked


async def test_fe_escalations_view_and_snapshot_show_the_open_one(episode: str, blue_escalates: list, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "escalation_timeout_sec", 5)
    vid = await f.vendor(episode)
    inv = await f.invoice(episode, vid, amount=4_910.0)
    async with _client() as cl:
        held = asyncio.create_task(cl.post(f"/api/invoices/{inv}/approve", headers=_green(episode, _key())))
        esc = await _open_escalation(cl, episode)
        (row,) = (await cl.get(f"/api/fe/episodes/{episode}/escalations", headers=OP)).json()
        snap = (await cl.get(f"/api/fe/episodes/{episode}/snapshot", headers=OP)).json()
        trail = (await cl.get(f"/api/fe/episodes/{episode}/entities/invoice/{inv}", headers=OP)).json()
        await cl.post(f"/api/escalations/{esc['id']}/resolve", json={"decision": "approve"}, headers=OP)
        assert (await held).status_code == 200
        after = (await cl.get(f"/api/fe/episodes/{episode}/escalations", headers=OP)).json()
    assert row["id"] == esc["id"] and row["status"] == "open" and row["entity_type"] == "invoice" and row["entity_id"] == inv
    assert float(row["amount"]) == 4_910.0 and row["reason"] and row["expires_at"] and list(row["rules_fired"]) == ["near_threshold"]
    vendor = await db.fetchrow("SELECT id, name FROM vendors WHERE id=$1", vid)
    number = await db.fetchval("SELECT invoice_number FROM invoices WHERE id=$1", inv)
    assert (row["vendor_id"], row["vendor_name"], row["invoice_number"]) == (vendor["id"], vendor["name"], number)
    assert row["change_field"] is None and "origin" not in row and "attack_id" not in row
    assert snap["controls"]["open_escalations"] == 1
    assert [e["id"] for e in trail["escalations"]] == [esc["id"]]
    assert [r["status"] for r in after] == ["approved"]  # the fe view lists every status, the operator queue only open ones


# ---------- races, replays and restarts ----------


def _caller(episode: str, key: str) -> Caller:
    return Caller(agent="green", episode_id=episode, day=1, tool_use_id=key)


async def test_blocked_403_names_the_escalation(episode: str, blue_escalates: list, short_hold: float) -> None:
    vid = await f.vendor(episode)
    inv = await f.invoice(episode, vid, amount=4_800.0)
    async with _client() as cl:
        resp = await cl.post(f"/api/invoices/{inv}/approve", headers=_green(episode, _key()))
    esc_id = await db.fetchval("SELECT id FROM escalations WHERE episode_id=$1", episode)
    assert resp.status_code == 403 and resp.json()["escalation_id"] == esc_id


async def test_concurrent_resolves_one_wins_and_green_follows_it(episode: str, blue_escalates: list, short_hold: float) -> None:
    vid = await f.vendor(episode)
    inv = await f.invoice(episode, vid, amount=4_850.0)
    async with _client() as cl:
        held = asyncio.create_task(cl.post(f"/api/invoices/{inv}/approve", headers=_green(episode, _key())))
        esc = await _open_escalation(cl, episode)
        r1, r2 = await asyncio.gather(
            cl.post(f"/api/escalations/{esc['id']}/resolve", json={"decision": "approve", "by": "a"}, headers=OP),
            cl.post(f"/api/escalations/{esc['id']}/resolve", json={"decision": "block", "by": "b"}, headers=OP),
        )
        resp = await held
    assert sorted([r1.status_code, r2.status_code]) == [200, 409]
    (ev,) = [e["payload"] for e in await _events(episode, "escalation.resolved")]
    row = await db.fetchrow("SELECT status, resolved_by FROM escalations WHERE id=$1", esc["id"])
    won = "approve" if r1.status_code == 200 else "block"
    assert ev["decision"] == won and (row["status"], row["resolved_by"]) == (
        {"approve": "approved", "block": "blocked"}[won],
        {"approve": "a", "block": "b"}[won],
    )
    assert resp.status_code == (200 if won == "approve" else 403)
    assert await db.fetchval("SELECT status FROM invoices WHERE id=$1", inv) == ("approved" if won == "approve" else "blocked")


async def test_resolve_landing_between_deadline_and_timeout_write_wins(episode: str, blue_escalates: list, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "escalation_timeout_sec", 1)
    real_close = gate._close
    gap = asyncio.Event()

    async def slow_close(esc_id: str, decision: str, by: str) -> bool:
        if decision == "timeout":
            gap.set()  # the deadline passed; the operator's click lands now, before the timeout write
            await asyncio.sleep(0.3)
        return await real_close(esc_id, decision, by)

    monkeypatch.setattr(gate, "_close", slow_close)
    vid = await f.vendor(episode)
    inv = await f.invoice(episode, vid, amount=4_850.0)
    async with _client() as cl:
        held = asyncio.create_task(cl.post(f"/api/invoices/{inv}/approve", headers=_green(episode, _key())))
        esc = await _open_escalation(cl, episode)
        await gap.wait()
        r = await cl.post(f"/api/escalations/{esc['id']}/resolve", json={"decision": "approve", "by": "late"}, headers=OP)
        resp = await held
    assert r.status_code == 200 and resp.status_code == 200
    assert [e["payload"]["decision"] for e in await _events(episode, "escalation.resolved")] == ["approve"]
    assert await db.fetchval("SELECT status FROM escalations WHERE id=$1", esc["id"]) == "approved"


async def test_same_key_replay_joins_the_open_escalation(episode: str, blue_escalates: list, short_hold: float) -> None:
    vid = await f.vendor(episode)
    inv = await f.invoice(episode, vid, amount=4_850.0)
    key = _key()

    async def check() -> gate.Decision:
        return await gate.check(_caller(episode, key), action="invoices.approve", entity_type="invoice", entity_id=inv, amount=4_850.0)

    async with _client() as cl:
        first = asyncio.create_task(check())
        esc = await _open_escalation(cl, episode)
        second = asyncio.create_task(check())
        await asyncio.sleep(0.2)
        assert not second.done()  # waiting on the same human decision
        assert (await cl.post(f"/api/escalations/{esc['id']}/resolve", json={"decision": "approve"}, headers=OP)).status_code == 200
        a, b = await first, await second
    assert a.allowed and b.allowed and a.verdict_id == b.verdict_id
    assert await db.fetchval("SELECT COUNT(*) FROM escalations WHERE episode_id=$1", episode) == 1
    assert len(blue_escalates) == 1


@pytest.mark.parametrize("decision", ["block", None], ids=["block", "timeout"])
async def test_same_key_retry_after_a_decision_replays_it(episode: str, blue_escalates: list, short_hold: float, decision: str | None) -> None:
    """A gl.post retried with the same key after the human blocked it (or the hold timed out) is
    blocked again at once: same key, same verdict, no second escalation card."""
    key = _key()
    body = {"account": "6000", "debit": 4_900.0, "credit": 0.0, "memo": "x"}
    async with _client() as cl:
        held = asyncio.create_task(cl.post("/api/gl/entries", json=body, headers=_green(episode, key)))
        if decision:
            esc = await _open_escalation(cl, episode)
            await cl.post(f"/api/escalations/{esc['id']}/resolve", json={"decision": decision}, headers=OP)
        first = await held
        t0 = asyncio.get_running_loop().time()
        again = await cl.post("/api/gl/entries", json=body, headers=_green(episode, key))
        assert asyncio.get_running_loop().time() - t0 < 1.0
    want = f"escalated; {decision or 'timeout'}"
    assert first.status_code == again.status_code == 403 and first.json()["reason"] == again.json()["reason"] == want
    assert again.json()["escalation_id"] == first.json()["escalation_id"]
    assert await db.fetchval("SELECT COUNT(*) FROM escalations WHERE episode_id=$1", episode) == 1
    assert await db.fetchval("SELECT COUNT(*) FROM gl_entries WHERE episode_id=$1", episode) == 0


async def _orphan(episode: str) -> tuple[str, str, str]:
    """An open escalation whose held request died with a previous battlefield process."""
    vid = await f.vendor(episode)
    inv = await f.invoice(episode, vid)
    v = await f.verdict(episode, "invoice", inv, verdict="escalate")
    esc_id = f.uid("esc")
    await db.execute("INSERT INTO escalations (id, episode_id, verdict_id, expires_at) VALUES ($1,$2,$3, now() + interval '1 minute')", esc_id, episode, v)
    return esc_id, v, inv


async def test_resolving_an_orphan_after_restart_is_409_and_expires_it(episode: str) -> None:
    esc_id, _, inv = await _orphan(episode)
    async with _client() as cl:
        r = await cl.post(f"/api/escalations/{esc_id}/resolve", json={"decision": "approve"}, headers=OP)
    assert r.status_code == 409  # approving it could never take effect: the held request is gone
    assert await db.fetchval("SELECT status FROM escalations WHERE id=$1", esc_id) == "timeout"
    assert [e["payload"] for e in await _events(episode, "escalation.resolved")] == [{"escalation_id": esc_id, "decision": "timeout", "by": "system"}]
    assert await db.fetchval("SELECT status FROM invoices WHERE id=$1", inv) == "pending"  # untouched; green may retry


async def test_startup_sweep_expires_orphans_only(episode: str, blue_escalates: list, short_hold: float) -> None:
    esc_id, _, _ = await _orphan(episode)
    vid = await f.vendor(episode)
    inv = await f.invoice(episode, vid, amount=4_850.0)
    async with _client() as cl:
        held = asyncio.create_task(cl.post(f"/api/invoices/{inv}/approve", headers=_green(episode, _key())))
        for _ in range(250):
            live = await db.fetchval("SELECT e.id FROM escalations e JOIN verdicts v ON v.id=e.verdict_id WHERE v.entity_id=$1", inv)
            if live:
                break
            await asyncio.sleep(0.02)
        assert await gate.expire_orphaned_escalations() >= 1
        assert await db.fetchval("SELECT status FROM escalations WHERE id=$1", esc_id) == "timeout"
        assert await db.fetchval("SELECT status FROM escalations WHERE id=$1", live) == "open"  # a live hold is left alone
        assert (await cl.post(f"/api/escalations/{live}/resolve", json={"decision": "approve"}, headers=OP)).status_code == 200
        assert (await held).status_code == 200


async def test_same_key_retry_after_restart_opens_a_fresh_escalation(episode: str, blue_escalates: list, short_hold: float) -> None:
    esc_id, vid_, inv = await _orphan(episode)
    key = await db.fetchval("SELECT idempotency_key FROM verdicts WHERE id=$1", vid_)
    await db.execute("UPDATE verdicts SET amount=1000 WHERE id=$1", vid_)
    async with _client() as cl:
        held = asyncio.create_task(cl.post(f"/api/invoices/{inv}/approve", headers=_green(episode, key)))
        for _ in range(250):
            rows = (await cl.get("/api/escalations", params={"episode_id": episode}, headers=OP)).json()
            if rows and rows[0]["id"] != esc_id:
                break
            await asyncio.sleep(0.02)
        (fresh,) = rows  # the orphan is no longer open
        assert fresh["id"] != esc_id and fresh["verdict_id"] == vid_
        assert (await cl.post(f"/api/escalations/{fresh['id']}/resolve", json={"decision": "approve"}, headers=OP)).status_code == 200
        assert (await held).status_code == 200
    assert await db.fetchval("SELECT status FROM escalations WHERE id=$1", esc_id) == "timeout"
    assert blue_escalates == []  # replayed the stored verdict, blue was not asked again


async def test_fe_escalations_view_describes_a_vendor_change(episode: str, blue_escalates: list, short_hold: float) -> None:
    vid = await f.vendor(episode)
    ch = await f.change(episode, vid, origin="sim", new_value="ACCT-NEW")
    async with _client() as cl:
        assert (await cl.post(f"/api/vendor_changes/{ch}/approve", headers=_green(episode, _key()))).status_code == 403  # timed out
        (row,) = (await cl.get(f"/api/fe/episodes/{episode}/escalations", headers=OP)).json()
    name = await db.fetchval("SELECT name FROM vendors WHERE id=$1", vid)
    assert row["amount"] is None and row["entity_type"] == "vendor_change" and row["status"] == "timeout"
    assert (row["vendor_id"], row["vendor_name"], row["change_field"], row["change_old_value"], row["change_new_value"]) == (
        vid,
        name,
        "bank_account",
        "ACCT-OLD",
        "ACCT-NEW",
    )


# ---------- battlefield restart ----------


async def test_startup_recovery_pauses_episodes_fails_replays_and_expires_orphans(episode: str) -> None:
    from app import main

    esc_id, _, _ = await _orphan(episode)
    await db.execute("UPDATE episodes SET status='running', current_day=2 WHERE id=$1", episode)
    replay = f.uid("replay_x")
    await db.execute("INSERT INTO episodes (id, seed, controller_mode, status, current_day) VALUES ($1, 1, 'off', 'running', 3)", replay)
    done_replay = f.uid("replay_y")
    await db.execute("INSERT INTO episodes (id, seed, controller_mode, status) VALUES ($1, 1, 'off', 'finished')", done_replay)
    finished = f.uid("ep")
    await db.execute("INSERT INTO episodes (id, seed, controller_mode, status) VALUES ($1, 1, 'off', 'finished')", finished)

    await main.recover_after_restart()

    assert await db.fetchval("SELECT status FROM episodes WHERE id=$1", episode) == "paused"  # never auto-resumed
    replay_row = await db.fetchrow("SELECT status, finished_at FROM episodes WHERE id=$1", replay)
    assert replay_row["status"] == "failed" and replay_row["finished_at"] is not None  # its streaming task died with the process
    assert await db.fetchval("SELECT status FROM episodes WHERE id=$1", finished) == "finished"
    assert await db.fetchval("SELECT status FROM escalations WHERE id=$1", esc_id) == "timeout"
    rows = await db.fetch("SELECT type, day, payload FROM events WHERE episode_id=$1 AND type IN ('error','episode.paused') ORDER BY id", episode)
    assert [(r["type"], r["day"]) for r in rows] == [("error", 2), ("episode.paused", 2)]
    assert rows[0]["payload"] == {"where": "orchestrator", "message": "battlefield restarted mid-episode; resume to continue"}
    replay_events = await db.fetch("SELECT type, day, payload FROM events WHERE episode_id=$1 ORDER BY id", replay)
    assert [(e["type"], e["day"], e["payload"]) for e in replay_events] == [
        ("error", 3, {"where": "replay", "message": "battlefield restarted mid-replay"})
    ]  # no episode.paused: a replay is failed, not paused
    assert await db.fetchval("SELECT status FROM episodes WHERE id=$1", done_replay) == "finished"
    assert await db.fetchval("SELECT COUNT(*) FROM events WHERE episode_id=ANY($1::text[])", [finished, done_replay]) == 0
