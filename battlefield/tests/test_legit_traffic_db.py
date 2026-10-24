"""DB: legit traffic's false-positive bait (legit bank changes, legit new vendors) and how it scores."""

from __future__ import annotations

import pytest

from app import db
from app.config import settings
from app.orchestrator import legit_traffic as lt
from app.scoring import score
from seed.company import seed_episode
from tests import factories as f

pytestmark = pytest.mark.usefixtures("pg")

SEED = 42
DAYS = 10
COUNT_KEYS = {"invoices", "purchase_orders", "expenses", "bank_lines", "vendor_changes", "new_vendors"}


async def _episode(seed: int = SEED) -> str:
    eid = f.uid("ep")
    await db.execute("INSERT INTO episodes (id, seed, controller_mode) VALUES ($1, $2, 'enforce')", eid, seed)
    return eid


async def _run(seed: int = SEED, days: int = DAYS) -> tuple[str, list[dict[str, int]]]:
    """A seeded company, then `days` of legit traffic with nobody processing it."""
    eid = await _episode(seed)
    await seed_episode(eid, seed)
    return eid, [await lt.inject(eid, seed, d) for d in range(days)]


async def _snapshot(eid: str) -> dict[str, list[tuple]]:
    """Everything legit traffic wrote during the episode, keyed by stable columns (ids are random)."""
    q = {
        "vendors": "SELECT name, ein, bank_account, bank_routing, address, category, created_day, created_by FROM vendors WHERE episode_id=$1 AND created_day >= 0",
        "purchase_orders": "SELECT v.name, po.amount, po.description, po.created_day FROM purchase_orders po JOIN vendors v ON v.id=po.vendor_id "
        "WHERE po.episode_id=$1 AND po.created_day >= 0",
        "invoices": "SELECT v.name, i.amount, i.invoice_number, i.received_day, po.amount AS po_amount FROM invoices i JOIN vendors v ON v.id=i.vendor_id "
        "LEFT JOIN purchase_orders po ON po.id=i.po_id WHERE i.episode_id=$1 AND i.received_day >= 0",
        "vendor_changes": "SELECT v.name, ch.field, ch.old_value, ch.new_value, ch.justification, ch.requested_day FROM vendor_changes ch "
        "JOIN vendors v ON v.id=ch.vendor_id WHERE ch.episode_id=$1",
        "expenses": "SELECT e.name, x.amount, x.category, x.submitted_day FROM expenses x JOIN employees e ON e.id=x.employee_id WHERE x.episode_id=$1",
    }
    return {k: sorted(tuple(r.values()) for r in await db.fetch(sql, eid)) for k, sql in q.items()}


async def test_generation_is_deterministic_for_seed_and_day() -> None:
    a, counts_a = await _run()
    b, counts_b = await _run()
    assert counts_a == counts_b
    assert all(set(c) == COUNT_KEYS for c in counts_a)
    snap = await _snapshot(a)
    assert snap == await _snapshot(b)
    assert snap["vendor_changes"] and snap["vendors"]  # the bait is actually there
    other, _ = await _run(seed=7, days=4)
    assert await _snapshot(other) != snap


async def test_counts_match_rows_and_schedule() -> None:
    eid, counts = await _run()
    for d, c in enumerate(counts):
        assert c["vendor_changes"] == int(lt.bank_change_scheduled(SEED, d))
        assert c["new_vendors"] == int(lt.new_vendor_scheduled(SEED, d))
        rows = {
            "invoices": "SELECT COUNT(*) FROM invoices WHERE episode_id=$1 AND received_day=$2",
            "purchase_orders": "SELECT COUNT(*) FROM purchase_orders WHERE episode_id=$1 AND created_day=$2",
            "vendor_changes": "SELECT COUNT(*) FROM vendor_changes WHERE episode_id=$1 AND requested_day=$2",
            "new_vendors": "SELECT COUNT(*) FROM vendors WHERE episode_id=$1 AND created_day=$2",
        }
        for key, sql in rows.items():
            assert await db.fetchval(sql, eid, d) == c[key], (d, key)
    assert sum(c["vendor_changes"] for c in counts) >= DAYS // lt.BANK_CHANGE_WINDOW
    assert sum(c["new_vendors"] for c in counts) >= DAYS // lt.NEW_VENDOR_WINDOW


async def test_bank_changes_come_from_established_sim_vendors_with_current_account() -> None:
    eid, _ = await _run()
    changes = await db.fetch(
        "SELECT ch.*, v.bank_account AS current, v.origin AS v_origin, v.created_day FROM vendor_changes ch JOIN vendors v ON v.id=ch.vendor_id WHERE ch.episode_id=$1",
        eid,
    )
    assert changes
    for ch in changes:
        assert ch["origin"] == "sim" and ch["v_origin"] == "sim"
        assert ch["field"] == "bank_account" and ch["status"] == "pending"
        assert ch["old_value"] == ch["current"]  # self-consistent: it moves the account the vendor really has
        assert ch["new_value"] != ch["old_value"] and len(ch["new_value"]) == 10
        assert ch["requested_day"] - ch["created_day"] >= lt.ESTABLISHED_AGE
        assert ch["justification"]
    assert len({ch["vendor_id"] for ch in changes}) == len(changes)  # one change per vendor per 30 days


async def _bank_change_day(seed: int = SEED) -> int:
    return next(d for d in range(lt.BANK_CHANGE_WINDOW) if lt.bank_change_scheduled(seed, d))


