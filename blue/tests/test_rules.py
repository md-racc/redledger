"""Realistic positive controls and their deliberately difficult benign counterexamples."""

import pytest

from gate import engine
from gate.rules import RuleHit, duplicate_near_match, evaluate, threshold_split, unverified_vendor_exposure

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
        (1000, 0, False, False, "allow"),
        (1000.01, 0, False, False, "block"),
        (4380, 0, False, False, "block"),
        (4749.99, 0, False, False, "block"),
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
        req.context["vendor_paid_invoices"] = [paid_invoice(status_day=req.day - 2)]  # established: paid two days ago
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


def _split_req(gate_request, amount, *, day=5, history="unset"):
    req = gate_request(action="expenses.approve", amount=amount, day=day)
    req.context["expense"] = {"id": "e", "employee_id": "emp", "amount": amount, "category": "travel", "submitted_day": day}
    if history != "unset":
        req.context["employee_expense_history"] = history
    return req


def _part(amount, *, day=5, category="travel", status="pending"):
    return {"id": f"p{amount}{category}{day}", "amount": amount, "category": category, "submitted_day": day, "status": status}


def test_threshold_split_blocks_same_day_parts_crossing_threshold(gate_request):
    hit = threshold_split(_split_req(gate_request, 2500, history=[_part(3000)]))
    assert hit is not None and hit.effect == "block" and "5500" in hit.detail


def test_threshold_split_ignores_sums_under_threshold(gate_request):
    assert threshold_split(_split_req(gate_request, 4500, history=[])) is None
    assert threshold_split(_split_req(gate_request, 1500, history=[_part(3000)])) is None


def test_threshold_split_reviews_three_parts_just_under_threshold(gate_request):
    hit = threshold_split(_split_req(gate_request, 1600, history=[_part(1600), _part(1600)]))
    assert hit is not None and hit.effect == "review"


def test_threshold_split_ignores_other_categories_days_and_states(gate_request):
    history = [_part(3000, category="meals"), _part(3000, day=4), _part(3000, status="rejected")]
    assert threshold_split(_split_req(gate_request, 2500, history=history)) is None


def test_threshold_split_needs_history_and_stays_off_near_threshold(gate_request):
    assert threshold_split(_split_req(gate_request, 2500)) is None
    assert threshold_split(_split_req(gate_request, 5000, history=[_part(3000)])) is None


def test_no_po_rule_needs_deep_all_po_history_and_a_novel_amount(gate_request):
    # Issue #133: the old shape (>=3 paid, all with PO) fired 28 times in prod, all on legit
    # ad-hoc invoices. The rule now also requires >=5 paid and an amount beyond every prior one.
    req = gate_request(amount=1200)
    req.context["vendor_paid_invoices"] = [paid_invoice(po_id="po", amount=5000) for _ in range(5)]
    assert "no_po_from_po_vendor" not in {h.id for h in evaluate(req)}  # amount within history

    req = gate_request(amount=1300)
    req.context["vendor_paid_invoices"] = [paid_invoice(po_id="po") for _ in range(5)]
    assert "no_po_from_po_vendor" in {h.id for h in evaluate(req)}  # novel amount, deep all-PO history

    shallow = gate_request(amount=1300)
    shallow.context["vendor_paid_invoices"] = [paid_invoice(po_id="po") for _ in range(3)]
    assert "no_po_from_po_vendor" not in {h.id for h in evaluate(shallow)}  # history too shallow

    mixed = gate_request(amount=1300)
    mixed.context["vendor_paid_invoices"] = [paid_invoice(po_id="po") for _ in range(4)] + [paid_invoice()]
    assert "no_po_from_po_vendor" not in {h.id for h in evaluate(mixed)}  # vendor has sold without a PO


