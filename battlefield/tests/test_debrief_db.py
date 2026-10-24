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


async def _mutation(eid: str, day: int, action: str, entity_type: str, entity_id: str) -> None:
    payload = {"agent": "green", "action": action, "entity_type": entity_type, "entity_id": entity_id}
    await db.execute("INSERT INTO events (episode_id, day, type, agent, payload) VALUES ($1,$2,'ledger.mutation','green',$3)", eid, day, payload)


async def _freeze(eid: str, vid: str, day: int) -> None:
    await db.execute("UPDATE vendors SET status='frozen' WHERE id=$1", vid)
    await db.execute(
        "INSERT INTO events (episode_id, day, type, agent, payload) VALUES ($1,$2,'vendor.frozen','blue',$3)", eid, day, {"vendor_id": vid, "reason": "t"}
    )


async def test_each_agent_sees_only_resolved_attacks() -> None:
    eid = await _lineage_episode()
    aid, vid, inv = await _paid_red_invoice(eid)
    await _mutation(eid, 1, "invoices.pay", "invoice", inv)
    await f.flag(eid, "vendor", vid, day=1)
    pending_aid = await f.attack(eid, day=1, scheme_id="duplicate_invoice")
    await f.invoice(eid, await f.vendor(eid), origin="red", status="pending", attack_id=pending_aid, day=1)
    froze_aid = await f.attack(eid, day=1, scheme_id="ghost_vendor")
    froze_vid = await f.vendor(eid, origin="red")
    froze_inv = await f.invoice(eid, froze_vid, origin="red", status="blocked", attack_id=froze_aid, day=1)  # stopped by a freeze; green never acted
    legit_vid = await f.vendor(eid)
    legit_blocked = await f.invoice(eid, legit_vid, amount=900, status="blocked", day=1)
    v_block = await f.verdict(eid, "invoice", legit_blocked, verdict="block", day=1)

    await score.end_of_day(eid, 1)
    await debrief.deliver(eid, 1, await _ctx(eid))

    assert await _attack_row(aid) == {"outcome": "extracted", "detected_day": 1, "resolved_day": 1, "revealed_day": 1}
    assert (await _attack_row(pending_aid))["revealed_day"] is None  # unresolved: never revealed mid-episode

    red = await _items(eid, "red", 1)
    assert [i["attack_id"] for i in red] == [aid, froze_aid] and all(i["kind"] == "attack" and i["new"] for i in red)
    assert [c["kind"] for c in red[0]["controls"]] == ["verdict", "flag"] and red[0]["controls"][0]["rules_fired"] == ["near_threshold"]

    blue = await _items(eid, "blue", 1)
    assert [i["kind"] for i in blue] == ["attack", "attack"]  # no false_positive items daily (absence inference)
    assert [c["kind"] for c in blue[0]["caught_by"]] == ["flag"]  # the allow verdict is not a catch
    assert {"entity_type": "invoice", "entity_id": inv, "amount": 4000.0} in blue[0]["entities"]
    assert {"entity_type": "vendor", "entity_id": vid} in blue[0]["entities"]

    green = await _items(eid, "green", 1)
    assert [(i["kind"], i["entity_id"], i["green_action"]) for i in green] == [("fraud", inv, "invoices.pay")]  # its real, last action
    assert froze_inv not in str(green) and legit_blocked not in str(green + blue)

    for items in (red, blue, green):
        assert "origin" not in str(items)
    events = await db.fetch("SELECT payload FROM events WHERE episode_id=$1 AND type='debrief.delivered' ORDER BY id", eid)
    assert [e["payload"] for e in events] == [
        {"agent": "red", "day": 1, "revealed_attacks": 2, "new_items": 2, "window_days": 3},
        {"agent": "green", "day": 1, "revealed_attacks": 0, "new_items": 1, "window_days": 3},
        {"agent": "blue", "day": 1, "revealed_attacks": 2, "new_items": 2, "window_days": 3},
    ]

    # the legit items go to the after-action review instead
    aar = await debrief.legit_items(eid)
    assert [(i["kind"], i["entity_id"]) for i in aar["blue"]] == [("false_positive", legit_blocked)]
    assert aar["blue"][0]["by"] == {"kind": "verdict", "id": v_block, "rules_fired": []}
    assert [(i["kind"], i["verdict_id"], i["amount"]) for i in aar["green"]] == [("legit_blocked", v_block, 900.0)]


async def test_resolved_day_is_set_once(episode: str) -> None:
    vid = await f.vendor(episode)
    aid = await f.attack(episode, day=1)
    await f.invoice(episode, vid, origin="red", status="rejected", attack_id=aid, day=1)
    await score.resolve_attacks(episode, 1)
    await score.resolve_attacks(episode, 4)
    assert await _attack_row(aid) == {"outcome": "blocked", "detected_day": None, "resolved_day": 1, "revealed_day": None}


