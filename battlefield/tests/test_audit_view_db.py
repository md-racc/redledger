"""DB: agents reading /audit_log never see red's rows (provenance, AGENTS.md §3.4); the operator does."""

from __future__ import annotations

import json
import uuid

import httpx
import pytest

from app import db
from app.main import app
from tests import factories as f

pytestmark = pytest.mark.usefixtures("pg")


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bf")  # lifespan not run; `pg` owns the pool


def _as(agent: str, episode: str, day: int = 1) -> dict[str, str]:
    return f.auth(agent, episode=episode, day=day, tool_use_id=f"tu_{uuid.uuid4().hex}")


async def _audit_row(episode: str, agent: str, action: str, *, day: int = 1, result: dict | None = None) -> None:
    """Direct insert, for agents whose real routes need a live gate (green)."""
    await db.execute(
        "INSERT INTO audit_log (episode_id, day, agent, action, args, result, http_status) VALUES ($1,$2,$3,$4,$5,$6,200)",
        episode,
        day,
        agent,
        action,
        {},
        result or {},
    )


async def _populate(episode: str) -> dict[str, str]:
    """Red declares an attack, creates a vendor and invoice (real routes); blue raises a flag; green approves."""
    sim_v = await f.vendor(episode)
    sim_inv = await f.invoice(episode, sim_v)
    async with _client() as c:
        atk = await c.post(
            "/api/attacks",
            json={"scheme_id": "ghost_vendor", "display_name": "Ghost vendor", "story": "SECRET-STORY", "target_amount": 4380},
            headers=_as("red", episode),
        )
        red_v = await c.post("/api/vendors", json={"name": "Acme", "bank_account": "998877", "bank_routing": "021000021"}, headers=_as("red", episode))
        red_inv = await c.post("/api/invoices", json={"vendor_id": red_v.json()["id"], "amount": 4380, "invoice_number": "AOS-1"}, headers=_as("red", episode))
        assert atk.status_code == red_v.status_code == red_inv.status_code == 201
        await _audit_row(episode, "green", "invoices.approve", result={"ok": True})
        flag = await c.post(
            "/api/flags", json={"entity_type": "invoice", "entity_id": sim_inv, "severity": "low", "reason": "dup?"}, headers=_as("blue", episode)
        )
        assert flag.status_code == 201
        # newest row is red's, so an unfiltered LIMIT 1 would hand an agent a red row
        await c.post("/api/invoices", json={"vendor_id": sim_v, "amount": 99, "invoice_number": "AOS-2"}, headers=_as("red", episode, day=2))
    return {"red_vendor": red_v.json()["id"], "red_invoice": red_inv.json()["id"], "attack": atk.json()["id"]}


async def test_agent_sees_only_green_and_blue_rows(episode: str) -> None:
    ids = await _populate(episode)
    async with _client() as c:
        r = await c.get("/api/audit_log", headers=_as("blue", episode))
    assert r.status_code == 200
    rows = r.json()
    assert {row["agent"] for row in rows} == {"green", "blue"}
    assert [row["action"] for row in rows] == ["flags.raise", "invoices.approve"]  # id DESC
    blob = json.dumps(rows)
    for leak in (*ids.values(), "SECRET-STORY", "attacks.declare", '"red"'):
        assert leak not in blob


async def test_agent_filtering_for_red_gets_empty_list_not_403(episode: str) -> None:
    await _populate(episode)
    async with _client() as c:
        r = await c.get("/api/audit_log", params={"agent": "red"}, headers=_as("blue", episode))
        r_day2 = await c.get("/api/audit_log", params={"day": 2}, headers=_as("blue", episode))
    assert r.status_code == 200 and r.json() == []
    assert r_day2.status_code == 200 and r_day2.json() == []  # day 2 holds only a red row


async def test_limit_applies_after_the_filter(episode: str) -> None:
    await _populate(episode)
    async with _client() as c:
        r = await c.get("/api/audit_log", params={"limit": 1}, headers=_as("blue", episode))
    assert [row["action"] for row in r.json()] == ["flags.raise"]


async def test_attacks_actions_hidden_from_agents_whoever_wrote_them(episode: str) -> None:
    await _audit_row(episode, "green", "attacks.declare")  # can't happen via routes; backstop
    await _audit_row(episode, "blue", "vendors.freeze")
    async with _client() as c:
        rows = (await c.get("/api/audit_log", headers=_as("blue", episode))).json()
    assert [row["action"] for row in rows] == ["vendors.freeze"]


async def test_operator_sees_every_row_including_red(episode: str) -> None:
    ids = await _populate(episode)
    async with _client() as c:
        r = await c.get("/api/audit_log", params={"episode_id": episode}, headers=f.auth())
        r_red = await c.get("/api/audit_log", params={"episode_id": episode, "agent": "red"}, headers=f.auth())
    assert r.status_code == 200
    rows = r.json()
    assert [row["agent"] for row in rows].count("red") == 4
    assert {row["agent"] for row in rows} == {"red", "green", "blue"}
    assert any(row["action"] == "attacks.declare" and row["result"]["id"] == ids["attack"] for row in rows)
    assert [row["action"] for row in r_red.json()] == ["invoices.submit", "invoices.submit", "vendors.create", "attacks.declare"]


async def test_green_and_red_still_forbidden(episode: str) -> None:
    async with _client() as c:
        assert (await c.get("/api/audit_log", headers=_as("green", episode))).status_code == 403
        assert (await c.get("/api/audit_log", headers=_as("red", episode))).status_code == 403
