"""Enforce-mode gap from the same-seed off/enforce review: ghost vendors billing under the old floor,
and the audit's same-day split finding staying medium (a high flag lands on the impersonated real
vendor, and already_flagged_high would then block its later legit invoices)."""

import pytest

from audit import evidence
from gate import engine
from gate.rules import UNVERIFIED_EXPOSURE_FLOOR

from .audit_helpers import FakeLedger, invoice, vendor
from .conftest import paid_invoice


def _ghost(gate_request, amount, action="invoices.pay"):
    req = gate_request(action=action, amount=amount)
    req.context["vendor"]["created_day"] = req.day
    return req


@pytest.mark.parametrize("amount", [500, 950, 2400, 4380])
@pytest.mark.parametrize("action", ["invoices.approve", "invoices.pay"])
async def test_ghost_vendor_amounts_are_held(gate_request, amount, action):
    # red's ghost_vendor range starts at $500; $4,380 is its default and $950/$2,400 the mock evasion rungs
    response = await engine.decide(_ghost(gate_request, amount, action))
    assert response.verdict == "block"
    assert "unverified_vendor_exposure" in response.rules_fired


def test_floor_is_ghost_vendor_minimum():
    assert UNVERIFIED_EXPOSURE_FLOOR == 500


async def test_legit_new_vendor_first_invoice_with_po_is_not_held(gate_request):
    # legit onboarding: brand-new vendor, first invoice against its onboarding PO
    req = _ghost(gate_request, 4380)
    req.context["invoice"]["po_id"] = "po"
    req.context["po"] = {"id": "po", "episode_id": "ep", "vendor_id": "v", "amount": 4400, "status": "open"}
    response = await engine.decide(req)
    assert "unverified_vendor_exposure" not in response.rules_fired
    assert response.verdict == "allow"


async def test_established_no_po_vendor_is_not_held(gate_request):
    req = gate_request(amount=2400)
    req.context["vendor"]["created_day"] = req.day - 30
    req.context["vendor_paid_invoices"] = [paid_invoice(amount=2300)]
    assert (await engine.decide(req)).verdict == "allow"


async def test_same_day_split_finding_stays_medium_severity():
    ledger = FakeLedger(
        vendors=[vendor(), vendor("split", created_day=-40)],
        invoices=[invoice(f"split_{i}", vendor_id="split", amount=4800 + i) for i in range(3)],
    )
    snapshot = await evidence.collect_snapshot(ledger, "ep", 5)
    split = [f for f in snapshot.findings if f.code == "same_day_split"]
    assert split and all(f.severity == "medium" for f in split)


async def test_same_day_po_backed_invoices_are_not_a_split():
    ledger = FakeLedger(
        vendors=[vendor()],
        invoices=[invoice(f"po_{i}", amount=4800 + i, po_id=f"po{i}") for i in range(3)],
    )
    snapshot = await evidence.collect_snapshot(ledger, "ep", 5)
    assert not any(f.code == "same_day_split" for f in snapshot.findings)
