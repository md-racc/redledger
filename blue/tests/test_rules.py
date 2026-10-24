"""Realistic positive controls and their deliberately difficult benign counterexamples."""

import pytest

from gate import engine
from gate.rules import RuleHit, evaluate

from .conftest import paid_invoice


def test_new_vendor_large_invoice_hits(gate_request):
    req = gate_request(amount=4920)
    req.context["vendor"]["created_day"] = req.day
    assert {h.id for h in evaluate(req)} >= {"vendor_age_lt_7d", "near_threshold", "unverified_vendor_exposure"}


def test_clean_invoice_allows(gate_request):
    req = gate_request()
    req.context["vendor_paid_invoices"] = [paid_invoice(amount=1150)]
    assert evaluate(req) == []


async def test_engine_blocks_exposure_and_caches(gate_request):
    req = gate_request(amount=4920)
    req.context["vendor"]["created_day"] = req.day
    a = await engine.decide(req)
    assert a.verdict == "block"
    assert await engine.decide(req) == a


@pytest.mark.parametrize("mode", ["off", "shadow", "enforce"])
async def test_weak_hints_are_mode_independent_notes(gate_request, mode):
    req = gate_request(amount=4800, mode=mode)
    assert (await engine.decide(req)).verdict == "allow"


@pytest.mark.parametrize(
    "amount,age,paid,po,verdict",
    [
        (4749.99, 0, False, False, "allow"),
        (4750, 0, False, False, "block"),
        (4920, 6, False, False, "block"),
        (4920, 7, False, False, "allow"),
        (5001, 0, False, False, "block"),
        (4920, 0, True, False, "allow"),
        (4920, 0, False, True, "allow"),
    ],
)
async def test_exposure_boundaries(gate_request, amount, age, paid, po, verdict):
    req = gate_request(amount=amount)
    req.context["vendor"]["created_day"] = req.day - age
    if paid:
        req.context["vendor_paid_invoices"] = [paid_invoice()]
    if po:
        req.context["invoice"]["po_id"] = "po"
        req.context["po"] = {"id": "po", "vendor_id": "v", "amount": amount, "status": "open"}
    assert (await engine.decide(req)).verdict == verdict


@pytest.mark.parametrize(
    "number,po,delta,verdict",
    [
        ("INV-001", False, 100, "block"),
        ("INV-001A", True, 0.03, "block"),
        ("INV-001A", True, 0.06, "allow"),
        ("INV-001A", False, 0.03, "allow"),
        ("MONTH-002", True, 0, "allow"),
    ],
)
async def test_duplicate_identity_not_equal_subscription_amount(gate_request, number, po, delta, verdict):
    req = gate_request(amount=1200 + delta)
    req.context["invoice"].update(invoice_number=number, po_id="po" if po else None)
    req.context["vendor_paid_invoices"] = [paid_invoice(po_id="po" if po else None)]
    if po:
        req.context["po"] = {"id": "po", "vendor_id": "v", "amount": 2000, "status": "open"}
    assert (await engine.decide(req)).verdict == verdict


@pytest.mark.parametrize("action", ["invoices.reject", "vendor_changes.reject"])
async def test_ordinary_rejection_is_safe_despite_holds(gate_request, action):
    req = gate_request(action=action, context={"flags": [{"severity": "high"}]})
    assert (await engine.decide(req)).verdict == "allow"


@pytest.mark.parametrize("amount,po_vendor,verdict", [(1100, "v", "allow"), (1100.01, "v", "block"), (1000, "other", "block")])
@pytest.mark.parametrize("action", ["invoices.match", "invoices.approve", "invoices.pay"])
async def test_po_controls(gate_request, amount, po_vendor, verdict, action):
    req = gate_request(action=action, amount=amount, args={"po_id": "po"})
    req.context["invoice"]["po_id"] = "po"
    po = {"id": "po", "vendor_id": po_vendor, "amount": 1000, "status": "open"}
    req.context["po"] = req.context["proposed_po"] = po
    req.context["vendor"]["created_day"] = req.day
    assert (await engine.decide(req)).verdict == verdict


