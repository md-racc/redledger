import json

import pytest

from audit import tools

from .audit_helpers import FakeLedger, bound_session, invoice, vendor


async def test_snapshot_reuse_and_arbitrary_writes_refused():
    ledger = FakeLedger(vendors=[vendor(created_day=5)], invoices=[invoice(amount=4920)])
    async with bound_session(ledger) as (session, emitter):
        first_reads = dict(ledger.read_counts)
        await tools.dispatch("day_activity")
        await tools.dispatch("vendor_dedupe")
        await tools.dispatch("benford_check")
        refused = await tools.dispatch("raise_flag", finding_id="invented")
        assert refused["ok"] is False
        assert ledger.read_counts == first_reads and not ledger.writes
        assert len(emitter.calls) == len(emitter.results) == 4


async def test_freeze_requires_independent_substantive_families_and_fresh_read():
    ledger = FakeLedger(
        vendors=[vendor(bank_account="shared"), vendor("other", bank_account="shared")],
        invoices=[
            invoice("paid", invoice_number="N", status="paid", received_day=-20),
            invoice("duplicate", invoice_number="N"),
        ],
    )
    async with bound_session(ledger) as (session, _):
        findings = [f for f in session.snapshot.findings if f.vendor_id == "v"]
        assert tools.freeze_authorized(findings)
        result = await tools.dispatch("freeze_vendor", vendor_id="v", finding_ids=[f.id for f in findings])
        assert result["ok"] and ledger.read_counts["fresh_vendor"] == 1
        assert len(ledger.writes) == 1 and ledger.writes[0][0] == "freeze"
        assert (await tools.dispatch("freeze_vendor", vendor_id="v", finding_ids=[f.id for f in findings]))["replayed"]
        assert len(ledger.writes) == 1
    ledger.writes.clear()
    ledger.fresh_override = vendor(bank_account="changed")
    async with bound_session(ledger) as (session, _):
        findings = [f for f in session.snapshot.findings if f.vendor_id == "v"]
        assert not (await tools.dispatch("freeze_vendor", vendor_id="v", finding_ids=[f.id for f in findings]))["ok"]
        assert not ledger.writes


async def test_newness_threshold_split_and_collision_without_integrity_never_freeze():
    ledger = FakeLedger(
        vendors=[vendor(created_day=5), vendor("other", bank_account="private-account-v")],
        invoices=[invoice(f"split_{i}", amount=4800) for i in range(3)],
    )
    async with bound_session(ledger) as (session, _):
        findings = [f for f in session.snapshot.findings if f.vendor_id == "v"]
        assert len(findings) >= 3 and not tools.freeze_authorized(findings)
        assert not (await tools.dispatch("freeze_vendor", vendor_id="v", finding_ids=[f.id for f in findings]))["ok"]
        assert not ledger.writes


async def test_live_missing_invocation_metadata_fails_closed():
    ledger = FakeLedger(vendors=[vendor(created_day=5)], invoices=[invoice(amount=4920)])
    async with bound_session(ledger, dry_run=False) as (session, _):
        result = json.loads(await tools.raise_flag(session.snapshot.findings[0].id))
        assert not result["ok"] and not ledger.writes
        with pytest.raises(ValueError):
            await tools.dispatch("post_report")


async def test_tool_signatures_return_json_text_and_hide_invocation_parameters():
    import inspect

    ledger = FakeLedger()
    async with bound_session(ledger):
        for fn in [tools.day_activity, tools.vendor_dedupe, tools.benford_check, tools.raise_flag, tools.freeze_vendor, tools.post_report]:
            signature = inspect.signature(fn)
            assert signature.return_annotation is str
            assert not any("invocation" in name or "tool_use_id" in name for name in signature.parameters)
        result = await tools.day_activity()
        assert isinstance(result, str) and json.loads(result)["ok"] is False
