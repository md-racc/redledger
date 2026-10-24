"""Owner: Dev Al. bank_swap: hijack a real vendor's remittance account, then invoice as that vendor."""

import json

import httpx
import respx

from agentkit import AgentSettings, LedgerClient
from schemes.bank_swap import BankSwap

S = AgentSettings(AGENT_NAME="red", BATTLEFIELD_URL="http://bf", INTERNAL_TOKEN="t")

VENDORS = [
    {"id": "ven_a", "name": "Harbor Logistics LLC", "bank_account": "1111111111", "bank_routing": "021000021", "category": "freight", "status": "active"},
    {"id": "ven_b", "name": "Pacific Paper Inc", "bank_account": "2222222222", "bank_routing": "021000021", "category": "office", "status": "active"},
]
PAID = [
    {"id": "inv_1", "vendor_id": "ven_a", "po_id": "po_1", "amount": 3100.0, "invoice_number": "INV-54321", "received_day": 1, "status": "paid"},
    {"id": "inv_2", "vendor_id": "ven_b", "po_id": None, "amount": 1200.0, "invoice_number": "PP-0090", "received_day": 2, "status": "paid"},
    {"id": "inv_3", "vendor_id": "ven_b", "po_id": None, "amount": 1400.0, "invoice_number": "PP-0093", "received_day": 3, "status": "paid"},
]
OPEN_POS = [
    {"id": "po_small", "vendor_id": "ven_b", "amount": 2000.0, "description": "paper", "status": "open"},
    {"id": "po_big", "vendor_id": "ven_a", "amount": 4400.0, "description": "freight", "status": "open"},
    # bigger, but 0.99x lands over the $5k auto-pay line, so it must lose to po_big
    {"id": "po_huge", "vendor_id": "ven_a", "amount": 8000.0, "description": "freight", "status": "open"},
]


def _mock_reads(vendors=VENDORS, paid=PAID, open_pos=OPEN_POS):
    respx.get("http://bf/api/vendors", params={"status": "active"}).mock(return_value=httpx.Response(200, json=vendors))
    respx.get("http://bf/api/invoices", params={"status": "paid"}).mock(return_value=httpx.Response(200, json=paid))
    respx.get("http://bf/api/purchase_orders", params={"status": "open"}).mock(return_value=httpx.Response(200, json=open_pos))


def test_catalog_shape():
    c = BankSwap().catalog()
    assert c.id == "bank_swap" and c.display_name == "Bank Account Swap"
    assert c.story.endswith(".")
    assert set(c.params_schema["properties"]) == {"vendor_id", "amount", "new_account", "justification"}
    assert c.expected_impact == {"min": 2000, "max": 12000}


@respx.mock
async def test_viable_false_without_paid_invoices():
    _mock_reads(paid=[])
    async with LedgerClient(S, episode_id="ep", day=1) as L:
        assert await BankSwap().viable(L) is False


@respx.mock
async def test_viable_false_when_paid_vendors_not_active():
    _mock_reads(vendors=[])
    async with LedgerClient(S, episode_id="ep", day=1) as L:
        assert await BankSwap().viable(L) is False


@respx.mock
async def test_viable_true_with_active_paid_vendor():
    _mock_reads()
    async with LedgerClient(S, episode_id="ep", day=1) as L:
        assert await BankSwap().viable(L) is True


@respx.mock
async def test_plan_picks_largest_open_po_vendor():
    _mock_reads()
    async with LedgerClient(S, episode_id="ep", day=1) as L:
        plan = await BankSwap().plan(L, {})
    assert plan["vendor_id"] == "ven_a" and plan["vendor_name"] == "Harbor Logistics LLC"
    assert plan["po_id"] == "po_big"
    assert plan["target_amount"] == 4356.0  # 0.99 * 4400: largest PO that still auto-pays under the line
    assert plan["invoice_number"] == "INV-54328"  # existing format, bumped by 7
    assert len(plan["new_account"]) == 10 and plan["new_account"].isdigit() and plan["new_account"] != "1111111111"
    assert plan["justification"]
    assert plan["category"] == "freight"


@respx.mock
async def test_plan_is_deterministic():
    _mock_reads()
    async with LedgerClient(S, episode_id="ep", day=1) as L:
        a = await BankSwap().plan(L, {})
        b = await BankSwap().plan(L, {})
    assert a == b