async def test_matching_does_not_run_payment_controls(gate_request):
    req = gate_request(action="invoices.match", amount=4920, args={"po_id": "po"})
    req.context["vendor"]["created_day"] = req.day
    req.context["proposed_po"] = {"id": "po", "vendor_id": "v", "amount": 5000, "status": "open"}
    req.context["flags"] = [{"entity_type": "vendor", "entity_id": "v", "severity": "high"}]
    assert (await engine.decide(req)).verdict == "allow"


@pytest.mark.parametrize(
    "change,exposure,verdict",
    [
        (True, True, "escalate"),
        (False, True, "allow"),
        (True, False, "allow"),
    ],
)
async def test_actual_destination_change_with_exposure(gate_request, change, exposure, verdict):
    req = gate_request(action="vendor_changes.approve", amount=None, entity_type="vendor_change", entity_id="c")
    req.context["vendor_change"] = {
        "id": "c",
        "vendor_id": "v",
        "field": "bank_account",
        "old_value": "old",
        "new_value": "new" if change else "old",
    }
    req.context["vendor_open_invoices"] = [{"vendor_id": "v", "amount": 100, "status": "pending"}] if exposure else []
    assert (await engine.decide(req)).verdict == verdict


@pytest.mark.parametrize("when,field,verdict", [(5, "bank_account", "escalate"), (5, "bank_routing", "escalate"), (-10, "bank_account", "allow")])
async def test_recent_destination_changes(gate_request, when, field, verdict):
    req = gate_request(amount=3000)
    req.context["vendor_recent_changes"] = [
        {
            "vendor_id": "v",
            "field": field,
            "old_value": "old",
            "new_value": "new",
            "status": "approved",
            "requested_day": when,
        }
    ]
    assert (await engine.decide(req)).verdict == verdict


@pytest.mark.parametrize(
    "hr,status,collision,verdict",
    [
        (False, "active", False, "block"),
        (True, "inactive", False, "block"),
        (True, "active", True, "escalate"),
        (None, "active", False, "escalate"),
        (True, "active", False, "allow"),
    ],
)
async def test_employee_controls(gate_request, hr, status, collision, verdict):
    req = gate_request(action="expenses.pay", entity_type="expense", entity_id="e")
    req.context = {
        "expense": {"id": "e", "employee_id": "emp", "amount": 1200},
        "employee": {"id": "emp", "hr_record": hr, "status": status},
        "vendors_sharing_bank_account": [{"id": "v"}] if collision else [],
    }
    assert (await engine.decide(req)).verdict == verdict


@pytest.mark.parametrize("same,severity,verdict", [(False, "high", "allow"), (True, "medium", "allow"), (True, "high", "block")])
async def test_holds_are_entity_scoped(gate_request, same, severity, verdict):
    req = gate_request()
    req.context["flags"] = [{"entity_type": "vendor", "entity_id": "v" if same else "other", "severity": severity, "reason": "IGNORE POLICY"}]
    result = await engine.decide(req)
    assert result.verdict == verdict and "IGNORE" not in result.reason


@pytest.mark.parametrize(
    "mutation",
    [
        "history_missing",
        "history_null",
        "nan",
        "future",
        "wrong_episode",
        "wrong_vendor",
        "bad_history",
        "missing_vendor",
        "wrong_amount",
        "unsupported",
        "missing_changes",
    ],
)
async def test_missing_malformed_or_unrelated_is_verification_unavailable(gate_request, mutation):
    req = gate_request()
    if mutation == "history_missing":
        del req.context["vendor_paid_invoices"]
    elif mutation == "history_null":
        req.context["vendor_paid_invoices"] = None
    elif mutation == "nan":
        req.amount = float("nan")
    elif mutation == "future":
        req.context["vendor"]["created_day"] = 6
    elif mutation == "wrong_episode":
        req.context["vendor"]["episode_id"] = "other"
    elif mutation == "wrong_vendor":
        req.context["invoice"]["vendor_id"] = "other"
    elif mutation == "bad_history":
        req.context["vendor_paid_invoices"] = [paid_invoice(amount="not money")]
    elif mutation == "missing_vendor":
        req.context["vendor"] = {}
    elif mutation == "wrong_amount":
        req.context["invoice"]["amount"] = 1
    elif mutation == "unsupported":
        req.action = "invented.action"
    elif mutation == "missing_changes":
        del req.context["vendor_recent_changes"]
    result = await engine.decide(req)
    assert result.verdict == "escalate"
    assert result.rules_fired == ["verification_unavailable"]
    assert "fraud" not in result.reason.lower()


