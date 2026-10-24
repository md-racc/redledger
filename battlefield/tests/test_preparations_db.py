"""DB: POST/GET /api/preparations (contracts/ledger-api.yaml), the gate half of green's gated actions.

Blue is a stand-in (`gate._ask_blue` patched) except where a test points BLUE_URL at nothing to get
the real fallback. Execution consuming a preparation is step 2b; here the inline gated route still
gates, and must reuse the prepared verdict rather than ask blue again.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
import pytest

from app import db
from app.api import preparations
from app.auth import Caller
from app.config import settings
from app.gate import gatekeeper as gate
from app.main import app
from tests import factories as f

pytestmark = pytest.mark.usefixtures("pg")

OP = f.auth()


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bf", timeout=30)


def _key() -> str:
    return f"tu_{uuid.uuid4().hex}"


def _green(ep: str, key: str, day: int = 1, agent: str = "green") -> dict[str, str]:
    return f.auth(agent, episode=ep, day=day, tool_use_id=key)


async def _episode(mode: str) -> str:
    ep = f.uid("ep")
    await db.execute("INSERT INTO episodes (id, seed, controller_mode) VALUES ($1, 42, $2)", ep, mode)
    return ep


@pytest.fixture
def blue(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stand-in for POST blue/gate: answers `state["verdict"]`, records every call."""
    state: dict[str, Any] = {"verdict": "allow", "calls": []}

    async def ask(c: Caller, mode: str, action: str, et: str | None, eid: str | None, amount: float | None, args: dict, context: dict, **kw: Any):
        state["calls"].append({"key": c.tool_use_id, "action": action, "entity_id": eid, "mode": mode, "amount": amount})
        return state["verdict"], f"stand-in says {state['verdict']}", 0.9, ["near_threshold"]

    monkeypatch.setattr(gate, "_ask_blue", ask)
    return state


async def _prepare(cl: httpx.AsyncClient, ep: str, key: str, action: str, entity_id: str | None, args: dict | None = None, **kw: Any) -> httpx.Response:
    body: dict[str, Any] = {"action": action, "args": args or {}}
    if entity_id is not None:
        body["entity_id"] = entity_id
    return await cl.post("/api/preparations", json=body, headers=_green(ep, key, **kw))


async def _events(ep: str, type_: str) -> list[dict[str, Any]]:
    return [dict(r["payload"]) for r in await db.fetch("SELECT payload FROM events WHERE episode_id=$1 AND type=$2 ORDER BY id", ep, type_)]


async def _invoice(ep: str, **kw: Any) -> str:
    return await f.invoice(ep, await f.vendor(ep), **kw)


# ---------- modes ----------


async def test_off_allows_without_a_gate_call(blue: dict[str, Any]) -> None:
    ep = await _episode("off")
    inv = await _invoice(ep)
    async with _client() as cl:
        r = await _prepare(cl, ep, _key(), "invoices.approve", inv)
    assert r.status_code == 200, r.text
    p = r.json()
    assert (p["effective"], p["decided_by"], p["verdict_id"], p["enforced"], p["consumed"]) == ("allow", "mode", None, False, False)
    assert p["amount"] == 1000.0 and p["controller_mode"] == "off"
    assert blue["calls"] == []
    assert await _events(ep, "gate.verdict") == []


async def test_shadow_records_the_verdict_and_allows(blue: dict[str, Any]) -> None:
    blue["verdict"] = "block"
    ep = await _episode("shadow")
    inv = await _invoice(ep)
    async with _client() as cl:
        r = await _prepare(cl, ep, _key(), "invoices.pay", inv)
    p = r.json()
    assert (p["effective"], p["decided_by"], p["verdict"], p["enforced"], p["cause"]) == ("allow", "gate", "block", False, "control")
    assert await db.fetchval("SELECT status FROM invoices WHERE id=$1", inv) == "pending"


async def test_enforce_allow(blue: dict[str, Any]) -> None:
    ep = await _episode("enforce")
    inv = await _invoice(ep)
    async with _client() as cl:
        r = await _prepare(cl, ep, _key(), "invoices.approve", inv)
    p = r.json()
    assert (p["effective"], p["decided_by"], p["verdict"], p["enforced"]) == ("allow", "gate", "allow", True)
    assert p["rules_fired"] == ["near_threshold"]


