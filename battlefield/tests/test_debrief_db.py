"""DB: lineage debriefs (contracts/agent-service.md "Lineages"), resolved/revealed attacks."""

from __future__ import annotations

from typing import Any

import pytest

from app import db
from app.evolution import debrief
from app.orchestrator import agents, runner
from app.scoring import score
from seed.company import seed_episode
from tests import factories as f

pytestmark = pytest.mark.usefixtures("pg")


async def _lineage_episode(*, days: int = 6, reveal_days: int = 3, seed: int = 4242) -> str:
    lid, eid = f.uid("ln"), f.uid("ep")
    await db.execute("INSERT INTO lineages (id, base_seed, config) VALUES ($1, $2, $3)", lid, seed - 1, {"days": days, "reveal_days": reveal_days})
    await db.execute(
        "INSERT INTO episodes (id, seed, controller_mode, days, lineage_id, generation) VALUES ($1, $2, 'enforce', $3, $4, 1)", eid, seed, days, lid
    )
    return eid


async def _ctx(eid: str) -> dict[str, Any]:
    ctx = await debrief.context(eid)
    assert ctx is not None
    return ctx


async def _items(eid: str, agent: str, day: int) -> list[dict[str, Any]]:
    payload = await db.fetchval("SELECT payload FROM debriefs WHERE episode_id=$1 AND agent=$2 AND day=$3", eid, agent, day)
    return payload["items"]


async def _attack_row(aid: str) -> dict[str, Any]:
    return dict(await db.fetchrow("SELECT outcome, detected_day, resolved_day, revealed_day FROM attacks WHERE id=$1", aid))


async def _paid_red_invoice(eid: str, *, day: int = 1) -> tuple[str, str, str]:
    """A resolved red attack: one invoice from a red vendor, approved (allow) and paid on `day`."""
    vid = await f.vendor(eid, origin="red", bank_account="ACCT-RED")
    aid = await f.attack(eid, day=day, scheme_id="ghost_vendor", target_amount=4_000)
    inv = await f.invoice(eid, vid, amount=4_000, origin="red", status="paid", attack_id=aid, day=day)
    await db.execute("UPDATE verdicts SET rules_fired=$2 WHERE id=$1", await f.verdict(eid, "invoice", inv, verdict="allow", day=day), ["near_threshold"])
    return aid, vid, inv


async def test_each_agent_sees_only_what_it_may_know(monkeypatch: pytest.MonkeyPatch) -> None:
    eid = await _lineage_episode()
    aid, vid, inv = await _paid_red_invoice(eid)
    await f.flag(eid, "vendor", vid, day=1)
    pending_aid = await f.attack(eid, day=1, scheme_id="duplicate_invoice")
    await f.invoice(eid, await f.vendor(eid), origin="red", status="pending", attack_id=pending_aid, day=1)
    legit_vid = await f.vendor(eid)
    legit_blocked = await f.invoice(eid, legit_vid, amount=900, status="blocked", day=1)
    v_block = await f.verdict(eid, "invoice", legit_blocked, verdict="block", day=1)
    still_open = await f.invoice(eid, legit_vid, status="pending", day=1)
    await f.verdict(eid, "invoice", still_open, verdict="block", day=1)

    await score.end_of_day(eid, 1)
    await debrief.deliver(eid, 1, await _ctx(eid))

    assert await _attack_row(aid) == {"outcome": "extracted", "detected_day": 1, "resolved_day": 1, "revealed_day": 1}
    assert (await _attack_row(pending_aid))["revealed_day"] is None  # unresolved: never revealed mid-episode

    [red] = await _items(eid, "red", 1)
    assert red["kind"] == "attack" and red["attack_id"] == aid and red["new"] is True and red["outcome"] == "extracted"
    assert [c["kind"] for c in red["controls"]] == ["verdict", "flag"]
    assert red["controls"][0]["rules_fired"] == ["near_threshold"] and "_revealed_day" not in red

    blue = await _items(eid, "blue", 1)
    [battack] = [i for i in blue if i["kind"] == "attack"]
    assert battack["attack_id"] == aid and [c["kind"] for c in battack["caught_by"]] == ["flag"]  # the allow verdict is not a catch
    assert {"entity_type": "invoice", "entity_id": inv, "amount": 4000.0} in battack["entities"]
    assert {"entity_type": "vendor", "entity_id": vid} in battack["entities"]
    [fp] = [i for i in blue if i["kind"] == "false_positive"]
    assert fp["entity_id"] == legit_blocked and fp["by"] == {"kind": "verdict", "id": v_block, "rules_fired": []} and fp["new"] is True
    assert still_open not in str(blue)  # legit item not in a terminal status

    green = await _items(eid, "green", 1)
    assert [(i["kind"], i["entity_id"]) for i in green] == [("fraud", inv), ("legit_blocked", legit_blocked)]
    assert green[0]["green_action"] == "invoices.approve" and green[0]["outcome"] == "paid"
    assert green[1]["verdict_id"] == v_block and green[1]["amount"] == 900.0

    for items in (red, *blue, *green):
        assert "origin" not in str(items)
    events = await db.fetch("SELECT payload FROM events WHERE episode_id=$1 AND type='debrief.delivered' ORDER BY id", eid)
    assert [e["payload"] for e in events] == [
        {"agent": "red", "day": 1, "revealed_attacks": 1, "new_items": 1, "window_days": 3},
        {"agent": "green", "day": 1, "revealed_attacks": 0, "new_items": 2, "window_days": 3},
        {"agent": "blue", "day": 1, "revealed_attacks": 1, "new_items": 2, "window_days": 3},
    ]


