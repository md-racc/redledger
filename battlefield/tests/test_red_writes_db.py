"""DB: red's write surface links rows to the right attack and never shows attack_id to agents."""

from __future__ import annotations

import uuid

import httpx
import pytest

from app import db
from app.main import app
from app.scoring import score
from tests import factories as f

pytestmark = pytest.mark.usefixtures("pg")


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bf")  # lifespan not run; `pg` owns the pool


def _red(episode: str, day: int = 1) -> dict[str, str]:
    return f.auth("red", episode=episode, day=day, tool_use_id=f"tu_{uuid.uuid4().hex}")


async def test_current_attack_is_the_latest_created_not_the_largest_id(episode: str) -> None:
    tag = uuid.uuid4().hex[:8]
    older = await f.attack(episode, day=1, id=f"atk_z{tag}", created_at=await db.fetchval("SELECT now() - interval '1 minute'"))
    newer = await f.attack(episode, day=1, id=f"atk_a{tag}")  # sorts first by id, created last
    await f.attack(episode, day=0, id=f"atk_0{tag}")  # yesterday's attack never links today's rows
    vid = await f.vendor(episode)
    emp = await f.employee(episode)
    async with _client() as c:
        inv = await c.post("/api/invoices", json={"vendor_id": vid, "amount": 100, "invoice_number": "X-1"}, headers=_red(episode))
        exp = await c.post("/api/expenses", json={"employee_id": emp, "amount": 50, "category": "travel"}, headers=_red(episode))
        ch = await c.post("/api/vendor_changes", json={"vendor_id": vid, "field": "bank_account", "new_value": "ACCT-RED"}, headers=_red(episode))
    assert inv.status_code == exp.status_code == ch.status_code == 201
    assert await db.fetchval("SELECT attack_id FROM invoices WHERE id=$1", inv.json()["id"]) == newer
    assert await db.fetchval("SELECT attack_id FROM expenses WHERE id=$1", exp.json()["id"]) == newer
    assert await db.fetchval("SELECT attack_id FROM vendor_changes WHERE id=$1", ch.json()["id"]) == newer
    assert older != newer


async def test_vendor_change_without_attack_today_is_unlinked(episode: str) -> None:
    await f.attack(episode, day=0)
    vid = await f.vendor(episode)
    async with _client() as c:
        r = await c.post("/api/vendor_changes", json={"vendor_id": vid, "field": "address", "new_value": "1 Elm St"}, headers=_red(episode, day=1))
    assert r.status_code == 201
    assert await db.fetchval("SELECT attack_id FROM vendor_changes WHERE id=$1", r.json()["id"]) is None


async def test_red_vendor_change_links_attack_and_hides_it(episode: str) -> None:
    sim_v = await f.vendor(episode)
    async with _client() as c:
        # ghost_vendor then bank_swap in one red turn, as two schemes would run them
        ghost = (await c.post("/api/attacks", json=_atk("ghost_vendor", 4380), headers=_red(episode))).json()["id"]
        red_v = (await c.post("/api/vendors", json={"name": "Acme", "bank_account": "998877", "bank_routing": "021000021"}, headers=_red(episode))).json()["id"]
        ghost_inv = (await c.post("/api/invoices", json={"vendor_id": red_v, "amount": 4380, "invoice_number": "AOS-1"}, headers=_red(episode))).json()["id"]
        swap = (await c.post("/api/attacks", json=_atk("bank_swap", 2500), headers=_red(episode))).json()["id"]
        created = await c.post("/api/vendor_changes", json={"vendor_id": sim_v, "field": "bank_account", "new_value": "ACCT-RED"}, headers=_red(episode))
        assert created.status_code == 201
        ch = created.json()
        lists = {who: (await c.get("/api/vendor_changes", headers=f.auth(who, episode=episode, day=1))).json() for who in ("red", "green", "blue")}
        operator = (await c.get("/api/vendor_changes", params={"episode_id": episode}, headers=f.auth())).json()

    assert not ({"attack_id", "origin"} & set(ch))
    for who, rows in lists.items():
        assert [r["id"] for r in rows] == [ch["id"]], who
        assert not ({"attack_id", "origin"} & set(rows[0])), who
    assert operator[0]["attack_id"] == swap and operator[0]["origin"] == "red"
    assert await db.fetchval("SELECT attack_id FROM invoices WHERE id=$1", ghost_inv) == ghost

    # green approves the swap and pays a sim invoice into it; blue rejects the ghost invoice
    await db.execute("UPDATE vendor_changes SET status='approved', resolved_day=1 WHERE id=$1", ch["id"])
    await db.execute("UPDATE vendors SET bank_account='ACCT-RED' WHERE id=$1", sim_v)
    await db.execute("UPDATE invoices SET status='rejected', status_day=1 WHERE id=$1", ghost_inv)
    paid = await f.invoice(episode, sim_v, amount=900, status="paid", day=2)
    await f.payment(episode, paid, amount=900, to_account="ACCT-RED", day=2)
    await score.resolve_attacks(episode, 3)
    outcomes = {r["id"]: (r["outcome"], float(r["amount_extracted"])) for r in await db.fetch("SELECT * FROM attacks WHERE episode_id=$1", episode)}
    assert outcomes == {ghost: ("blocked", 0.0), swap: ("extracted", 900.0)}