async def test_enforce_block_is_200_marks_the_entity_and_moves_no_money(blue: dict[str, Any]) -> None:
    blue["verdict"] = "block"
    ep = await _episode("enforce")
    inv = await _invoice(ep, status="approved")
    key = _key()
    async with _client() as cl:
        r = await _prepare(cl, ep, key, "invoices.pay", inv)
    assert r.status_code == 200
    p = r.json()
    assert (p["effective"], p["decided_by"], p["verdict"], p["cause"]) == ("block", "gate", "block", "control")
    assert await db.fetchval("SELECT status FROM invoices WHERE id=$1", inv) == "blocked"
    assert await db.fetchval("SELECT COUNT(*) FROM payments WHERE episode_id=$1", ep) == 0
    (ev,) = await _events(ep, "gate.verdict")
    assert ev["preparation_id"] == p["preparation_id"] and ev["cause"] == "control" and ev["verdict_id"] == p["verdict_id"]
    assert await _events(ep, "ledger.mutation") == []
    audit = await db.fetchrow("SELECT action, http_status, verdict_id, result FROM audit_log WHERE episode_id=$1 AND tool_use_id=$2", ep, key)
    assert (audit["action"], audit["http_status"], audit["verdict_id"]) == ("prepare:invoices.pay", 200, p["verdict_id"])
    assert dict(audit["result"])["effective"] == "block"


async def test_vendor_change_and_expense_and_gl(blue: dict[str, Any]) -> None:
    ep = await _episode("enforce")
    vid = await f.vendor(ep)
    ch = await f.change(ep, vid)
    ex = await f.expense(ep, await f.employee(ep), status="approved")
    async with _client() as cl:
        rc = (await _prepare(cl, ep, _key(), "vendor_changes.approve", ch)).json()
        rx = (await _prepare(cl, ep, _key(), "expenses.pay", ex)).json()
        rg = (await _prepare(cl, ep, _key(), "gl.post", None, {"account": "6000", "debit": 120.0})).json()
    assert (rc["entity_type"], rc["amount"], rc["effective"]) == ("vendor_change", None, "allow")
    assert (rx["entity_type"], rx["amount"]) == ("expense", 200.0)
    assert (rg["entity_type"], rg["entity_id"], rg["amount"], rg["effective"]) == ("gl_entry", None, None, "allow")
    assert blue["calls"][-1]["amount"] == 120.0  # blue sees the posted amount, as on the inline route


# ---------- one key, one gate call ----------


async def test_same_key_again_returns_the_stored_preparation(blue: dict[str, Any]) -> None:
    ep = await _episode("enforce")
    inv = await _invoice(ep)
    key = _key()
    async with _client() as cl:
        a = (await _prepare(cl, ep, key, "invoices.approve", inv)).json()
        b = (await _prepare(cl, ep, key, "invoices.approve", inv)).json()
        g = await cl.get(f"/api/preparations/{key}", headers=f.auth("green", episode=ep, day=1))
    assert a == b == g.json()
    assert len(blue["calls"]) == 1
    assert len(await _events(ep, "gate.verdict")) == 1


async def test_concurrent_same_key_prepares_ask_blue_once(blue: dict[str, Any]) -> None:
    ep = await _episode("enforce")
    inv = await _invoice(ep)
    key = _key()
    async with _client() as cl:
        rs = await asyncio.gather(*[_prepare(cl, ep, key, "invoices.approve", inv) for _ in range(5)])
    assert {r.status_code for r in rs} == {200}
    assert len({r.json()["preparation_id"] for r in rs}) == 1
    assert len(blue["calls"]) == 1


async def test_same_key_for_another_action_is_409_and_audited(blue: dict[str, Any]) -> None:
    ep = await _episode("enforce")
    inv = await _invoice(ep)
    other = await _invoice(ep)
    key = _key()
    async with _client() as cl:
        first = (await _prepare(cl, ep, key, "invoices.approve", inv)).json()
        r = await _prepare(cl, ep, key, "invoices.approve", other)
    assert r.status_code == 409
    assert r.json() == {"error": gate.IDEMPOTENCY_CONFLICT, "verdict_id": first["verdict_id"]}
    assert len(blue["calls"]) == 1
    assert await db.fetchval("SELECT http_status FROM audit_log WHERE episode_id=$1 AND tool_use_id=$2 ORDER BY id DESC LIMIT 1", ep, key) == 409


