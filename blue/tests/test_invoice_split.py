"""Invoice threshold splitting: one vendor bill cut into near-same-day parts under the approval line."""

import pytest

from gate import engine
from gate.rules import RETIREABLE_RULE_IDS, RULES, evaluate, invoice_threshold_split

from .conftest import paid_invoice


def _open(amount, *, id=None, day=5, status="pending", vendor_id="v", po_id=None, **extra):
    row = {
        "id": id or f"o{amount}{day}{status}{vendor_id}",
        "episode_id": "ep",
        "vendor_id": vendor_id,
        "amount": amount,
        "invoice_number": f"INV-{id or amount}",
        "po_id": po_id,
        "received_day": day,
        "status": status,
    }
    return row | extra


def _paid(amount, *, id=None, day=5, **extra):
    return paid_invoice(id=id or f"p{amount}{day}", invoice_number=f"PD-{id or amount}", amount=amount, received_day=day) | extra


def _req(gate_request, amount, *, action="invoices.approve", open_rows=(), paid_rows=()):
    req = gate_request(action=action, amount=amount)
    req.context["vendor_open_invoices"] = list(open_rows)
    req.context["vendor_paid_invoices"] = list(paid_rows)
    return req


@pytest.mark.parametrize("action", ["invoices.approve", "invoices.pay"])
def test_three_part_split_blocks_on_first_part_with_siblings_pending(gate_request, action):
    req = _req(gate_request, 1700, action=action, open_rows=[_open(1800), _open(1650)])
    hit = invoice_threshold_split(req)
    assert hit is not None and hit.effect == "block" and hit.family == "amount"
    assert "3 invoices" in hit.detail and "5150" in hit.detail and "5000" in hit.detail


def test_three_part_split_blocks_on_a_later_part_with_some_siblings_paid(gate_request):
    req = _req(gate_request, 1650, action="invoices.pay", open_rows=[_open(1800, day=4)], paid_rows=[_paid(1700, day=4)])
    hit = invoice_threshold_split(req)
    assert hit is not None and hit.effect == "block" and "3 invoices" in hit.detail


def test_single_invoice_and_other_vendors_are_ignored(gate_request):
    assert invoice_threshold_split(_req(gate_request, 4900)) is None
    other = [_open(3000, vendor_id="other"), _paid(3000) | {"vendor_id": "other"}]
    assert invoice_threshold_split(_req(gate_request, 2500, open_rows=other[:1])) is None
    assert invoice_threshold_split(_req(gate_request, 2500, open_rows=other)) is None


def test_sum_under_threshold_is_ignored_and_review_band_works(gate_request):
    assert invoice_threshold_split(_req(gate_request, 1500, open_rows=[_open(3000)])) is None
    # Two parts just under the line are not a review: the band needs three or more parts.
    assert invoice_threshold_split(_req(gate_request, 2400, open_rows=[_open(2450)])) is None
    hit = invoice_threshold_split(_req(gate_request, 1600, open_rows=[_open(1600), _open(1610)]))
    assert hit is not None and hit.effect == "review" and hit.severity == 2


def test_current_invoice_at_or_over_threshold_is_not_a_split(gate_request):
    assert invoice_threshold_split(_req(gate_request, 5000, open_rows=[_open(3000)])) is None
    # A sibling already at the threshold went through approval on its own; it is not a split part.
    assert invoice_threshold_split(_req(gate_request, 2500, open_rows=[_open(5000)])) is None


def test_rejected_siblings_are_ignored(gate_request):
    assert invoice_threshold_split(_req(gate_request, 2500, open_rows=[_open(3000, status="rejected")])) is None


@pytest.mark.parametrize("action", ["invoices.approve", "invoices.pay"])
def test_last_part_is_blocked_when_earlier_parts_were_already_blocked(gate_request, action):
    # Parts 1 and 2 were blocked; part 3 judged alone would be paid. Blocked parts still count.
    req = _req(gate_request, 1650, action=action, open_rows=[_open(1800, status="blocked"), _open(1700, status="blocked", day=4)])
    hit = invoice_threshold_split(req)
    assert hit is not None and hit.effect == "block" and "3 invoices" in hit.detail and "5150" in hit.detail