async def test_resolved_day_is_set_once(episode: str) -> None:
    vid = await f.vendor(episode)
    aid = await f.attack(episode, day=1)
    await f.invoice(episode, vid, origin="red", status="rejected", attack_id=aid, day=1)
    await score.resolve_attacks(episode, 1)
    await score.resolve_attacks(episode, 4)
    assert await _attack_row(aid) == {"outcome": "blocked", "detected_day": None, "resolved_day": 1, "revealed_day": None}


async def test_revealed_outcome_is_frozen() -> None:
    eid = await _lineage_episode()
    aid, vid, _ = await _paid_red_invoice(eid)
    await score.end_of_day(eid, 1)
    await debrief.deliver(eid, 1, await _ctx(eid))
    # hindsight: blue freezes and flags the vendor after the reveal
    await db.execute("UPDATE vendors SET status='frozen' WHERE id=$1", vid)
    await f.flag(eid, "invoice", (await db.fetchval("SELECT id FROM invoices WHERE attack_id=$1", aid)), day=2)
    await score.resolve_attacks(eid, 2)
    assert await _attack_row(aid) == {"outcome": "extracted", "detected_day": None, "resolved_day": 1, "revealed_day": 1}


async def test_hindsight_would_change_an_unrevealed_attack(episode: str) -> None:
    """Control for the test above: without the reveal the same freeze makes the attack partial."""
    vid = await f.vendor(episode, origin="red")
    aid = await f.attack(episode, day=1)
    await f.invoice(episode, vid, origin="red", status="paid", attack_id=aid, day=1)
    await score.resolve_attacks(episode, 1)
    await db.execute("UPDATE vendors SET status='frozen' WHERE id=$1", vid)
    await score.resolve_attacks(episode, 2)
    assert (await _attack_row(aid))["outcome"] == "partial"


async def test_window_slides_and_new_marks_first_appearance() -> None:
    eid = await _lineage_episode(reveal_days=2)
    aid, *_ = await _paid_red_invoice(eid)
    legit = await f.invoice(eid, await f.vendor(eid), status="rejected", day=1)
    await f.flag(eid, "invoice", legit, day=1)
    ctx = await _ctx(eid)
    for day in (1, 2, 3):
        await score.end_of_day(eid, day)
        await debrief.deliver(eid, day, ctx)
    assert [(i["attack_id"], i["new"]) for i in await _items(eid, "red", 1)] == [(aid, True)]
    assert [(i["attack_id"], i["new"]) for i in await _items(eid, "red", 2)] == [(aid, False)]
    assert await _items(eid, "red", 3) == []  # revealed on day 1, outside days 2..3
    fps = [[(i["entity_id"], i["new"]) for i in await _items(eid, "blue", d) if i["kind"] == "false_positive"] for d in (1, 2, 3)]
    assert fps == [[(legit, True)], [(legit, False)], []]