def _atk(scheme_id: str, target: float) -> dict:
    return {"scheme_id": scheme_id, "display_name": scheme_id, "story": "test", "target_amount": target}


async def test_attack_listings_order_same_day_by_created_at(episode: str) -> None:
    tag = uuid.uuid4().hex[:8]
    ago = "SELECT now() - make_interval(mins => $1)"
    first = await f.attack(episode, day=1, scheme_id="bank_swap", id=f"atk_z{tag}", created_at=await db.fetchval(ago, 2))
    second = await f.attack(episode, day=1, scheme_id="threshold_split", id=f"atk_a{tag}", created_at=await db.fetchval(ago, 1))
    day0 = await f.attack(episode, day=0, scheme_id="ghost_vendor", id=f"atk_m{tag}")  # created last, launched first
    expected = [day0, first, second]  # day_launched, then created_at; id order would put atk_a before atk_z
    schemes = ["ghost_vendor", "bank_swap", "threshold_split"]
    async with _client() as c:
        red = (await c.get("/api/attacks", headers=f.auth("red", episode=episode, day=1))).json()
        op = (await c.get("/api/attacks/all", params={"episode_id": episode}, headers=f.auth())).json()
        fe = (await c.get(f"/api/fe/episodes/{episode}/attacks", headers=f.auth())).json()
        board = (await c.get(f"/api/fe/episodes/{episode}/attacks/leaderboard", headers=f.auth())).json()
        cmp = (await c.get("/api/fe/compare", params={"a": episode, "b": episode}, headers=f.auth())).json()
    assert [a["id"] for a in red] == [a["id"] for a in op] == [a["id"] for a in fe] == expected
    assert [r["scheme_id"] for r in board] == schemes  # all tied at $0 extracted: launch order breaks the tie
    assert [a["scheme_id"] for a in cmp["a"]["attacks"]] == [a["scheme_id"] for a in cmp["b"]["attacks"]] == schemes


async def test_red_amounts_must_be_positive_finite_and_due_days_non_negative(episode: str) -> None:
    """A negative invoice would add cash when paid and score negative dollars extracted; a NaN one
    persisted without its audit row and broke every later invoice read. Both are 422 now, nothing written."""
    vid = await f.vendor(episode)
    emp = await f.employee(episode)
    inv = {"vendor_id": vid, "amount": 100, "invoice_number": "X-1"}
    async with _client() as c:
        bad = [
            await c.post("/api/invoices", json={**inv, "amount": -25_000}, headers=_red(episode)),
            await c.post("/api/invoices", json={**inv, "amount": 0}, headers=_red(episode)),
            await c.post("/api/invoices", json={**inv, "due_in_days": -40}, headers=_red(episode)),
            await c.post(
                "/api/invoices",
                content=f'{{"vendor_id": "{vid}", "amount": NaN, "invoice_number": "X-2"}}',
                headers={**_red(episode), "Content-Type": "application/json"},
            ),
            await c.post("/api/expenses", json={"employee_id": emp, "amount": -50, "category": "travel"}, headers=_red(episode)),
            await c.post("/api/attacks", json={**_atk("ghost_vendor", 100), "target_amount": -1}, headers=_red(episode)),
        ]
        ok = await c.post("/api/invoices", json=inv, headers=_red(episode))
        listed = await c.get("/api/invoices", headers=_red(episode))
    assert [r.status_code for r in bad] == [422] * len(bad)
    assert ok.status_code == 201 and listed.status_code == 200
    assert await db.fetchval("SELECT COUNT(*) FROM invoices WHERE episode_id=$1", episode) == 1
    assert await db.fetchval("SELECT COUNT(*) FROM expenses WHERE episode_id=$1", episode) == 0