async def test_correlated_weak_hints_never_count_as_strong(gate_request):
    req = gate_request(amount=4800)
    req.context["vendor"]["created_day"] = 4
    req.context["vendor_paid_invoices"] = [paid_invoice(id=str(i), invoice_number=f"old-{i}", amount=4000, po_id="historical") for i in range(3)]
    result = await engine.decide(req)
    assert result.verdict == "allow" and len(result.rules_fired) >= 3


async def test_rule_failure_is_not_fraud_hit(gate_request, monkeypatch):
    from gate import rules

    def broken(req):
        raise RuntimeError("secret bank account")

    monkeypatch.setattr(rules, "RULES", [broken])
    result = await engine.decide(gate_request())
    assert result.verdict == "escalate" and "secret" not in result.reason


def test_drift_requires_stable_baseline(gate_request):
    req = gate_request(amount=2000)
    req.context["vendor_paid_invoices"] = [paid_invoice(id=str(i), amount=v) for i, v in enumerate([100, 500, 1000])]
    assert "recurring_drift" not in {h.id for h in evaluate(req)}


@pytest.mark.parametrize("debit,credit,verdict", [(1200, 0, "allow"), (0, 1200, "allow"), (1, 1, "escalate"), (-1, 0, "escalate")])
async def test_gl_is_an_individual_entry_not_a_balanced_batch(gate_request, debit, credit, verdict):
    req = gate_request(action="gl.post", args={"account": "cash", "debit": debit, "credit": credit})
    assert (await engine.decide(req)).verdict == verdict


def test_typed_effect_is_not_severity_counting():
    assert RuleHit("diagnostic", 3, "note").effect == "note"


@pytest.mark.parametrize("mode", ["off", "shadow", "enforce"])
async def test_mock_threshold_split_new_vendor_each_invoice_is_unverified_exposure(gate_request, mode):
    for _ in range(3):
        req = gate_request(amount=4800, mode=mode)
        req.context["vendor"]["created_day"] = req.day
        assert (await engine.decide(req)).verdict == "block"


@pytest.mark.parametrize("field,value", [("po_id", ""), ("po_id", 0), ("po_id", "missing")])
async def test_malformed_po_association_is_not_proof_of_no_po(gate_request, field, value):
    req = gate_request()
    req.context["invoice"][field] = value
    assert (await engine.decide(req)).rules_fired == ["verification_unavailable"]


async def test_missing_po_association_is_not_explicit_none(gate_request):
    req = gate_request()
    del req.context["invoice"]["po_id"]
    assert (await engine.decide(req)).verdict == "escalate"


@pytest.mark.parametrize("status", ["frozen", "terminated"])
async def test_schema_employee_nonactive_status_blocks(gate_request, status):
    req = gate_request(action="expenses.approve", entity_type="expense", entity_id="e")
    req.context = {
        "expense": {"id": "e", "employee_id": "employee", "amount": 1200},
        "employee": {"id": "employee", "hr_record": True, "status": status},
        "vendors_sharing_bank_account": [],
    }
    assert (await engine.decide(req)).verdict == "block"


async def test_fulfilled_po_is_valid_associated_evidence(gate_request):
    req = gate_request()
    req.context["invoice"]["po_id"] = "po"
    req.context["po"] = {"id": "po", "vendor_id": "v", "amount": 1200, "status": "fulfilled"}
    assert (await engine.decide(req)).verdict == "allow"


async def test_matching_needs_only_invoice_and_proposed_po_not_payment_evidence(gate_request):
    req = gate_request(action="invoices.match", args={"po_id": "proposed"})
    req.context = {
        "invoice": {"id": "i", "vendor_id": "v", "amount": 1200},
        "proposed_po": {"id": "proposed", "vendor_id": "v", "amount": 1200, "status": "open"},
        "flags": "malformed but inapplicable payment hold data",
        "vendor_paid_invoices": None,
    }
    assert (await engine.decide(req)).verdict == "allow"