@respx.mock
async def test_plan_falls_back_to_most_paid_history_without_open_pos():
    _mock_reads(open_pos=[])
    async with LedgerClient(S, episode_id="ep", day=1) as L:
        plan = await BankSwap().plan(L, {})
    assert plan["vendor_id"] == "ven_b"
    assert plan["po_id"] is None
    assert plan["target_amount"] == 1300.0  # mean of 1200, 1400
    assert plan["invoice_number"] == "PP-0100"  # most recent paid PP-0093 + 7, width preserved


@respx.mock
async def test_plan_honours_params():
    _mock_reads()
    async with LedgerClient(S, episode_id="ep", day=1) as L:
        plan = await BankSwap().plan(L, {"vendor_id": "ven_b", "amount": 2600, "new_account": "9876543210", "justification": "New treasury account."})
    assert plan["vendor_id"] == "ven_b" and plan["vendor_name"] == "Pacific Paper Inc"
    assert plan["target_amount"] == 2600.0
    assert plan["po_id"] is None  # explicit amount is not tied to the vendor's PO
    assert plan["new_account"] == "9876543210"
    assert plan["justification"] == "New treasury account."


@respx.mock
async def test_plan_avoids_near_threshold_band():
    pos = [{"id": "po_nt", "vendor_id": "ven_a", "amount": 4900.0, "description": "freight", "status": "open"}]
    _mock_reads(open_pos=pos)
    async with LedgerClient(S, episode_id="ep", day=1) as L:
        plan = await BankSwap().plan(L, {})
    assert plan["po_id"] == "po_nt"
    assert not (4750 <= plan["target_amount"] < 5000)
    assert plan["target_amount"] < 4750


@respx.mock
async def test_plan_falls_back_to_generic_invoice_number():
    paid = [{"id": "inv_9", "vendor_id": "ven_a", "po_id": None, "amount": 3000.0, "invoice_number": "FREIGHT-MAY", "received_day": 1, "status": "paid"}]
    _mock_reads(paid=paid, open_pos=[])
    async with LedgerClient(S, episode_id="ep", day=1) as L:
        plan = await BankSwap().plan(L, {})
    assert plan["invoice_number"].startswith("INV-") and len(plan["invoice_number"]) == len("INV-12345")


@respx.mock
async def test_execute_requests_bank_change_then_invoices():
    _mock_reads()
    vc = respx.post("http://bf/api/vendor_changes").mock(return_value=httpx.Response(201, json={"id": "vc_x", "status": "pending"}))
    inv = respx.post("http://bf/api/invoices").mock(return_value=httpx.Response(201, json={"id": "inv_x"}))
    async with LedgerClient(S, episode_id="ep", day=1) as L:
        scheme = BankSwap()
        plan = await scheme.plan(L, {})
        out = await scheme.execute(L, plan)

    assert vc.call_count == 1 and inv.call_count == 1
    assert vc.calls[0].request.headers["X-Agent"] == "red" and inv.calls[0].request.headers["X-Agent"] == "red"
    assert vc.calls[0].request.headers["X-Tool-Use-Id"] != inv.calls[0].request.headers["X-Tool-Use-Id"]

    change = json.loads(vc.calls[0].request.content)
    assert change == {"vendor_id": "ven_a", "field": "bank_account", "new_value": plan["new_account"], "justification": plan["justification"]}

    body = json.loads(inv.calls[0].request.content)
    assert body["vendor_id"] == "ven_a" and body["amount"] == 4356.0 and body["po_id"] == "po_big"
    assert body["invoice_number"] == "INV-54328"
    assert body["line_items"] == [{"desc": "freight — monthly", "amount": 4356.0}]

    # order: vendor change strictly before the invoice
    order = [c.request.url.path for c in respx.calls if c.request.method == "POST"]
    assert order == ["/api/vendor_changes", "/api/invoices"]

    assert "Harbor Logistics LLC" in out and "4,356.00" in out and plan["new_account"][-4:] in out


@respx.mock
async def test_execute_omits_po_id_when_none():
    _mock_reads(open_pos=[])
    respx.post("http://bf/api/vendor_changes").mock(return_value=httpx.Response(201, json={"id": "vc_x"}))
    inv = respx.post("http://bf/api/invoices").mock(return_value=httpx.Response(201, json={"id": "inv_x"}))
    async with LedgerClient(S, episode_id="ep", day=1) as L:
        scheme = BankSwap()
        plan = await scheme.plan(L, {})
        await scheme.execute(L, plan)
    body = json.loads(inv.calls[0].request.content)
    assert "po_id" not in body
    assert body["line_items"][0]["desc"] == "office — monthly"
