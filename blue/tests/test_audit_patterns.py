import pytest

from audit import evidence
from audit.agent import AUDIT_TOOL_IDS

from .audit_helpers import FakeLedger, invoice, turn, vendor


async def test_four_mock_patterns_and_no_newness_freeze(runtime):
    ledger = FakeLedger(
        vendors=[vendor(), vendor("ghost", created_day=5), vendor("split", created_day=5)],
        invoices=[
            invoice("paid", amount=1500, invoice_number="INV-1", po_id="po", status="paid", received_day=-20),
            invoice("dup", amount=1500.03, invoice_number="INV-1A", po_id="po"),
            invoice("ghost_inv", vendor_id="ghost", amount=4920),
            *[invoice(f"split_{i}", vendor_id="split", amount=4800) for i in range(3)],
        ],
        changes=[
            {
                "id": "bank_change",
                "episode_id": "ep",
                "vendor_id": "v",
                "field": "bank_account",
                "old_value": "old-private",
                "new_value": "new-private",
                "requested_day": 5,
                "status": "pending",
            }
        ],
    )
    agent, ledger, emitter = runtime(ledger)
    result = await agent.run_turn(turn())
    assert result.ok
    outcome = agent.outcome("ep", 5)
    assert outcome.flags_raised >= 5 and outcome.report_posted
    flag_reasons = [args[3] for kind, args, _ in ledger.writes if kind == "flag"]
    assert any("duplicates" in text for text in flag_reasons)
    assert any("three same-day" in text for text in flag_reasons)
    assert any("destination change" in text for text in flag_reasons)
    assert any("new vendor" in text for text in flag_reasons)
    assert not any(kind == "freeze" for kind, args, _ in ledger.writes if args[0] in {"ghost", "split"})
    # Every write ID is exactly the ID in the corresponding tool narration.
    event_ids = {invocation for _, _, invocation in emitter.calls}
    assert all(invocation in event_ids for _, _, invocation in ledger.writes)
    assert len(event_ids) == len(emitter.calls)
    assert len(emitter.calls) == len(emitter.results)
    markdown = next(args[1] for kind, args, _ in ledger.writes if kind == "report")
    assert len(markdown.split()) < 200
    assert all(section in markdown for section in ["Reviewed", "Flagged", "Needs a human tomorrow"])


async def test_benign_onboarding_subscriptions_rotations_po_variance(runtime):
    ledger = FakeLedger(
        vendors=[vendor(), vendor("new", created_day=5)],
        invoices=[
            invoice("small_new", vendor_id="new", amount=700),
            invoice("monthly_paid", invoice_number="SUB-1", amount=1200, status="paid", received_day=-20),
            invoice("monthly_now", invoice_number="SUB-2", amount=1200),
            invoice("po_new", vendor_id="new", amount=4800, po_id="new_po"),
        ],
        purchase_orders=[{"id": "new_po", "vendor_id": "new", "amount": 4500, "status": "open"}],
        changes=[
            {
                "id": "old_rotation",
                "vendor_id": "v",
                "field": "bank_account",
                "old_value": "old",
                "new_value": "new",
                "requested_day": -20,
                "status": "approved",
            }
        ],
    )
    agent, ledger, _ = runtime(ledger)
    assert (await agent.run_turn(turn())).ok
    assert agent.outcome("ep", 5).flags_raised == 0
    assert [kind for kind, _, _ in ledger.writes] == ["report"]


@pytest.mark.parametrize("received_day", [4, 5])
async def test_duplicate_received_earlier_and_paid_today_is_audited(runtime, received_day):
    ledger = FakeLedger(
        invoices=[
            invoice("original", invoice_number="DUP-1", status="paid", received_day=-20),
            invoice("duplicate", invoice_number="DUP-1", status="paid", received_day=received_day),
        ],
        payments=[{"id": "payment", "invoice_id": "duplicate", "amount": 1200, "paid_day": 5}],
    )
    snapshot = await evidence.collect_snapshot(ledger, "ep", 5)
    assert [(f.code, f.entity_id) for f in snapshot.findings] == [("duplicate_invoice", "duplicate")]
    agent, ledger, _ = runtime(ledger)
    assert (await agent.run_turn(turn())).ok
    assert agent.outcome("ep", 5).flags_raised == 1
    assert any(kind == "flag" and args[1] == "duplicate" for kind, args, _ in ledger.writes)


@pytest.mark.parametrize("received_day", [4, 5])
@pytest.mark.parametrize("status", ["pending", "paid"])
async def test_first_new_vendor_exposure_is_not_its_own_paid_history(runtime, received_day, status):
    ledger = FakeLedger(
        vendors=[vendor(created_day=4)],
        invoices=[invoice("first", amount=4920, received_day=received_day, status=status)],
        payments=[{"id": "payment", "invoice_id": "first", "amount": 4920, "paid_day": 5}] if status == "paid" else [],
    )
    snapshot = await evidence.collect_snapshot(ledger, "ep", 5)
    assert [f.code for f in snapshot.findings] == ["unverified_vendor_exposure"]
    agent, ledger, _ = runtime(ledger)
    assert (await agent.run_turn(turn())).ok
    assert agent.outcome("ep", 5).flags_raised == 1
    assert not any(kind == "freeze" for kind, _, _ in ledger.writes)


async def test_new_vendor_independent_earlier_payment_remains_history(runtime):
    ledger = FakeLedger(
        vendors=[vendor(created_day=3)],
        invoices=[
            invoice("history", amount=100, received_day=3, status="paid"),
            invoice("today", amount=4920, status="paid"),
        ],
        payments=[{"id": "payment", "invoice_id": "today", "amount": 4920, "paid_day": 5}],
    )
    snapshot = await evidence.collect_snapshot(ledger, "ep", 5)
    assert snapshot.findings == []
    agent, ledger, _ = runtime(ledger)
    assert (await agent.run_turn(turn())).ok
    assert agent.outcome("ep", 5).flags_raised == 0


async def test_live_path_stays_closed_before_sdk_stream(runtime, monkeypatch):
    from agentkit import DroidAgent

    entered = []

    async def forbidden(*args, **kwargs):
        entered.append(True)
        raise AssertionError("SDK stream must remain unreachable")

    monkeypatch.setattr(DroidAgent, "_droid_turn", forbidden)
    agent, ledger, emitter = runtime(dry_run=False)
    result = await agent.run_turn(turn())
    assert not result.ok and "Live audit unavailable" in result.summary
    assert "worker-thread Blue context" in result.summary and "invocation binding" in result.summary
    assert not entered and not ledger.writes and not emitter.calls
    assert agent._tool_ids == list(AUDIT_TOOL_IDS)  # A literal allowlist does not qualify live SDK use.
    assert (await agent.health())["droid_ok"] is False
