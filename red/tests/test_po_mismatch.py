"""Owner: Dev Al. po_mismatch scheme against a respx-mocked Ledger API. Spec: SCHEMES-SPEC.md §5.2, §7."""

import json

import httpx
import pytest
import respx

from agentkit import AgentSettings, LedgerClient
from schemes.po_mismatch import PoMismatch

S = AgentSettings(AGENT_NAME="red", BATTLEFIELD_URL="http://bf", INTERNAL_TOKEN="t")

VENDORS = [
    {
        "id": "ven_1",
        "name": "Harbor Logistics",
        "bank_account": "7777",
        "bank_routing": "021000021",
        "category": "logistics",
        "created_day": -300,
        "status": "active",
        "created_by": "seed",
    },
    {
        "id": "ven_2",
        "name": "Bay Facilities",
        "bank_account": "8888",
        "bank_routing": "021000021",
        "category": "facilities",
        "created_day": -250,
        "status": "frozen",
        "created_by": "seed",
    },
]
POS = [
    {"id": "po_1", "vendor_id": "ven_1", "amount": 3000.0, "description": "Q3 freight", "created_day": -5, "status": "open"},
    {"id": "po_2", "vendor_id": "ven_1", "amount": 1200.0, "description": "pallets", "created_day": -9, "status": "open"},  # already invoiced below
    {"id": "po_3", "vendor_id": "ven_2", "amount": 2500.0, "description": "HVAC service", "created_day": -4, "status": "open"},  # vendor frozen
]
INVOICES = [
    {
        "id": "inv_1",
        "vendor_id": "ven_1",
        "po_id": "po_2",
        "amount": 1200.0,
        "invoice_number": "HL-2201",
        "line_items": [],
        "received_day": -8,
        "due_day": 22,
        "status": "paid",
        "status_day": -2,
    },
]


def _mock_books(vendors=VENDORS, pos=POS, invoices=INVOICES):
    respx.get("http://bf/api/vendors").mock(return_value=httpx.Response(200, json=vendors))
    respx.get("http://bf/api/purchase_orders").mock(return_value=httpx.Response(200, json=pos))
    respx.get("http://bf/api/invoices").mock(return_value=httpx.Response(200, json=invoices))


def test_catalog_shape():
    c = PoMismatch().catalog()
    assert c.id == "po_mismatch" and c.display_name == "PO Mismatch" and c.story.endswith(".")
    assert c.params_schema["properties"]["overage_pct"]["default"] == 0.2
    assert 0 < c.expected_impact["min"] < c.expected_impact["max"]


@respx.mock
async def test_viable_false_without_usable_po():
    _mock_books(pos=[POS[1], POS[2]])  # one already invoiced, one with a frozen vendor
    async with LedgerClient(S, episode_id="ep", day=3) as L:
        assert await PoMismatch().viable(L) is False


@respx.mock
async def test_plan_picks_unreferenced_open_po_of_active_vendor():
    _mock_books()
    async with LedgerClient(S, episode_id="ep", day=3) as L:
        plan = await PoMismatch().plan(L, {})
    assert plan["po_id"] == "po_1" and plan["vendor_id"] == "ven_1" and plan["target_amount"] > 3000.0


@respx.mock
async def test_execute_submits_one_invoice_referencing_the_po():
    _mock_books()
    inv = respx.post("http://bf/api/invoices").mock(return_value=httpx.Response(201, json={"id": "inv_x"}))
    async with LedgerClient(S, episode_id="ep", day=3) as L:
        plan = await PoMismatch().plan(L, {})
        await PoMismatch().execute(L, plan)
    body = json.loads(inv.calls[0].request.content)
    assert inv.call_count == 1 and body["po_id"] == "po_1" and body["amount"] == plan["target_amount"]


@respx.mock
@pytest.mark.parametrize("value,expected", [(-10, 0.01), (10, 1.0)])
async def test_percentage_clamped(value, expected):
    _mock_books()
    async with LedgerClient(S, episode_id="ep", day=3) as ledger:
        plan = await PoMismatch().plan(ledger, {"overage_pct": value})
    assert plan["overage_pct"] == expected
    assert plan["target_amount"] == round(plan["baseline"] * (1 + expected), 2)


@respx.mock
async def test_invalid_override_rejected():
    _mock_books()
    async with LedgerClient(S, episode_id="ep", day=3) as ledger:
        with pytest.raises(ValueError, match="po_mismatch:"):
            await PoMismatch().plan(ledger, {"po_id": "missing"})


@respx.mock
@pytest.mark.parametrize("value", [float("nan"), float("inf"), "invalid", None])
async def test_invalid_percentage_rejected(value):
    _mock_books()
    async with LedgerClient(S, episode_id="ep", day=3) as ledger:
        with pytest.raises(ValueError, match="po_mismatch:"):
            await PoMismatch().plan(ledger, {"overage_pct": value})


@respx.mock
async def test_plan_is_read_only_and_repeatable():
    _mock_books()
    async with LedgerClient(S, episode_id="ep", day=3) as ledger:
        scheme = PoMismatch()
        assert await scheme.viable(ledger)
        assert await scheme.plan(ledger, {}) == await scheme.plan(ledger, {})
    assert all(call.request.method == "GET" for call in respx.calls)


@respx.mock
@pytest.mark.parametrize("po_id", ["po_2", "po_3"])
async def test_ineligible_po_override_rejected(po_id):
    _mock_books()
    async with LedgerClient(S, episode_id="ep", day=3) as ledger:
        with pytest.raises(ValueError, match="po_mismatch:"):
            await PoMismatch().plan(ledger, {"po_id": po_id})


@respx.mock
async def test_deterministic_pick_and_number_collision():
    rows = INVOICES + [dict(INVOICES[0], id="inv_2", invoice_number="HL-2204", received_day=-20)]
    _mock_books(pos=list(reversed(POS)) + [dict(POS[0], id="po_0", status="closed")], invoices=rows)
    async with LedgerClient(S, episode_id="ep", day=3) as ledger:
        plan = await PoMismatch().plan(ledger, {"po_id": "po_1"})
    assert plan["target_amount"] == 3600
    assert plan["invoice_number"] == "HL-2207"
    assert plan["line_items"] == [{"desc": "Q3 freight", "amount": 3600}]


@respx.mock
async def test_no_history_generates_invoice_number_from_po():
    _mock_books(invoices=[])
    async with LedgerClient(S, episode_id="ep", day=3) as ledger:
        plan = await PoMismatch().plan(ledger, {})
    assert plan["invoice_number"] == "INV-po_1-1"