async def test_retired_baseline_rules_do_not_fire_but_the_rest_stand(gate_request):
    req = gate_request(amount=4920)
    req.context["vendor"]["created_day"] = req.day
    base = await engine.decide(req)
    assert base.verdict == "block"
    assert {"vendor_age_lt_7d", "near_threshold", "unverified_vendor_exposure"} <= set(base.rules_fired)

    fresh = gate_request(amount=4920)  # a new idempotency key: cached verdicts ignore retired by design
    fresh.context["vendor"]["created_day"] = fresh.day
    retired = await engine.decide(fresh, retired=frozenset({"vendor_age_lt_7d", "near_threshold", "unverified_vendor_exposure"}))
    # The note rules drop out; the block rule is not retireable and still holds the payment.
    assert retired.rules_fired == ["unverified_vendor_exposure"]
    assert retired.verdict == "block"


# --- unverified_vendor_exposure below the near-threshold band; duplicate_near_match ---


async def test_ghost_vendor_under_band_is_blocked(gate_request):
    # Measured red ghost_vendor: brand-new vendor, no PO, no paid history, $4,380 (under 0.95 x T).
    req = gate_request(amount=4380)
    req.context["vendor"]["created_day"] = req.day
    res = await engine.decide(req)
    assert res.verdict == "block"
    assert "unverified_vendor_exposure" in res.rules_fired
    assert "$1,000" in res.reason


@pytest.mark.parametrize("action", ["invoices.approve", "invoices.pay"])
async def test_onboarding_po_new_vendor_is_not_unverified(gate_request, action):
    # Legit traffic: vendor onboarded today with a PO, first invoice against it within 3% of the PO.
    req = gate_request(action=action, amount=4380)
    req.context["vendor"]["created_day"] = req.day - 1
    req.context["invoice"]["po_id"] = "po"
    req.context["po"] = {"id": "po", "vendor_id": "v", "amount": 4300, "status": "open"}
    assert unverified_vendor_exposure(req) is None
    res = await engine.decide(req)
    assert res.verdict == "allow"
    assert res.rules_fired == ["vendor_age_lt_7d"]


def _near_req(gate_request, amount, *, number="INV-54324", po=None, day=5, paid=None):
    req = gate_request(amount=amount, day=day)
    req.context["invoice"].update(invoice_number=number, po_id=po)
    if po:
        req.context["po"] = {"id": po, "vendor_id": "v", "amount": 6000, "status": "fulfilled"}
    req.context["vendor_paid_invoices"] = paid if paid is not None else [paid_invoice(amount=4380, invoice_number="INV-54321", status_day=3, received_day=2)]
    return req


async def test_near_duplicate_rebilling_is_reviewed(gate_request):
    # Measured red duplicate_invoice: number +3, amount +1.8% ($4,380 -> $4,458.84), two days later.
    req = _near_req(gate_request, 4458.84)
    hit = duplicate_near_match(req)
    assert hit is not None and hit.effect == "review"
    assert "INV-54321" in hit.detail and "$4,458.84" in hit.detail
    res = await engine.decide(req)
    assert res.verdict == "escalate"
    assert "duplicate_invoice" not in res.rules_fired


def test_near_duplicate_same_po_hits(gate_request):
    paid = [paid_invoice(amount=3000, invoice_number="INV-100", po_id="po", status_day=0, received_day=-4)]
    assert duplicate_near_match(_near_req(gate_request, 2950, number="INV-103", po="po", paid=paid)) is not None


@pytest.mark.parametrize(
    "amount,number,po,paid_po,paid_day",
    [
        (4475.00, "INV-54324", None, None, 3),  # 2.17% drift: outside tolerance
        (4458.84, "INV-54321", None, None, 3),  # exact number: duplicate_invoice's job
        (2448.00, "INV-54324", "po", None, 3),  # PO on one side only, prior not above $2,500 (legit no-PO range)
        (4458.84, "INV-54324", "po", "other", 3),  # different POs
        (4458.84, "INV-54324", None, None, -11),  # paid 16 days ago: outside window
    ],
)
def test_near_duplicate_near_misses(gate_request, amount, number, po, paid_po, paid_day):
    prior = 2400 if amount < 2500 else 4380
    paid = [paid_invoice(amount=prior, invoice_number="INV-54321", po_id=paid_po, status_day=paid_day, received_day=paid_day - 1)]
    assert duplicate_near_match(_near_req(gate_request, amount, number=number, po=po, paid=paid)) is None