async def test_inline_route_after_prepare_reuses_the_verdict(blue: dict[str, Any]) -> None:
    ep = await _episode("enforce")
    inv = await _invoice(ep, status="approved")
    key = _key()
    async with _client() as cl:
        p = (await _prepare(cl, ep, key, "invoices.pay", inv)).json()
        r = await cl.post(f"/api/invoices/{inv}/pay", headers=_green(ep, key))
    assert r.status_code == 200, r.text
    assert len(blue["calls"]) == 1  # the gated route replayed the prepared verdict
    assert await db.fetchval("SELECT verdict_id FROM audit_log WHERE episode_id=$1 AND action='invoices.pay'", ep) == p["verdict_id"]


async def test_prepare_after_an_inline_verdict_reuses_it(blue: dict[str, Any]) -> None:
    ep = await _episode("enforce")
    inv = await _invoice(ep)
    key = _key()
    async with _client() as cl:
        assert (await cl.post(f"/api/invoices/{inv}/approve", headers=_green(ep, key))).status_code == 200
        await db.execute("UPDATE invoices SET status='pending' WHERE id=$1", inv)  # so the route's state check passes again
        p = (await _prepare(cl, ep, key, "invoices.approve", inv)).json()
    assert len(blue["calls"]) == 1 and p["effective"] == "allow"


# ---------- escalation ----------


async def test_escalation_holds_until_a_human_approves(blue: dict[str, Any]) -> None:
    blue["verdict"] = "escalate"
    ep = await _episode("enforce")
    inv = await _invoice(ep)
    key = _key()
    async with _client() as cl:
        held = asyncio.create_task(_prepare(cl, ep, key, "invoices.approve", inv))
        esc = None
        for _ in range(250):
            rows = (await cl.get("/api/escalations", params={"episode_id": ep}, headers=OP)).json()
            if rows:
                esc = rows[0]
                break
            await asyncio.sleep(0.02)
        assert esc is not None
        pending = (await cl.get(f"/api/preparations/{key}", headers=f.auth("green", episode=ep, day=1))).json()
        assert (pending["effective"], pending["decided_by"], pending["escalation_id"]) == ("pending", None, esc["id"])
        assert (await cl.post(f"/api/escalations/{esc['id']}/resolve", json={"decision": "approve", "by": "ad"}, headers=OP)).status_code == 200
        p = (await held).json()
        again = (await _prepare(cl, ep, key, "invoices.approve", inv)).json()
    assert (p["effective"], p["decided_by"], p["escalation_id"]) == ("allow", "human", esc["id"])
    assert again == p
    assert await db.fetchval("SELECT COUNT(*) FROM escalations WHERE episode_id=$1", ep) == 1
    (opened,) = await _events(ep, "escalation.opened")
    assert opened["preparation_id"] == p["preparation_id"] and opened["cause"] == "control"
    assert await db.fetchval("SELECT status FROM invoices WHERE id=$1", inv) == "pending"  # approved to run, not run


