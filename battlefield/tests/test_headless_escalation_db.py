"""DB: the gatekeeper's lineage hooks. A headless generation holds escalations for its config's
headless.escalation_timeout_sec (timeout = block); plain and demo episodes keep ESCALATION_TIMEOUT_SEC.
Blue's /gate request carries playbook_version only in lineage episodes."""

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
from tests import factories as f

pytestmark = pytest.mark.usefixtures("pg")


async def lineage_episode(status: str = "running", headless: dict | None = None) -> tuple[str, str]:
    ln, ep = f.uid("ln"), f.uid("ep")
    config = {"generations": 3, "days": 6, "controller_mode": "enforce", "reveal_days": 3, "reveal_generations": 2, "headless": headless}
    await db.execute("INSERT INTO lineages (id, base_seed, config, status, current_generation) VALUES ($1, 42, $2, $3, 1)", ln, config, status)
    await db.execute("INSERT INTO episodes (id, seed, controller_mode, lineage_id, generation) VALUES ($1, 43, 'enforce', $2, 1)", ep, ln)
    return ln, ep


@pytest.fixture
def blue_escalates(monkeypatch: pytest.MonkeyPatch) -> None:
    async def ask(c: Caller, mode: str, action: str, et: str | None, eid: str | None, amount: float | None, args: dict, context: dict, **_: Any):
        return "escalate", "Needs human review.", 0.9, ["near_threshold"]

    monkeypatch.setattr(gate, "_ask_blue", ask)


async def test_headless_generation_times_out_to_block_on_its_short_hold(monkeypatch: pytest.MonkeyPatch, blue_escalates: None) -> None:
    monkeypatch.setattr(settings, "escalation_timeout_sec", 30)  # would hang the test if it applied
    _, ep = await lineage_episode(headless={"day_pause_sec": 0, "escalation_policy": "block", "escalation_timeout_sec": 1})
    ch = await f.change(ep, await f.vendor(ep), origin="sim")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bf", timeout=30) as cl:
        t0 = asyncio.get_running_loop().time()
        r = await cl.post(f"/api/vendor_changes/{ch}/approve", headers=f.auth("green", episode=ep, day=1, tool_use_id=f"tu_{uuid.uuid4().hex}"))
        waited = asyncio.get_running_loop().time() - t0
    assert r.status_code == 403 and r.json()["reason"] == "escalated; timeout"
    assert 1 <= waited < 5
    assert await db.fetchval("SELECT status FROM escalations WHERE episode_id=$1", ep) == "timeout"


async def test_plain_and_demo_episodes_keep_the_global_hold(episode: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "escalation_timeout_sec", 90)
    headless = {"day_pause_sec": 0, "escalation_policy": "block", "escalation_timeout_sec": 5}
    assert await gate.escalation_timeout_sec(episode) == 90
    _, demo = await lineage_episode(status="finished", headless=headless)  # POST /episodes {lineage_id} needs finished/failed
    assert await gate.escalation_timeout_sec(demo) == 90
    _, no_headless = await lineage_episode(headless=None)
    assert await gate.escalation_timeout_sec(no_headless) == 90
    _, runner = await lineage_episode(status="paused", headless=headless)
    assert await gate.escalation_timeout_sec(runner) == 5


class _Capture:
    sent: list[dict[str, Any]] = []

    def __init__(self, **_: Any) -> None:
        pass

    async def __aenter__(self) -> _Capture:
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None

    async def post(self, url: str, json: dict[str, Any], headers: dict[str, str]) -> httpx.Response:
        _Capture.sent.append(json)
        return httpx.Response(200, json={"verdict": "allow", "reason": "ok", "rules_fired": []}, request=httpx.Request("POST", url))


async def test_playbook_version_reaches_blue_only_in_lineages(episode: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gate.httpx, "AsyncClient", _Capture)
    _Capture.sent = []
    ln, ep = await lineage_episode()

    async def ask(episode_id: str) -> dict[str, Any]:
        c = Caller(agent="green", episode_id=episode_id, day=1, tool_use_id=f"tu_{uuid.uuid4().hex}")
        await gate.check(c, action="invoices.pay", entity_type="invoice", entity_id=f.uid("inv"), amount=10.0)
        return _Capture.sent[-1]

    assert "playbook_version" not in await ask(episode)
    assert (await ask(ep))["playbook_version"] == 0  # synthetic v0 before blue writes anything
    for agent, version in (("blue", 0), ("blue", 1), ("red", 0), ("red", 1), ("red", 2)):
        await db.execute(
            "INSERT INTO playbooks (lineage_id, agent, version, generation, source, content) VALUES ($1, $2, $3, 1, 'turn', '{}')", ln, agent, version
        )
    assert (await ask(ep))["playbook_version"] == 1  # blue's own latest, not red's
