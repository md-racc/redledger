import asyncio

from audit import snapshot as evidence

from .audit_helpers import FakeLedger, invoice


async def test_snapshot_collects_once_at_most_four_concurrent_reads():
    ledger = FakeLedger()
    snapshot = await evidence.collect_snapshot(ledger, "ep", 5)
    assert ledger.max_read_active <= 4
    assert len(ledger.read_counts) == 8 and all(v == 1 for v in ledger.read_counts.values())
    assert len(snapshot.coverage) == 8 and all(c.status == "complete" for c in snapshot.coverage)


async def test_snapshot_row_cap_cross_episode_and_malformed_coverage():
    rows = [invoice(f"i_{i}") for i in range(2002)]
    rows[1]["episode_id"] = "other"
    rows[2]["amount"] = "NaN"
    ledger = FakeLedger(invoices=rows)
    snapshot = await evidence.collect_snapshot(ledger, "ep", 5)
    coverage = next(c for c in snapshot.coverage if c.dataset == "invoices")
    assert len(snapshot.datasets["invoices"]) == 1998
    assert coverage.status == "truncated" and coverage.omitted == 4


async def test_snapshot_timeout_partial_coverage(monkeypatch):
    ledger = FakeLedger()
    ledger.read_block = asyncio.Event()
    monkeypatch.setattr(evidence, "COLLECTION_TIMEOUT", 0.02)
    snapshot = await evidence.collect_snapshot(ledger, "ep", 5)
    assert len(snapshot.coverage) == 8
    assert all(c.status == "unavailable" for c in snapshot.coverage)
    assert ledger.read_active == 0


def test_outcome_counts_only_confirmed_effects():
    from audit.models import AuditSession, ConfirmedEffect, Coverage, Snapshot

    session = AuditSession("ep", 5, True, 170, snapshot=Snapshot("ep", 5))
    session.snapshot.coverage = [Coverage(dataset="invoices", status="complete")]
    for state in ("attempted", "confirmed", "failed", "unknown"):
        session.effects.append(ConfirmedEffect(kind="flag", key=state, tool_use_id=state, state=state))
    outcome = session.outcome()
    assert outcome.flags_raised == 1 and outcome.partial and not outcome.report_posted
    assert "2 unknown writes" in outcome.summary