async def test_last_day_and_zero_window_deliver_nothing() -> None:
    eid = await _lineage_episode(days=3)
    await _paid_red_invoice(eid, day=2)
    await score.end_of_day(eid, 2)
    await debrief.deliver(eid, 2, await _ctx(eid))  # day 2 is the last of 3
    eid0 = await _lineage_episode(reveal_days=0, seed=777)
    await debrief.deliver(eid0, 1, await _ctx(eid0))
    for e in (eid, eid0):
        assert await db.fetchval("SELECT COUNT(*) FROM debriefs WHERE episode_id=$1", e) == 0
        assert await db.fetchval("SELECT COUNT(*) FROM events WHERE episode_id=$1 AND type='debrief.delivered'", e) == 0


class _Agents:
    def __init__(self) -> None:
        self.turns: list[tuple[str, int, dict[str, Any]]] = []
        self.audits: list[tuple[int, dict[str, Any]]] = []

    async def turn(self, agent: str, episode_id: str, day: int, mode: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        self.turns.append((agent, day, options or {}))
        if agent == "red" and day == 0:
            await _paid_red_invoice(episode_id, day=0)
        return {"ok": True, "summary": "stub", "duration_sec": 0}

    async def audit(self, episode_id: str, day: int, inputs: list | None = None, **extra: Any) -> dict[str, Any]:
        self.audits.append((day, extra))
        return {"ok": True, "summary": "stub"}


async def test_run_day_delivers_on_the_next_turn_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    eid = await _lineage_episode(days=3)
    await seed_episode(eid, 4242)
    stub = _Agents()
    monkeypatch.setattr(agents, "turn", stub.turn)
    monkeypatch.setattr(agents, "audit", stub.audit)
    lid = await db.fetchval("SELECT lineage_id FROM episodes WHERE id=$1", eid)

    await runner.run_day(eid)
    red0 = stub.turns[0][2]
    assert red0["lineage"] == {"id": lid, "generation": 1, "playbook_version": 0} and "debrief" not in red0
    types = [r["type"] for r in await db.fetch("SELECT type FROM events WHERE episode_id=$1 AND day=0 ORDER BY id", eid)]
    tail = types[types.index("score.updated") :]
    assert tail == ["score.updated", "debrief.delivered", "debrief.delivered", "debrief.delivered", "day.ended"]

    # a restart between the two days loses nothing: day 1's turns read day 0's debriefs from the table
    runner._states.pop(eid, None)
    await debrief.deliver(eid, 0, await _ctx(eid))  # a resumed day 0 re-delivers nothing
    assert await db.fetchval("SELECT COUNT(*) FROM debriefs WHERE episode_id=$1", eid) == 3
    await runner.run_day(eid)
    by_agent = {a: o for a, d, o in stub.turns if d == 1}
    assert by_agent["red"]["debrief"] == await db.fetchval("SELECT payload FROM debriefs WHERE episode_id=$1 AND agent='red' AND day=0", eid)
    assert by_agent["red"]["debrief"]["items"][0]["kind"] == "attack"
    assert by_agent["green"]["debrief"]["day"] == 0
    day1_audit = dict(stub.audits)[1]
    assert day1_audit["lineage"]["id"] == lid and day1_audit["debrief"]["day"] == 0


async def test_plain_episode_is_unchanged(episode: str, monkeypatch: pytest.MonkeyPatch) -> None:
    await seed_episode(episode, 42)
    stub = _Agents()
    monkeypatch.setattr(agents, "turn", stub.turn)
    monkeypatch.setattr(agents, "audit", stub.audit)
    await runner.run_day(episode)
    await runner.run_day(episode)
    assert all("lineage" not in o and "debrief" not in o for _, _, o in stub.turns)
    assert all(extra == {} for _, extra in stub.audits)
    assert await db.fetchval("SELECT COUNT(*) FROM debriefs WHERE episode_id=$1", episode) == 0
    assert await db.fetchval("SELECT COUNT(*) FROM attacks WHERE episode_id=$1 AND revealed_day IS NOT NULL", episode) == 0
    assert await db.fetchval("SELECT COUNT(*) FROM events WHERE episode_id=$1 AND type='debrief.delivered'", episode) == 0