async def test_escalation_timeout_blocks_and_marks_the_entity(blue: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    blue["verdict"] = "escalate"
    monkeypatch.setattr(settings, "escalation_timeout_sec", 0.3)
    ep = await _episode("enforce")
    inv = await _invoice(ep)
    async with _client() as cl:
        p = (await _prepare(cl, ep, _key(), "invoices.approve", inv)).json()
    assert (p["effective"], p["decided_by"]) == ("block", "timeout")
    assert await db.fetchval("SELECT status FROM invoices WHERE id=$1", inv) == "blocked"


# ---------- blue unavailable ----------


@pytest.mark.parametrize(("mode", "effective", "decided_by"), [("shadow", "allow", "gate"), ("enforce", "block", "timeout")])
async def test_blue_down_is_gate_unavailable(mode: str, effective: str, decided_by: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "blue_url", "http://127.0.0.1:9")  # nothing listens: the real fallback
    monkeypatch.setattr(settings, "gate_timeout_sec", 0.5)
    monkeypatch.setattr(settings, "escalation_timeout_sec", 0.3)
    ep = await _episode(mode)
    inv = await _invoice(ep)
    async with _client() as cl:
        p = (await _prepare(cl, ep, _key(), "invoices.approve", inv)).json()
    assert (p["effective"], p["decided_by"], p["cause"]) == (effective, decided_by, "gate_unavailable")
    assert await db.fetchval("SELECT cause FROM verdicts WHERE id=$1", p["verdict_id"]) == "gate_unavailable"


# ---------- refusals ----------


async def test_route_state_checks_and_bad_bodies(blue: dict[str, Any]) -> None:
    ep = await _episode("enforce")
    paid = await _invoice(ep, status="paid")
    frozen_vendor = await f.vendor(ep, status="frozen")
    on_frozen = await f.invoice(ep, frozen_vendor, status="approved")
    async with _client() as cl:
        r1 = await _prepare(cl, ep, _key(), "invoices.approve", paid)
        r2 = await _prepare(cl, ep, _key(), "invoices.pay", on_frozen)
        r3 = await _prepare(cl, ep, _key(), "invoices.approve", "inv_missing")
        r4 = await _prepare(cl, ep, _key(), "invoices.approve", None)
        r5 = await cl.post("/api/preparations", json={"action": "invoices.burn", "entity_id": paid}, headers=_green(ep, _key()))
        r6 = await _prepare(cl, ep, _key(), "invoices.match", await _invoice(ep), {"po_id": "po_missing"})
        r7 = await _prepare(cl, ep, _key(), "invoices.reject", await _invoice(ep), {})
    assert (r1.status_code, r1.json()) == (409, {"error": "invalid_state", "detail": "invoice is paid"})
    assert (r2.status_code, r2.json()) == (409, {"error": "invalid_state", "detail": "vendor is frozen"})
    assert r3.status_code == 404 and r6.status_code == 404
    assert r4.status_code == 422 and r5.status_code == 422 and r7.status_code == 422
    assert blue["calls"] == []
    assert await db.fetchval("SELECT COUNT(*) FROM audit_log WHERE episode_id=$1 AND action LIKE 'prepare:%'", ep) == 7


async def test_only_green_may_prepare(blue: dict[str, Any]) -> None:
    ep = await _episode("enforce")
    inv = await _invoice(ep)
    async with _client() as cl:
        r = await _prepare(cl, ep, _key(), "invoices.approve", inv, agent="red")
        g = await cl.get(f"/api/preparations/{_key()}", headers=f.auth("green", episode=ep, day=1))
    assert r.status_code == 403
    assert g.status_code == 404


@pytest.mark.usefixtures("turn_guard")
async def test_outside_the_active_turn_is_409(blue: dict[str, Any]) -> None:
    ep = await _episode("enforce")
    inv = await _invoice(ep)
    async with _client() as cl:
        r = await _prepare(cl, ep, _key(), "invoices.approve", inv)
    assert (r.status_code, r.json()) == (409, {"error": "no active turn for this agent"})
    assert blue["calls"] == []


# ---------- restart and startup ----------


async def test_restart_sweep_blocks_pending_preparations(blue: dict[str, Any]) -> None:
    ep = await _episode("enforce")
    inv = await _invoice(ep)
    vd = await f.verdict(ep, "invoice", inv, verdict="escalate")
    prep = f.uid("prep")
    await db.execute(
        "INSERT INTO preparations (id, episode_id, idempotency_key, day, agent, controller_mode, action, entity_type, entity_id, amount, state_hash, "
        "verdict_id, effective, expires_at) VALUES ($1,$2,$3,1,'green','enforce','invoices.approve','invoice',$4,1000,'h',$5,'pending', now() + interval '2 minutes')",
        prep,
        ep,
        _key(),
        inv,
        vd,
    )
    assert await preparations.sweep_pending() >= 1
    row = await db.fetchrow("SELECT effective, decided_by FROM preparations WHERE id=$1", prep)
    assert (row["effective"], row["decided_by"]) == ("block", "timeout")
    assert await db.fetchval("SELECT status FROM invoices WHERE id=$1", inv) == "blocked"


def test_startup_refuses_a_hold_longer_than_a_preparation(monkeypatch: pytest.MonkeyPatch) -> None:
    gate.check_preparation_budget()  # defaults: 90 + 8 + 15 <= 120
    monkeypatch.setattr(settings, "escalation_timeout_sec", 100)
    with pytest.raises(RuntimeError, match="preparation lifetime"):
        gate.check_preparation_budget()


async def test_fingerprint_ignores_the_subject_status_but_not_the_bank_account() -> None:
    ep = await _episode("enforce")
    vid = await f.vendor(ep)
    inv = await f.invoice(ep, vid, status="approved")
    h0 = await preparations.fingerprint("invoices.pay", inv, {})
    await db.execute("UPDATE invoices SET status='matched' WHERE id=$1", inv)
    assert await preparations.fingerprint("invoices.pay", inv, {}) == h0
    await db.execute("UPDATE vendors SET bank_account='ACCT-NEW' WHERE id=$1", vid)
    assert await preparations.fingerprint("invoices.pay", inv, {}) != h0


async def test_mock_green_prepares_then_executes_under_the_same_key() -> None:
    from mock_agents import server as mock

    class Ledger:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []
            self.n = 0

        def new_tool_use_id(self) -> str:
            self.n += 1
            return f"k{self.n}"

        async def _write(self, method: str, path: str, body: dict, key: str) -> dict:
            self.calls.append(("prepare:" + body["action"], key))
            return {"effective": "block" if body["entity_id"] == "inv_bad" else "allow"}

        async def list_vendor_changes(self, status: str) -> list:
            return []

        async def list_purchase_orders(self, status: str) -> list:
            return []

        async def list_invoices(self, status: str) -> list:
            return [{"id": "inv_ok", "amount": 10}, {"id": "inv_bad", "amount": 10}] if status == "approved" else []

        async def list_expenses(self, status: str) -> list:
            return []

        async def pay_invoice(self, invoice_id: str, *, tool_use_id: str) -> dict:
            self.calls.append(("invoices.pay:" + invoice_id, tool_use_id))
            return {}

    class Em:
        def thinking(self, text: str) -> None:
            pass

    led = Ledger()
    summary = await mock.green_turn(None, led, Em())  # type: ignore[arg-type]
    assert led.calls == [("prepare:invoices.pay", "k1"), ("invoices.pay:inv_ok", "k1"), ("prepare:invoices.pay", "k2")]
    assert summary == "processed 1 items, 1 blocked/failed"


# ---------- holders that go away ----------


def _caller(ep: str, key: str) -> Caller:
    return Caller(agent="green", episode_id=ep, day=1, tool_use_id=key)


async def _prepare_direct(ep: str, key: str, inv: str) -> Any:
    return await gate.prepare(
        _caller(ep, key),
        action="invoices.approve",
        entity_type="invoice",
        entity_id=inv,
        amount=1000.0,
        verdict_amount=1000.0,
        args={},
        context={},
        state_hash="h",
        mark_blocked=preparations.block_marker("invoices.approve", inv, 1),
    )


async def _wait_open_escalation(ep: str) -> str:
    for _ in range(250):
        esc = await db.fetchval("SELECT id FROM escalations WHERE episode_id=$1 AND status='open'", ep)
        if esc:
            return esc
        await asyncio.sleep(0.02)
    raise AssertionError("no escalation opened")


async def test_cancelled_holder_closes_as_timeout_and_a_retry_opens_no_second_card(blue: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    blue["verdict"] = "escalate"
    monkeypatch.setattr(settings, "escalation_timeout_sec", 30)
    ep = await _episode("enforce")
    inv = await _invoice(ep)
    key = _key()
    held = asyncio.create_task(_prepare_direct(ep, key, inv))
    esc = await _wait_open_escalation(ep)
    held.cancel()
    with pytest.raises(asyncio.CancelledError):
        await held
    row = await db.fetchrow("SELECT effective, decided_by, escalation_id FROM preparations WHERE episode_id=$1 AND idempotency_key=$2", ep, key)
    assert (row["effective"], row["decided_by"], row["escalation_id"]) == ("block", "timeout", esc)
    assert await db.fetchval("SELECT status FROM escalations WHERE id=$1", esc) == "timeout"
    assert await db.fetchval("SELECT status FROM invoices WHERE id=$1", inv) == "blocked"
    async with _client() as cl:
        await db.execute("UPDATE invoices SET status='pending' WHERE id=$1", inv)  # so the route's state check lets the retry through
        p = (await _prepare(cl, ep, key, "invoices.approve", inv)).json()
    assert (p["effective"], p["decided_by"]) == ("block", "timeout")
    assert await db.fetchval("SELECT COUNT(*) FROM escalations WHERE episode_id=$1", ep) == 1
    assert len(blue["calls"]) == 1


async def test_retry_of_a_pending_row_without_a_live_holder_blocks_it(blue: dict[str, Any]) -> None:
    ep = await _episode("enforce")
    inv = await _invoice(ep)
    key = _key()
    vd = await f.verdict(ep, "invoice", inv, verdict="escalate")
    await db.execute("UPDATE verdicts SET idempotency_key=$2, action='invoices.approve', amount=1000 WHERE id=$1", vd, key)
    esc = f.uid("esc")
    await db.execute("INSERT INTO escalations (id, episode_id, verdict_id, expires_at) VALUES ($1,$2,$3, now() + interval '1 minute')", esc, ep, vd)
    await db.execute(
        "INSERT INTO preparations (id, episode_id, idempotency_key, day, agent, controller_mode, action, entity_type, entity_id, amount, state_hash, "
        "verdict_id, escalation_id, effective, expires_at) "
        "VALUES ($1,$2,$3,1,'green','enforce','invoices.approve','invoice',$4,1000,'h',$5,$6,'pending', now() + interval '2 minutes')",
        f.uid("prep"),
        ep,
        key,
        inv,
        vd,
        esc,
    )
    async with _client() as cl:
        p = (await _prepare(cl, ep, key, "invoices.approve", inv)).json()
    assert (p["effective"], p["decided_by"]) == ("block", "timeout")
    assert await db.fetchval("SELECT status FROM escalations WHERE id=$1", esc) == "timeout"
    assert await db.fetchval("SELECT COUNT(*) FROM escalations WHERE episode_id=$1", ep) == 1
    assert await db.fetchval("SELECT status FROM invoices WHERE id=$1", inv) == "blocked"
    assert blue["calls"] == []


async def test_an_approval_after_expiry_cannot_authorize(blue: dict[str, Any]) -> None:
    ep = await _episode("enforce")
    inv = await _invoice(ep)
    prep = f.uid("prep")
    await db.execute(
        "INSERT INTO preparations (id, episode_id, idempotency_key, day, agent, controller_mode, action, entity_type, entity_id, amount, state_hash, "
        "effective, expires_at) VALUES ($1,$2,$3,1,'green','enforce','invoices.approve','invoice',$4,1000,'h','pending', now() - interval '1 second')",
        prep,
        ep,
        _key(),
        inv,
    )
    await gate._record_decision({"id": prep}, "approve", preparations.block_marker("invoices.approve", inv, 1))
    row = await db.fetchrow("SELECT effective, decided_by FROM preparations WHERE id=$1", prep)
    assert (row["effective"], row["decided_by"]) == ("block", "timeout")
    assert await db.fetchval("SELECT status FROM invoices WHERE id=$1", inv) == "blocked"


async def test_expiry_is_created_at_plus_ttl(blue: dict[str, Any]) -> None:
    ep = await _episode("enforce")
    inv = await _invoice(ep)
    async with _client() as cl:
        p = (await _prepare(cl, ep, _key(), "invoices.approve", inv)).json()
    gap = await db.fetchval("SELECT EXTRACT(EPOCH FROM expires_at - created_at) FROM preparations WHERE id=$1", p["preparation_id"])
    assert float(gap) == 120.0


# ---------- smaller contract points ----------


async def test_off_mode_conflict_has_no_verdict_id(blue: dict[str, Any]) -> None:
    ep = await _episode("off")
    inv, other = await _invoice(ep), await _invoice(ep)
    key = _key()
    async with _client() as cl:
        await _prepare(cl, ep, key, "invoices.approve", inv)
        r = await _prepare(cl, ep, key, "invoices.approve", other)
    assert (r.status_code, r.json()) == (409, {"error": gate.IDEMPOTENCY_CONFLICT, "verdict_id": None})


async def test_non_object_and_non_json_bodies_are_audited_422(blue: dict[str, Any]) -> None:
    ep = await _episode("enforce")
    async with _client() as cl:
        r1 = await cl.post("/api/preparations", json=["invoices.approve"], headers=_green(ep, _key()))
        r2 = await cl.post("/api/preparations", content=b"not json", headers={**_green(ep, _key()), "content-type": "application/json"})
    assert r1.status_code == 422 and r2.status_code == 422
    assert await db.fetchval("SELECT COUNT(*) FROM audit_log WHERE episode_id=$1 AND action='prepare:unknown' AND http_status=422", ep) == 2


async def test_inline_escalation_carries_cause(blue: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    blue["verdict"] = "escalate"
    monkeypatch.setattr(settings, "escalation_timeout_sec", 0.3)
    ep = await _episode("enforce")
    inv = await _invoice(ep)
    async with _client() as cl:
        r = await cl.post(f"/api/invoices/{inv}/approve", headers=_green(ep, _key()))
    assert r.status_code == 403
    (opened,) = await _events(ep, "escalation.opened")
    assert opened["cause"] == "control" and "preparation_id" not in opened