def test_window_is_same_or_adjacent_received_day(gate_request):
    assert invoice_threshold_split(_req(gate_request, 2500, open_rows=[_open(3000, day=6)])) is not None
    assert invoice_threshold_split(_req(gate_request, 2500, open_rows=[_open(3000, day=3)])) is None
    assert invoice_threshold_split(_req(gate_request, 2500, paid_rows=[_paid(3000, day=7)])) is None


def test_current_invoice_and_repeated_rows_are_not_double_counted(gate_request):
    me = _open(2500, id="i", status="approved")  # the judged invoice echoed back in a list
    assert invoice_threshold_split(_req(gate_request, 2500, open_rows=[me])) is None
    twice = _open(1300, id="dup")
    assert invoice_threshold_split(_req(gate_request, 2500, open_rows=[twice, twice], paid_rows=[me])) is None


def test_separately_po_backed_invoices_are_not_parts_but_a_shared_po_is(gate_request):
    req = _req(gate_request, 2500, open_rows=[_open(3000, po_id="po-2")])
    req.context["invoice"]["po_id"] = "po-1"
    req.context["po"] = {"id": "po-1", "vendor_id": "v", "amount": 2500, "status": "open"}
    assert invoice_threshold_split(req) is None
    assert invoice_threshold_split(_req(gate_request, 2500, open_rows=[_open(3000, po_id="po-2")])) is None

    shared = _req(gate_request, 2500, open_rows=[_open(3000, po_id="po-1")])
    shared.context["invoice"]["po_id"] = "po-1"
    shared.context["po"] = {"id": "po-1", "vendor_id": "v", "amount": 6000, "status": "open"}
    assert invoice_threshold_split(shared) is not None


@pytest.mark.parametrize(
    "bad",
    [
        "not a row",
        None,
        {"id": "x", "vendor_id": "v", "amount": 3000, "status": "pending"},  # no received_day
        _open(3000) | {"received_day": "5"},
        _open(3000) | {"received_day": True},
        _open(3000) | {"amount": "lots"},
        _open(3000) | {"amount": float("nan")},
        _open(3000) | {"amount": -3000},
        _open(3000) | {"episode_id": "other"},
        _open(3000) | {"id": ""},
        _open(3000) | {"vendor_id": None},
        _open(3000) | {"po_id": 7},
        _open(3000) | {"status": ["pending"]},
        _open(3000) | {"status": {"pending": True}},
        _open(3000) | {"vendor_id": ["v"]},
        _open(3000) | {"id": {"x": 1}},
        _open(3000) | {"received_day": [5]},
        _open(3000) | {"amount": {"value": 3000}},
    ],
)
def test_malformed_sibling_rows_are_ignored_without_raising(gate_request, bad):
    req = _req(gate_request, 2500, open_rows=[bad])
    assert invoice_threshold_split(req) is None
    assert {h.id for h in evaluate(req)} == set()


@pytest.mark.parametrize("value", [None, "garbage", {"rows": []}])
def test_missing_or_malformed_open_list_does_not_fail_closed(gate_request, value):
    req = _req(gate_request, 2500, paid_rows=[_paid(3000)])
    req.context["vendor_open_invoices"] = value
    assert [h.id for h in evaluate(req)] == ["invoice_threshold_split"]


def test_other_actions_are_ignored(gate_request):
    req = _req(gate_request, 2500, action="invoices.match", open_rows=[_open(3000)])
    assert invoice_threshold_split(req) is None


async def test_engine_blocks_invoice_split(gate_request):
    req = _req(gate_request, 1700, action="invoices.pay", open_rows=[_open(1800)], paid_rows=[_paid(1650, day=4)])
    result = await engine.decide(req)
    assert result.verdict == "block"
    assert "invoice_threshold_split" in result.rules_fired


async def test_engine_split_block_survives_retirement(gate_request):
    req = _req(gate_request, 1700, open_rows=[_open(1800), _open(1650)])
    result = await engine.decide(req, retired=frozenset(RETIREABLE_RULE_IDS | {"invoice_threshold_split"}))
    assert result.verdict == "block"


def test_rule_is_registered_and_not_retireable():
    assert invoice_threshold_split in RULES
    assert "invoice_threshold_split" not in RETIREABLE_RULE_IDS