async def test_revealed_outcome_is_frozen_and_items_end_at_reveal() -> None:
    eid = await _lineage_episode()
    aid, vid, inv = await _paid_red_invoice(eid)
    await score.end_of_day(eid, 1)
    await debrief.deliver(eid, 1, await _ctx(eid))
    # hindsight: blue freezes and flags after the reveal
    await _freeze(eid, vid, 2)
    await f.flag(eid, "invoice", inv, day=2)
    await score.end_of_day(eid, 2)
    await debrief.deliver(eid, 2, await _ctx(eid))
    assert await _attack_row(aid) == {"outcome": "extracted", "detected_day": None, "resolved_day": 1, "revealed_day": 1}
    [red] = await _items(eid, "red", 2)
    assert red["new"] is False and all(c["day"] <= 1 for c in red["controls"])  # controls bounded to revealed_day
    [blue] = await _items(eid, "blue", 2)
    assert blue["caught_by"] == []


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
    ctx = await _ctx(eid)
    for day in (1, 2, 3):
        await score.end_of_day(eid, day)
        await debrief.deliver(eid, day, ctx)
    assert [(i["attack_id"], i["new"]) for i in await _items(eid, "red", 1)] == [(aid, True)]
    assert [(i["attack_id"], i["new"]) for i in await _items(eid, "red", 2)] == [(aid, False)]
    assert await _items(eid, "red", 3) == []  # revealed on day 1, outside days 2..3


async def test_attribution_runs_over_every_attack() -> None:
    """Red files C1 before declaring anything, then declares A (an invoice) and B (change-only).
    C1 (NULL attack_id) belongs to B by the same-day fallback, whichever attacks are being revealed."""
    eid = await _lineage_episode()
    v1 = await f.vendor(eid)
    c1 = await f.change(eid, v1, day=1)  # pending, attack_id NULL
    aid, red_vid, inv = await _paid_red_invoice(eid)
    bid = await f.attack(eid, day=1, scheme_id="bank_swap", target_amount=6_000)
    c2 = await f.change(eid, await f.vendor(eid), day=1, attack_id=bid)
    await score.end_of_day(eid, 1)
    await debrief.deliver(eid, 1, await _ctx(eid))
    assert (await _attack_row(bid))["revealed_day"] is None
    [a_item] = [i for i in await _items(eid, "blue", 1) if i["attack_id"] == aid]
    assert {e["entity_id"] for e in a_item["entities"]} == {inv, red_vid}

    await db.execute("UPDATE vendor_changes SET status='rejected', resolved_day=2 WHERE id = ANY($1::text[])", [c1, c2])
    await score.resolve_attacks(eid, 2)
    before = await score.compute(eid)
    await debrief.deliver(eid, 2, await _ctx(eid))
    assert (await _attack_row(bid))["revealed_day"] == 2
    [b_item] = [i for i in await _items(eid, "blue", 2) if i["attack_id"] == bid]
    assert {c1, c2} <= {e["entity_id"] for e in b_item["entities"]}
    assert await score.compute(eid) == before and before["dollars_blocked"] == 6_000


async def test_live_bank_swap_is_not_resolved() -> None:
    eid = await _lineage_episode()
    vid = await f.vendor(eid)
    aid = await f.attack(eid, day=1)
    await f.change(eid, vid, day=1, status="approved", resolved_day=1, attack_id=aid)
    paid = await f.invoice(eid, vid, status="paid", day=1)
    await f.payment(eid, paid, amount=1_000, to_account="ACCT-RED", day=1)
    await score.end_of_day(eid, 1)
    await debrief.deliver(eid, 1, await _ctx(eid))
    assert await _attack_row(aid) == {"outcome": "extracted", "detected_day": None, "resolved_day": None, "revealed_day": None}
    assert await _items(eid, "red", 1) == []
    await f.change(eid, vid, origin="sim", day=2, status="approved", resolved_day=2, new_value="ACCT-NEW")  # swap no longer live
    await score.end_of_day(eid, 2)
    await debrief.deliver(eid, 2, await _ctx(eid))
    assert (await _attack_row(aid))["revealed_day"] == 2


async def test_revealed_attack_score_ignores_hindsight_freeze(episode: str) -> None:
    async def run(eid: str, *, lineage: bool) -> tuple[float, float]:
        vid = await f.vendor(eid)
        aid = await f.attack(eid, day=1, target_amount=8_000)
        await f.change(eid, vid, day=1, field="address", status="approved", resolved_day=1, attack_id=aid)
        await score.end_of_day(eid, 1)
        if lineage:
            await debrief.deliver(eid, 1, await _ctx(eid))
            assert await _attack_row(aid) == {"outcome": "failed", "detected_day": None, "resolved_day": 1, "revealed_day": 1}
        before = (await score.compute(eid))["dollars_blocked"]
        await _freeze(eid, vid, 2)
        return before, (await score.compute(eid))["dollars_blocked"]

    assert await run(await _lineage_episode(), lineage=True) == (0, 0)
    assert await run(episode, lineage=False) == (0, 8_000)  # control: unrevealed, the freeze counts


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
