import asyncio
import time

import httpx
import pytest

from agentkit.ledger_client import LedgerError
from audit import evidence, tools

from .audit_helpers import FakeLedger, invoice, turn, vendor


@pytest.mark.parametrize(
    "failure,state",
    [
        (LedgerError(422, "private"), "failed"),
        (LedgerError(500, "private"), "unknown"),
        (httpx.ReadTimeout("private"), "unknown"),
        ("invalid", "unknown"),
    ],
)
async def test_partial_effect_receipts_report_and_same_day_no_retry(runtime, failure, state):
    ledger = FakeLedger(vendors=[vendor(created_day=5)], invoices=[invoice(amount=4920)])
    ledger.write_failures["flag"] = failure
    agent, ledger, _ = runtime(ledger)
    first = await agent.run_turn(turn())
    assert not first.ok
    outcome = agent.outcome("ep", 5)
    assert outcome.flags_raised == 0 and outcome.report_posted and outcome.partial
    assert state in first.summary if state == "unknown" else "Partial" in first.summary
    count = len(ledger.writes)
    assert await agent.run_turn(turn(options={"inputs": [{"payload": "richer lead"}]})) == first
    assert len(ledger.writes) == count
    assert "private" not in first.summary


async def test_report_failure_is_not_model_success(runtime):
    ledger = FakeLedger()
    ledger.write_failures["report"] = LedgerError(503, "private")
    agent, ledger, _ = runtime(ledger)
    response = await agent.run_turn(turn())
    assert not response.ok
    outcome = agent.outcome("ep", 5)
    assert not outcome.report_posted and outcome.flags_raised == 0 and outcome.partial
    await agent.run_turn(turn())
    assert len(ledger.writes) == 1


async def test_existing_findings_suppressed_across_days_and_same_day_replayed(runtime):
    ledger = FakeLedger(vendors=[vendor(created_day=5)], invoices=[invoice(amount=4920)])
    snapshot = await evidence.collect_snapshot(ledger, "ep", 5)
    finding = snapshot.findings[0]
    ledger.datasets["flags"] = [
        {
            "id": "existing",
            "entity_type": finding.entity_type,
            "entity_id": finding.entity_id,
            "severity": finding.severity,
            "reason": finding.reason,
        }
    ]
    agent, ledger, _ = runtime(ledger)
    response = await agent.run_turn(turn())
    assert response.ok and agent.outcome("ep", 5).flags_raised == 0
    await agent.run_turn(turn())
    assert [kind for kind, _, _ in ledger.writes] == ["report"]


async def test_write_timeout_reports_unknown_and_never_retries(runtime, monkeypatch):
    ledger = FakeLedger(vendors=[vendor(created_day=5)], invoices=[invoice(amount=4920)])
    ledger.write_failures["flag"] = "hang"
    monkeypatch.setattr(tools, "WRITE_TIMEOUT", 0.02)
    agent, ledger, _ = runtime(ledger)
    response = await agent.run_turn(turn())
    assert not response.ok and "1 unknown writes" in response.summary
    assert agent.outcome("ep", 5).report_posted
    await agent.run_turn(turn())
    assert [kind for kind, _, _ in ledger.writes] == ["flag", "report"]


async def test_confirmed_flags_survive_report_failure_and_receipts_are_retained(runtime):
    ledger = FakeLedger(vendors=[vendor(created_day=5)], invoices=[invoice(amount=4920)])
    ledger.write_failures["report"] = LedgerError(503, "private")
    agent, ledger, emitter = runtime(ledger)
    response = await agent.run_turn(turn())
    assert not response.ok
    outcome = agent.outcome("ep", 5)
    assert outcome.flags_raised == 1 and not outcome.report_posted
    receipts = agent.receipts[("ep", 5)]
    assert [(r.kind, r.state) for r in receipts] == [("flag", "confirmed"), ("report", "unknown")]
    assert receipts[0].tool_use_id in {call[2] for call in emitter.calls}


async def test_unknown_flags_not_blindly_retried_on_later_days(runtime):
    ledger = FakeLedger(vendors=[vendor(created_day=5)], invoices=[invoice(amount=4920)])
    ledger.write_failures["flag"] = httpx.ReadTimeout("private")
    agent, ledger, _ = runtime(ledger)
    await agent.run_turn(turn())
    await agent.run_turn(turn(day=6))
    assert [kind for kind, _, _ in ledger.writes].count("flag") == 1
    assert "prior commit outcome unknown" in agent.outcome("ep", 6).summary
    assert len(agent.receipts[("ep", 5)]) == 2


async def test_confirmed_flags_locally_suppressed_on_later_days_even_if_read_missing(runtime):
    ledger = FakeLedger(vendors=[vendor(created_day=5)], invoices=[invoice(amount=4920)])
    agent, ledger, _ = runtime(ledger)
    await agent.run_turn(turn())
    ledger.fail_reads.add("flags")
    await agent.run_turn(turn(day=6))
    assert [kind for kind, _, _ in ledger.writes].count("flag") == 1
    assert agent.outcome("ep", 6).partial


async def test_cancellation_preserves_unknown_commit_and_report_attempt(runtime):
    ledger = FakeLedger(vendors=[vendor(created_day=5)], invoices=[invoice(amount=4920)])
    ledger.write_failures["flag"] = "hang"
    agent, ledger, _ = runtime(ledger)
    task = asyncio.create_task(agent.run_turn(turn()))
    for _ in range(100):
        if ledger.writes:
            break
        await asyncio.sleep(0)
    assert ledger.writes[0][0] == "flag"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not agent.audit_lock.locked()
    assert any(effect.kind == "flag" and effect.state == "unknown" for effect in agent.receipts[("ep", 5)])
    assert agent.outcome("ep", 5).report_posted
    count = len(ledger.writes)
    response = await agent.run_turn(turn())
    assert not response.ok and len(ledger.writes) == count


async def test_total_timeout_is_bounded_and_retains_partial_summary(runtime):
    ledger = FakeLedger()
    ledger.read_block = asyncio.Event()
    agent, ledger, _ = runtime(ledger, timeout=11)
    started = time.monotonic()
    response = await agent.run_turn(turn())
    assert time.monotonic() - started < 1.3
    assert not response.ok and "Audit deadline reached" in response.summary
    assert not agent.outcome("ep", 5).report_posted


async def test_name_similarity_and_benford_are_not_mutation_authority(runtime):
    ledger = FakeLedger(
        vendors=[vendor(name="Same Name"), vendor("other", name="same name")],
        invoices=[invoice(f"benford_{i}", amount=4444) for i in range(20)],
    )
    agent, ledger, _ = runtime(ledger)
    result = await agent.run_turn(turn())
    assert result.ok and agent.outcome("ep", 5).flags_raised == 0
    assert [kind for kind, _, _ in ledger.writes] == ["report"]
