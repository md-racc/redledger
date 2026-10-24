"""DB: a gated green route consumes the preparation made under its X-Tool-Use-Id (step 2b;
contracts/ledger-api.yaml /preparations, design §2.5). No second blue call, no new escalation; refused
with 409 PreparationRejected when consumed / pending / stale / expired (per D4), 403 for a stored
enforced block. Blue is a stand-in (`gate._ask_blue` patched).
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
import pytest

from app import db
from app.auth import Caller
from app.gate import gatekeeper as gate
from app.main import app
from tests import factories as f

pytestmark = pytest.mark.usefixtures("pg")


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bf", timeout=30)


def _key() -> str:
    return f"tu_{uuid.uuid4().hex}"


def _green(ep: str, key: str, day: int = 1) -> dict[str, str]:
    return f.auth("green", episode=ep, day=day, tool_use_id=key)


async def _episode(mode: str) -> str:
    ep = f.uid("ep")
    await db.execute("INSERT INTO episodes (id, seed, controller_mode) VALUES ($1, 42, $2)", ep, mode)
    return ep


@pytest.fixture
def blue(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"verdict": "allow", "calls": []}

    async def ask(c: Caller, mode: str, action: str, et: str | None, eid: str | None, amount: float | None, args: dict, context: dict, **kw: Any):
        state["calls"].append({"key": c.tool_use_id, "action": action, "entity_id": eid})
        return state["verdict"], f"stand-in says {state['verdict']}", 0.9, ["near_threshold"]

    monkeypatch.setattr(gate, "_ask_blue", ask)
    return state


async def _prepare(cl: httpx.AsyncClient, ep: str, key: str, action: str, entity_id: str | None, args: dict | None = None, day: int = 1) -> dict:
    body: dict[str, Any] = {"action": action, "args": args or {}}
    if entity_id is not None:
        body["entity_id"] = entity_id
    r = await cl.post("/api/preparations", json=body, headers=_green(ep, key, day))
    assert r.status_code == 200, r.text
    return r.json()


async def _events(ep: str, type_: str) -> list[dict[str, Any]]:
    return [dict(r["payload"]) for r in await db.fetch("SELECT payload FROM events WHERE episode_id=$1 AND type=$2 ORDER BY id", ep, type_)]


async def _last_audit(ep: str, key: str) -> Any:
    return await db.fetchrow(
        "SELECT action, http_status, result, verdict_id FROM audit_log WHERE episode_id=$1 AND tool_use_id=$2 ORDER BY id DESC LIMIT 1", ep, key
    )


async def _payments(ep: str) -> int:
    return int(await db.fetchval("SELECT COUNT(*) FROM payments WHERE episode_id=$1", ep))


async def _approved_invoice(ep: str) -> tuple[str, str]:
    vid = await f.vendor(ep)
    return await f.invoice(ep, vid, status="approved"), vid


# ---------- the hit ----------


async def test_prepared_pay_consumes_without_a_second_blue_call(blue: dict[str, Any]) -> None:
    ep = await _episode("enforce")
    inv, _ = await _approved_invoice(ep)
    key = _key()
    async with _client() as cl:
        p = await _prepare(cl, ep, key, "invoices.pay", inv)
        r = await cl.post(f"/api/invoices/{inv}/pay", headers=_green(ep, key))
    assert r.status_code == 200, r.text
    assert len(blue["calls"]) == 1
    assert await _payments(ep) == 1
    row = await db.fetchrow("SELECT consumed_at, consumed_status FROM preparations WHERE id=$1", p["preparation_id"])
    assert row["consumed_at"] is not None and row["consumed_status"] == 200
    a = await _last_audit(ep, key)
    assert (a["action"], a["http_status"], a["verdict_id"]) == ("invoices.pay", 200, p["verdict_id"])
    assert dict(a["result"])["preparation_id"] == p["preparation_id"] and "stale" not in dict(a["result"])
    (m,) = await _events(ep, "ledger.mutation")
    assert (m["preparation_id"], m["verdict_id"], m["action"]) == (p["preparation_id"], p["verdict_id"], "invoices.pay")
    assert len(await _events(ep, "gate.verdict")) == 1


async def test_off_mode_preparation_is_consumed(blue: dict[str, Any]) -> None:
    ep = await _episode("off")
    inv, _ = await _approved_invoice(ep)
    key = _key()
    async with _client() as cl:
        p = await _prepare(cl, ep, key, "invoices.pay", inv)
        r = await cl.post(f"/api/invoices/{inv}/pay", headers=_green(ep, key))
    assert r.status_code == 200 and blue["calls"] == []
    (m,) = await _events(ep, "ledger.mutation")
    assert m["preparation_id"] == p["preparation_id"] and m["verdict_id"] is None


async def test_prepared_match_and_vendor_change_execute(blue: dict[str, Any]) -> None:
    # match: the CAS rewrites invoices.po_id, so the fingerprint is recomputed before it;
    # vendor change: the approved field is written after the consume, inside the same transaction
    ep = await _episode("enforce")
    vid = await f.vendor(ep)
    inv = await f.invoice(ep, vid)
    po = f.uid("po")
    await db.execute("INSERT INTO purchase_orders (id, episode_id, vendor_id, amount, created_day) VALUES ($1,$2,$3,1000,0)", po, ep, vid)
    ch = await f.change(ep, vid, new_value="ACCT-NEW")
    k1, k2 = _key(), _key()
    async with _client() as cl:
        await _prepare(cl, ep, k1, "invoices.match", inv, {"po_id": po})
        r1 = await cl.post(f"/api/invoices/{inv}/match", json={"po_id": po}, headers=_green(ep, k1))
        await _prepare(cl, ep, k2, "vendor_changes.approve", ch)
        r2 = await cl.post(f"/api/vendor_changes/{ch}/approve", headers=_green(ep, k2))
    assert (r1.status_code, r2.status_code) == (200, 200), (r1.text, r2.text)
    assert await db.fetchval("SELECT po_id FROM invoices WHERE id=$1", inv) == po
    assert await db.fetchval("SELECT bank_account FROM vendors WHERE id=$1", vid) == "ACCT-NEW"
    assert len(blue["calls"]) == 2


# ---------- refusals ----------


async def test_consumed_retry_is_409_with_the_consumed_status(blue: dict[str, Any]) -> None:
    ep = await _episode("enforce")
    inv, _ = await _approved_invoice(ep)
    key = _key()
    async with _client() as cl:
        p = await _prepare(cl, ep, key, "invoices.pay", inv)
        assert (await cl.post(f"/api/invoices/{inv}/pay", headers=_green(ep, key))).status_code == 200
        r = await cl.post(f"/api/invoices/{inv}/pay", headers=_green(ep, key))
    assert r.status_code == 409
    assert r.json() == {"error": "preparation_consumed", "preparation_id": p["preparation_id"], "consumed_status": 200}
    assert await _payments(ep) == 1 and len(blue["calls"]) == 1
    assert (await _last_audit(ep, key))["http_status"] == 409


async def test_pending_preparation_is_409_and_never_opens_an_escalation(blue: dict[str, Any]) -> None:
    ep = await _episode("enforce")
    inv, _ = await _approved_invoice(ep)
    key = _key()
    async with _client() as cl:
        p = await _prepare(cl, ep, key, "invoices.pay", inv)
        await db.execute("UPDATE preparations SET effective='pending', decided_by=NULL WHERE id=$1", p["preparation_id"])
        r = await cl.post(f"/api/invoices/{inv}/pay", headers=_green(ep, key))
    assert r.status_code == 409 and r.json() == {"error": "preparation_pending", "preparation_id": p["preparation_id"]}
    assert await db.fetchval("SELECT COUNT(*) FROM escalations WHERE episode_id=$1", ep) == 0
    assert await _payments(ep) == 0 and len(blue["calls"]) == 1


async def test_mode_change_is_stale_in_every_mode(blue: dict[str, Any]) -> None:
    ep = await _episode("enforce")
    inv, _ = await _approved_invoice(ep)
    key = _key()
    async with _client() as cl:
        p = await _prepare(cl, ep, key, "invoices.pay", inv)
        await db.execute("UPDATE episodes SET controller_mode='shadow' WHERE id=$1", ep)
        r = await cl.post(f"/api/invoices/{inv}/pay", headers=_green(ep, key))
    assert r.status_code == 409
    assert r.json() == {"error": "preparation_stale", "preparation_id": p["preparation_id"], "detail": "mode changed"}
    assert await _payments(ep) == 0


async def test_day_change_is_stale(blue: dict[str, Any]) -> None:
    ep = await _episode("shadow")  # refused even in shadow (D4)
    inv, _ = await _approved_invoice(ep)
    key = _key()
    async with _client() as cl:
        await _prepare(cl, ep, key, "invoices.pay", inv, day=1)
        r = await cl.post(f"/api/invoices/{inv}/pay", headers=_green(ep, key, day=2))
    assert r.status_code == 409 and r.json()["detail"] == "day changed"
    assert await _payments(ep) == 0


async def test_expiry_refuses_in_enforce_and_is_audited_in_shadow(blue: dict[str, Any]) -> None:
    for mode, want in (("enforce", 409), ("shadow", 200)):
        ep = await _episode(mode)
        inv, _ = await _approved_invoice(ep)
        key = _key()
        async with _client() as cl:
            p = await _prepare(cl, ep, key, "invoices.pay", inv)
            await db.execute("UPDATE preparations SET expires_at=now() - interval '1 second' WHERE id=$1", p["preparation_id"])
            r = await cl.post(f"/api/invoices/{inv}/pay", headers=_green(ep, key))
        assert r.status_code == want, (mode, r.text)
        if mode == "enforce":
            assert r.json()["error"] == "preparation_expired" and await _payments(ep) == 0
        else:
            res = dict((await _last_audit(ep, key))["result"])
            assert res["stale"] is True and res["stale_detail"] == "expired" and await _payments(ep) == 1


async def test_fingerprint_drift_refuses_in_enforce_rolls_back_and_is_audited_in_shadow(blue: dict[str, Any]) -> None:
    for mode in ("enforce", "shadow"):
        ep = await _episode(mode)
        inv, vid = await _approved_invoice(ep)
        key = _key()
        async with _client() as cl:
            p = await _prepare(cl, ep, key, "invoices.pay", inv)
            await db.execute("UPDATE vendors SET bank_account='ACCT-SWAPPED' WHERE id=$1", vid)  # a bank swap lands in between
            r = await cl.post(f"/api/invoices/{inv}/pay", headers=_green(ep, key))
        row = await db.fetchrow("SELECT consumed_at FROM preparations WHERE id=$1", p["preparation_id"])
        if mode == "enforce":
            assert r.status_code == 409 and r.json() == {"error": "preparation_stale", "preparation_id": p["preparation_id"], "detail": "state changed"}
            assert await _payments(ep) == 0 and row["consumed_at"] is None  # the transaction rolled back
            assert await db.fetchval("SELECT status FROM invoices WHERE id=$1", inv) == "approved"
        else:
            assert r.status_code == 200, r.text
            assert dict((await _last_audit(ep, key))["result"])["stale_detail"] == "state changed" and row["consumed_at"] is not None


async def test_binding_mismatch_is_409_in_every_mode(blue: dict[str, Any]) -> None:
    for mode in ("off", "shadow", "enforce"):
        ep = await _episode(mode)
        vid = await f.vendor(ep)
        a, b = await f.invoice(ep, vid), await f.invoice(ep, vid)
        key = _key()
        async with _client() as cl:
            p = await _prepare(cl, ep, key, "invoices.approve", a)
            r = await cl.post(f"/api/invoices/{b}/approve", headers=_green(ep, key))
        assert r.status_code == 409, mode
        assert r.json() == {"error": gate.IDEMPOTENCY_CONFLICT, "verdict_id": p["verdict_id"]}
        assert await db.fetchval("SELECT status FROM invoices WHERE id=$1", b) == "pending"


async def test_stored_enforced_block_is_403_without_asking_blue(blue: dict[str, Any]) -> None:
    blue["verdict"] = "block"
    ep = await _episode("enforce")
    inv, _ = await _approved_invoice(ep)
    key = _key()
    async with _client() as cl:
        p = await _prepare(cl, ep, key, "invoices.pay", inv)
        r = await cl.post(f"/api/invoices/{inv}/pay", headers=_green(ep, key))
    assert r.status_code == 403
    body = r.json()
    assert (body["verdict"], body["verdict_id"], body["preparation_id"], body["decided_by"]) == ("block", p["verdict_id"], p["preparation_id"], "gate")
    assert len(blue["calls"]) == 1 and await _payments(ep) == 0
    assert await db.fetchval("SELECT COUNT(*) FROM escalations WHERE episode_id=$1", ep) == 0


# ---------- GL, concurrency, match binding ----------


async def test_gl_audit_replay_takes_precedence_over_consumption(blue: dict[str, Any]) -> None:
    ep = await _episode("enforce")
    key = _key()
    entry = {"account": "6000", "debit": 120.0}
    async with _client() as cl:
        p = await _prepare(cl, ep, key, "gl.post", None, entry)
        r1 = await cl.post("/api/gl/entries", json=entry, headers=_green(ep, key))
        r2 = await cl.post("/api/gl/entries", json=entry, headers=_green(ep, key))
    assert (r1.status_code, r2.status_code) == (201, 201), (r1.text, r2.text)
    assert r1.json()["id"] == r2.json()["id"]
    assert await db.fetchval("SELECT COUNT(*) FROM gl_entries WHERE episode_id=$1", ep) == 1
    assert await db.fetchval("SELECT consumed_status FROM preparations WHERE id=$1", p["preparation_id"]) == 201
    assert len(blue["calls"]) == 1 and len(await _events(ep, "ledger.mutation")) == 1


async def test_concurrent_identical_executions_pay_once(blue: dict[str, Any]) -> None:
    ep = await _episode("enforce")
    inv, _ = await _approved_invoice(ep)
    key = _key()
    async with _client() as cl:
        await _prepare(cl, ep, key, "invoices.pay", inv)
        rs = await asyncio.gather(*[cl.post(f"/api/invoices/{inv}/pay", headers=_green(ep, key)) for _ in range(5)])
    assert sorted(r.status_code for r in rs) == [200, 409, 409, 409, 409]
    assert await _payments(ep) == 1 and len(blue["calls"]) == 1


async def test_match_binding_covers_the_po_on_both_paths(blue: dict[str, Any]) -> None:
    ep = await _episode("enforce")
    vid = await f.vendor(ep)
    po_a, po_b = f.uid("po"), f.uid("po")
    for po in (po_a, po_b):
        await db.execute("INSERT INTO purchase_orders (id, episode_id, vendor_id, amount, created_day) VALUES ($1,$2,$3,1000,0)", po, ep, vid)
    prepared, inline = await f.invoice(ep, vid), await f.invoice(ep, vid)
    k1, k2 = _key(), _key()
    # an inline verdict for PO A under k2 (as if the route had judged it and the call was lost)
    await db.execute(
        "INSERT INTO verdicts (id, episode_id, idempotency_key, day, agent, action, entity_type, entity_id, amount, args, verdict, reason, rules_fired, enforced) "
        "VALUES ($1,$2,$3,1,'green','invoices.match','invoice',$4,1000,$5,'allow','ok','[]'::jsonb,true)",
        f.uid("vd"),
        ep,
        k2,
        inline,
        {"po_id": po_a},
    )
    async with _client() as cl:
        await _prepare(cl, ep, k1, "invoices.match", prepared, {"po_id": po_a})
        r1 = await cl.post(f"/api/invoices/{prepared}/match", json={"po_id": po_b}, headers=_green(ep, k1))
        r2 = await cl.post(f"/api/invoices/{inline}/match", json={"po_id": po_b}, headers=_green(ep, k2))
    assert (r1.status_code, r2.status_code) == (409, 409), (r1.text, r2.text)
    assert r1.json()["error"] == r2.json()["error"] == gate.IDEMPOTENCY_CONFLICT
    assert await db.fetchval("SELECT COUNT(*) FROM invoices WHERE episode_id=$1 AND status='matched'", ep) == 0