async def test_bank_change_prefers_a_vendor_with_open_invoices(monkeypatch: pytest.MonkeyPatch) -> None:
    day = await _bank_change_day()
    for share, want_open in ((1.0, True), (0.0, False)):
        monkeypatch.setattr(lt, "BANK_CHANGE_OPEN_SHARE", share)
        eid = await _episode()
        with_open = await f.vendor(eid, bank_account="1111111111")
        idle = await f.vendor(eid, bank_account="2222222222")
        await f.invoice(eid, with_open, amount=3200, status="matched")
        await f.invoice(eid, idle, amount=900, status="paid")
        assert await lt._bank_change(eid, SEED, day)
        ch = await db.fetchrow("SELECT * FROM vendor_changes WHERE episode_id=$1", eid)
        assert ch["vendor_id"] == (with_open if want_open else idle)
        assert ch["old_value"] == ("1111111111" if want_open else "2222222222")


async def test_bank_change_skips_young_frozen_red_and_recently_changed_vendors() -> None:
    day = await _bank_change_day()
    eid = await _episode()
    young = await f.insert("vendors", episode_id=eid, name="Young Co", bank_account="1", bank_routing="2", created_day=day - 5, origin="sim")
    await f.vendor(eid, status="frozen")
    await f.vendor(eid, origin="red")
    pending_red = await f.vendor(eid)
    await f.change(eid, pending_red, origin="red", day=day - 40, status="pending")
    recent = await f.vendor(eid)
    await f.change(eid, recent, origin="sim", day=day - 10, status="approved", resolved_day=day - 9)
    assert not await lt._bank_change(eid, SEED, day)
    ok = await f.vendor(eid)
    assert await lt._bank_change(eid, SEED, day)
    assert await db.fetchval("SELECT vendor_id FROM vendor_changes WHERE episode_id=$1 AND origin='sim' AND requested_day=$2", eid, day) == ok
    assert young  # created, never picked


async def test_new_vendors_get_a_po_then_a_first_invoice_under_it() -> None:
    eid, _ = await _run()
    onboarded = [d for d in range(DAYS) if lt.new_vendor_scheduled(SEED, d)]
    vendors = await db.fetch("SELECT * FROM vendors WHERE episode_id=$1 AND created_day >= 0 ORDER BY created_day", eid)
    assert [v["created_day"] for v in vendors] == onboarded
    for v in vendors:
        assert v["origin"] == "sim" and v["created_by"] == lt.ONBOARDED_BY and v["status"] == "active"
        pos = await db.fetch("SELECT * FROM purchase_orders WHERE vendor_id=$1", v["id"])
        assert len(pos) == 1 and pos[0]["created_day"] == v["created_day"] and pos[0]["origin"] == "sim"
        invoices = await db.fetch("SELECT * FROM invoices WHERE vendor_id=$1", v["id"])
        due = v["created_day"] + lt.first_invoice_delay(SEED, v["created_day"])
        if due >= DAYS:
            assert invoices == []
            continue
        assert len(invoices) == 1
        inv = invoices[0]
        assert inv["po_id"] == pos[0]["id"] and inv["received_day"] == due and inv["origin"] == "sim" and inv["attack_id"] is None
        assert float(inv["amount"]) > 1000  # trips vendor_age_lt_7d
        assert abs(float(inv["amount"]) - float(pos[0]["amount"])) <= float(pos[0]["amount"]) * 0.03 + 0.01
    # no PO is billed twice by the generic traffic either
    assert not await db.fetch("SELECT po_id FROM invoices WHERE episode_id=$1 AND po_id IS NOT NULL GROUP BY po_id HAVING COUNT(*) > 1", eid)


async def test_blocked_legit_bait_counts_as_false_positives() -> None:
    eid, _ = await _run()
    assert (await score.compute(eid))["legit_blocked"] == 0
    ch = await db.fetchrow("SELECT id FROM vendor_changes WHERE episode_id=$1 AND origin='sim' ORDER BY requested_day LIMIT 1", eid)
    inv = await db.fetchrow(
        "SELECT i.id, i.amount FROM invoices i JOIN vendors v ON v.id=i.vendor_id WHERE i.episode_id=$1 AND v.created_day >= 0 ORDER BY i.received_day LIMIT 1",
        eid,
    )
    assert ch and inv
    # what the gate does on a block: verdict row + entity marked blocked (green_writes._gated)
    await f.verdict(eid, "vendor_change", ch["id"], verdict="block", day=2)
    await db.execute("UPDATE vendor_changes SET status='blocked' WHERE id=$1", ch["id"])
    await f.verdict(eid, "invoice", inv["id"], verdict="block", day=3)
    await db.execute("UPDATE invoices SET status='blocked', status_day=3 WHERE id=$1", inv["id"])
    # a second legit bank change, escalated and still waiting on a human
    other = await db.fetchrow("SELECT id FROM vendor_changes WHERE episode_id=$1 AND origin='sim' AND id<>$2 LIMIT 1", eid, ch["id"])
    await f.verdict(eid, "vendor_change", other["id"], verdict="escalate", day=4)

    s = await score.compute(eid)
    assert s["legit_blocked"] == 2
    expected = float(inv["amount"]) * settings.fp_penalty_rate + (2 + 1) * settings.fp_flat_penalty
    assert s["false_positive_cost"] == round(expected, 2)
    assert s["attacks_launched"] == 0 and s["dollars_blocked"] == 0  # legit traffic never looks like an attack to scoring