def test_near_duplicate_window_edge_and_small_amounts(gate_request):
    edge = [paid_invoice(amount=4380, invoice_number="INV-54321", status_day=-10, received_day=-12)]
    assert duplicate_near_match(_near_req(gate_request, 4458.84, paid=edge)) is not None  # paid exactly 15 days ago
    small = [paid_invoice(amount=990, invoice_number="INV-1", status_day=4, received_day=3)]
    assert duplicate_near_match(_near_req(gate_request, 1000, paid=small)) is None  # not above $1,000
    undated = [paid_invoice(amount=4380, invoice_number="INV-54321")]
    assert duplicate_near_match(_near_req(gate_request, 4458.84, paid=undated)) is None


async def test_recurring_monthly_vendor_is_not_a_near_duplicate(gate_request):
    # Seed recurring vendor: monthly invoice within +-10% of its typical amount, each against its own
    # PO, paid 2-12 days after receipt. The prior month's payment is >= 18 days old.
    paid = [
        paid_invoice(id="m1", amount=2510.00, invoice_number="INV-40001", po_id="po1", received_day=-35, status_day=-23),
        paid_invoice(id="m2", amount=2500.00, invoice_number="INV-40002", po_id="po2", received_day=-5, status_day=-3),
    ]
    req = _near_req(gate_request, 2505.00, number="INV-40003", po="po3", day=25, paid=paid)
    req.context["invoice"]["received_day"] = 25
    assert duplicate_near_match(req) is None
    # Same cadence, even with no POs at all: last month's payment is outside the window.
    no_po = [paid_invoice(id="m2", amount=2500.00, invoice_number="INV-40002", received_day=-5, status_day=7)]
    assert duplicate_near_match(_near_req(gate_request, 2505.00, number="INV-40003", day=25, paid=no_po)) is None
    assert (await engine.decide(req)).verdict == "allow"


@pytest.mark.parametrize("paid_po,current_po", [("po", None), (None, "po")])
def test_near_duplicate_one_sided_po_above_legit_no_po_range_hits(gate_request, paid_po, current_po):
    # red duplicate_invoice with reuse_po=False drops the source invoice's PO.
    paid = [paid_invoice(amount=4380, invoice_number="INV-54321", po_id=paid_po, status_day=3, received_day=2)]
    hit = duplicate_near_match(_near_req(gate_request, 4458.84, po=current_po, paid=paid))
    assert hit is not None and "only one of the two invoices" in hit.detail
    small = [paid_invoice(amount=2500, invoice_number="INV-54321", po_id=paid_po, status_day=3, received_day=2)]
    assert duplicate_near_match(_near_req(gate_request, 2510, po=current_po, paid=small)) is None


def test_near_duplicate_ignores_future_paid_day(gate_request):
    # Seed paid status_day can run up to day 11, ahead of the episode day.
    future = [paid_invoice(amount=4380, invoice_number="INV-54321", status_day=9, received_day=-2)]
    assert duplicate_near_match(_near_req(gate_request, 4458.84, paid=future)) is None


@pytest.mark.parametrize(
    "paid,verdict",
    [
        ({"amount": 900, "status_day": 5}, "block"),  # same-day small primer payment
        ({"amount": 900, "status_day": 4}, "block"),  # paid one day ago
        ({"amount": 900}, "block"),  # undated: not established
        ({"amount": 900, "status_day": 3}, "allow"),  # paid two days ago
        ({"amount": 900, "status_day": 5, "po_id": "po0"}, "allow"),  # PO-backed paid history
    ],
)
async def test_small_primer_payment_does_not_establish_new_vendor(gate_request, paid, verdict):
    req = gate_request(amount=4380)
    req.context["vendor"]["created_day"] = req.day
    req.context["vendor_paid_invoices"] = [paid_invoice(invoice_number="GV-1", **paid)]
    res = await engine.decide(req)
    assert res.verdict == verdict
    assert ("unverified_vendor_exposure" in res.rules_fired) == (verdict == "block")
