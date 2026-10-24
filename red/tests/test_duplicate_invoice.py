"""Owner: Dev Al. duplicate_invoice scheme against a respx-mocked Ledger API."""

import json

import httpx
import pytest
import respx

from agentkit import AgentSettings, LedgerClient
from schemes.duplicate_invoice import DuplicateInvoice

S = AgentSettings(AGENT_NAME="red", BATTLEFIELD_URL="http://bf", INTERNAL_TOKEN="t")

PAID = [
    {
        "id": "inv_a",
        "vendor_id": "ven_1",
        "po_id": "po_1",
        "amount": 3200.0,
        "invoice_number": "INV-54321",
        "line_items": [{"desc": "Pallets", "amount": 2000.0}, {"desc": "Freight", "amount": 1200.0}],
        "received_day": 5,
        "due_day": 35,
        "status": "paid",
    },
    {
        "id": "inv_b",
        "vendor_id": "ven_2",
        "po_id": "po_2",
        "amount": 1500.0,
        "invoice_number": "INV-10002",
        "line_items": [{"desc": "Cleaning", "amount": 1500.0}],
        "received_day": 6,
        "due_day": 36,
        "status": "paid",
    },
    {
        "id": "inv_c",
        "vendor_id": "ven_3",
        "po_id": None,
        "amount": 900.0,
        "invoice_number": "INV-7",
        "line_items": [],
        "received_day": 4,
        "due_day": 34,
        "status": "paid",
    },
]


def _mock_paid(rows):
    return respx.get("http://bf/api/invoices", params={"status": "paid"}).mock(return_value=httpx.Response(200, json=rows))


def test_catalog_shape():
    c = DuplicateInvoice().catalog()
    assert c.id == "duplicate_invoice" and c.display_name == "Duplicate Invoice"
    assert c.story.endswith(".")
    props = c.params_schema["properties"]
    assert set(props) == {"invoice_id", "drift_pct", "reuse_po"}
    assert props["drift_pct"]["default"] == 0.018 and props["drift_pct"]["minimum"] == 0 and props["drift_pct"]["maximum"] == 0.08
    assert c.expected_impact == {"min": 300, "max": 9000}


@respx.mock
async def test_viable_false_without_paid_invoices():
    _mock_paid([])
    async with LedgerClient(S, episode_id="ep", day=1) as L:
        assert await DuplicateInvoice().viable(L) is False


@respx.mock
async def test_viable_true_with_paid_invoice():
    _mock_paid(PAID[:1])
    async with LedgerClient(S, episode_id="ep", day=1) as L:
        assert await DuplicateInvoice().viable(L) is True


@respx.mock
async def test_plan_default_drift_picks_largest_recent_and_keeps_po():
    _mock_paid(PAID)
    async with LedgerClient(S, episode_id="ep", day=1) as L:
        plan = await DuplicateInvoice().plan(L, {})
    assert plan["source_invoice_id"] == "inv_a" and plan["vendor_id"] == "ven_1"
    assert plan["target_amount"] == pytest.approx(3200.0 * 1.018, abs=0.01)
    assert plan["target_amount"] == 3257.6
    assert plan["invoice_number"] != "INV-54321" and plan["invoice_number"].startswith("INV-")
    assert plan["source_invoice_number"] == "INV-54321"
    assert plan["po_id"] == "po_1"
    assert plan["drift_pct"] == 0.018
    assert [li["desc"] for li in plan["line_items"]] == ["Pallets", "Freight"]
    assert round(sum(li["amount"] for li in plan["line_items"]), 2) == plan["target_amount"]


@respx.mock
async def test_plan_zero_drift_is_exact_duplicate():
    _mock_paid(PAID)
    async with LedgerClient(S, episode_id="ep", day=1) as L:
        plan = await DuplicateInvoice().plan(L, {"drift_pct": 0})
    assert plan["target_amount"] == 3200.0
    assert plan["line_items"] == [{"desc": "Pallets", "amount": 2000.0}, {"desc": "Freight", "amount": 1200.0}]


