"""DB: read routes hide provenance from agents, show it to the operator."""

from __future__ import annotations

import httpx
import pytest

from app.main import app
from tests import factories as f

pytestmark = pytest.mark.usefixtures("pg")


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bf")  # lifespan not run; `pg` owns the pool


async def test_vendors_hide_origin_from_agents(episode: str) -> None:
    vid = await f.vendor(episode, origin="red")
    async with _client() as c:
        agent = await c.get("/api/vendors", headers=f.auth("green", episode=episode, day=1))
        operator = await c.get("/api/vendors", params={"episode_id": episode}, headers=f.auth())
    assert agent.status_code == 200 and operator.status_code == 200
    [a] = agent.json()
    [o] = operator.json()
    assert a["id"] == o["id"] == vid
    assert "origin" not in a
    assert o["origin"] == "red"


async def test_invoice_hides_attack_id_and_payments_hide_origin_of_source(episode: str) -> None:
    vid = await f.vendor(episode)
    atk = await f.attack(episode, scheme_id="threshold_split")
    iid = await f.invoice(episode, vid, origin="red", attack_id=atk, status="paid")
    await f.payment(episode, iid, amount=1000, to_account="ACCT-OLD", day=1, origin_of_source="red")
    async with _client() as c:
        inv_agent = (await c.get(f"/api/invoices/{iid}", headers=f.auth("blue", episode=episode, day=1))).json()
        inv_op = (await c.get(f"/api/invoices/{iid}", headers=f.auth())).json()
        pay_agent = (await c.get("/api/payments", headers=f.auth("blue", episode=episode, day=1))).json()
        pay_op = (await c.get("/api/payments", params={"episode_id": episode}, headers=f.auth())).json()
    assert not ({"origin", "attack_id"} & set(inv_agent))
    assert inv_op["origin"] == "red" and inv_op["attack_id"] == atk
    assert "origin_of_source" not in pay_agent[0]
    assert pay_op[0]["origin_of_source"] == "red"


async def test_red_vendor_creation_leaks_no_provenance_via_created_by(episode: str) -> None:
    # created_by='red' used to sit in plain sight for every agent (invariant 4)
    body = {"name": "Acme Office Supply LLC", "ein": "47-1234567", "bank_account": "9988776655", "bank_routing": "021000021", "category": "office"}
    async with _client() as c:
        made = await c.post("/api/vendors", json=body, headers={**f.auth("red", episode=episode, day=1), "X-Tool-Use-Id": "tu_v1"})
        assert made.status_code == 201
        vid = made.json()["id"]
        seen_by = {a: (await c.get(f"/api/vendors/{vid}", headers=f.auth(a, episode=episode, day=1))).json() for a in ("red", "green", "blue")}
        listed = (await c.get("/api/vendors", headers=f.auth("blue", episode=episode, day=1))).json()
        operator = (await c.get(f"/api/vendors/{vid}", headers=f.auth())).json()
    for row in [made.json(), *seen_by.values(), *(v for v in listed if v["id"] == vid)]:
        assert not ({"origin", "created_by"} & set(row))
    assert operator["origin"] == "red"
    assert operator["created_by"] == "procurement"  # same value as legit mid-episode onboarding


_OUTCOME = {"outcome": "extracted", "amount_extracted": 4380.0, "detected_day": 3, "resolved_day": 4}
_DECLARED = {"id", "scheme_id", "display_name", "story", "params", "target_amount", "day_launched", "notes", "created_at", "revealed_day"}


async def _red_and_operator_attacks(episode: str) -> tuple[list[dict], list[dict]]:
    async with _client() as c:
        red = await c.get("/api/attacks", headers=f.auth("red", episode=episode, day=5))
        op = await c.get("/api/attacks", params={"episode_id": episode}, headers=f.auth())
    assert red.status_code == 200 and op.status_code == 200
    return red.json(), op.json()


async def test_red_attacks_withhold_outcome_until_revealed(episode: str) -> None:
    # outside a lineage debrief red never learns how an attack went (invariant 4)
    aid = await f.attack(episode, scheme_id="ghost_vendor", **_OUTCOME)
    [red], [op] = await _red_and_operator_attacks(episode)
    assert red["id"] == aid and red["revealed_day"] is None
    assert not (set(_OUTCOME) & set(red))
    assert _DECLARED <= set(red)
    assert {k: op[k] for k in _OUTCOME} == _OUTCOME  # operator: full row


async def test_red_attacks_show_outcome_once_revealed(episode: str) -> None:
    aid = await f.attack(episode, scheme_id="ghost_vendor", revealed_day=5, **_OUTCOME)
    [red], [op] = await _red_and_operator_attacks(episode)
    assert red["id"] == aid and red["revealed_day"] == 5
    assert {k: red[k] for k in _OUTCOME} == _OUTCOME
    assert red == op  # attacks carry no provenance columns: a revealed row is the operator's row