@respx.mock
async def test_plan_reuse_po_false_drops_po():
    _mock_paid(PAID)
    async with LedgerClient(S, episode_id="ep", day=1) as L:
        plan = await DuplicateInvoice().plan(L, {"reuse_po": False})
    assert plan["po_id"] is None


@respx.mock
async def test_plan_explicit_invoice_id_uses_get_invoice():
    paid = _mock_paid(PAID)
    respx.get("http://bf/api/invoices/inv_c").mock(return_value=httpx.Response(200, json=PAID[2]))
    async with LedgerClient(S, episode_id="ep", day=1) as L:
        plan = await DuplicateInvoice().plan(L, {"invoice_id": "inv_c"})
    assert not paid.called
    assert plan["source_invoice_id"] == "inv_c" and plan["vendor_id"] == "ven_3"
    assert plan["target_amount"] == 916.2
    assert plan["invoice_number"] == "INV-10"
    assert plan["po_id"] is None
    assert plan["line_items"] == [{"desc": "services", "amount": 916.2}]


@respx.mock
async def test_plan_invoice_number_without_trailing_int_gets_suffix():
    _mock_paid([dict(PAID[0], invoice_number="INV-A")])
    async with LedgerClient(S, episode_id="ep", day=1) as L:
        plan = await DuplicateInvoice().plan(L, {})
    assert plan["invoice_number"] == "INV-A-R1"


@respx.mock
async def test_plan_escapes_near_threshold_band():
    _mock_paid([dict(PAID[0], amount=4700.0)])  # 4700 * 1.018 = 4784.60 lands in [4750, 5000)
    async with LedgerClient(S, episode_id="ep", day=1) as L:
        plan = await DuplicateInvoice().plan(L, {})
    assert plan["target_amount"] == 5084.6
    assert not (4750 <= plan["target_amount"] < 5000)


@respx.mock
async def test_plan_only_considers_twenty_most_recent():
    rows = [dict(PAID[1], id=f"inv_{i}", received_day=100 - i, amount=1000.0 + i) for i in range(20)]
    rows.append(dict(PAID[0], id="inv_old_big", received_day=1, amount=9000.0))
    _mock_paid(rows)
    async with LedgerClient(S, episode_id="ep", day=1) as L:
        plan = await DuplicateInvoice().plan(L, {})
    assert plan["source_invoice_id"] == "inv_19"


@respx.mock
async def test_execute_posts_exactly_one_invoice():
    _mock_paid(PAID)
    inv = respx.post("http://bf/api/invoices").mock(return_value=httpx.Response(201, json={"id": "inv_new"}))
    async with LedgerClient(S, episode_id="ep", day=1) as L:
        scheme = DuplicateInvoice()
        plan = await scheme.plan(L, {})
        out = await scheme.execute(L, plan)
    assert inv.call_count == 1
    req = inv.calls[0].request
    assert req.headers["X-Agent"] == "red"
    body = json.loads(req.content)
    assert body == {
        "vendor_id": "ven_1",
        "amount": 3257.6,
        "invoice_number": plan["invoice_number"],
        "po_id": "po_1",
        "line_items": plan["line_items"],
    }
    assert out == f"resubmitted INV-54321 as {plan['invoice_number']} for $3,257.60"


@respx.mock
async def test_execute_omits_po_id_when_none():
    _mock_paid(PAID)
    inv = respx.post("http://bf/api/invoices").mock(return_value=httpx.Response(201, json={"id": "inv_new"}))
    async with LedgerClient(S, episode_id="ep", day=1) as L:
        scheme = DuplicateInvoice()
        plan = await scheme.plan(L, {"reuse_po": False})
        await scheme.execute(L, plan)
    body = json.loads(inv.calls[0].request.content)
    assert "po_id" not in body


def test_attack_decl_uses_plan_target_amount():
    scheme = DuplicateInvoice()
    decl = scheme.attack_decl({"target_amount": 3257.6}, {"drift_pct": 0.018})
    assert decl.scheme_id == "duplicate_invoice" and decl.target_amount == 3257.6 and decl.params == {"drift_pct": 0.018}
