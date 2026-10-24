"""Owner: Dev Al. Pattern: mock the Ledger API with respx and assert the scheme's calls."""

import json

import httpx
import respx

from agentkit import AgentSettings, LedgerClient
from schemes.threshold_split import ThresholdSplit

S = AgentSettings(AGENT_NAME="red", BATTLEFIELD_URL="http://bf", INTERNAL_TOKEN="t")


def _pairwise_ok(amounts):
    for i in range(len(amounts)):
        for j in range(i + 1, len(amounts)):
            a, b = amounts[i], amounts[j]
            if abs(a - b) <= 0.01 * min(a, b):
                return False
    return True


def test_catalog_shape():
    c = ThresholdSplit().catalog()
    assert c.id == "threshold_split"
    assert c.display_name == "Threshold Splitting"
    assert c.story.endswith(".")
    assert c.expected_impact == {"min": 9000, "max": 15000}


@respx.mock
async def test_plan_default_three_parts_sum_and_spread():
    # One active vendor with paid history well away from ~4600 so no nudging fires.
    respx.get("http://bf/api/vendors", params={"status": "active"}).mock(
        return_value=httpx.Response(200, json=[{"id": "ven_a", "name": "Globex Logistics LLC", "status": "active"}])
    )
    respx.get("http://bf/api/invoices", params={"status": "paid"}).mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": "i1", "vendor_id": "ven_a", "amount": 8000, "invoice_number": "GLX-00040", "status": "paid"},
                {"id": "i2", "vendor_id": "ven_a", "amount": 8200, "invoice_number": "GLX-00041", "status": "paid"},
                {"id": "i3", "vendor_id": "ven_a", "amount": 8400, "invoice_number": "GLX-00042", "status": "paid"},
            ],
        )
    )
    async with LedgerClient(S, episode_id="ep", day=1) as L:
        plan = await ThresholdSplit().plan(L, {"threshold": 5000})
    amts = plan["amounts"]
    assert len(amts) == 3
    assert abs(sum(amts) - 13800) <= 0.01
    assert abs(plan["target_amount"] - 13800) <= 0.01
    assert all(a < 0.93 * 5000 for a in amts)  # < 4650
    assert _pairwise_ok(amts)
    assert plan["vendor_id"] == "ven_a"
    assert plan["vendor"] is None
    # invoice numbers continue the vendor's format: GLX-00042 bumped by +2, +3, +4
    assert plan["invoice_numbers"] == ["GLX-00044", "GLX-00045", "GLX-00046"]


@respx.mock
async def test_plan_adapts_to_low_threshold():
    respx.get("http://bf/api/vendors", params={"status": "active"}).mock(
        return_value=httpx.Response(200, json=[{"id": "ven_a", "name": "Globex Logistics LLC", "status": "active"}])
    )
    respx.get("http://bf/api/invoices", params={"status": "paid"}).mock(
        return_value=httpx.Response(
            200,
            json=[{"id": "i1", "vendor_id": "ven_a", "amount": 2000, "invoice_number": "GLX-00040", "status": "paid"}],
        )
    )
    async with LedgerClient(S, episode_id="ep", day=1) as L:
        plan = await ThresholdSplit().plan(L, {"threshold": 3000})
    amts = plan["amounts"]
    cap = 0.93 * 3000
    assert all(a < cap for a in amts)
    assert _pairwise_ok(amts)
    assert abs(plan["target_amount"] - sum(amts)) <= 0.01
    # default total/parts (4600) is way over cap, so parts was raised and total lowered
    assert len(amts) == 4
    assert plan["target_amount"] < 13800


@respx.mock
async def test_plan_new_vendor_caps_parts_and_returns_vendor():
    async with LedgerClient(S, episode_id="ep", day=1) as L:
        plan = await ThresholdSplit().plan(L, {"new_vendor": True, "parts": 4, "threshold": 5000})
    assert plan["vendor_id"] is None
    v = plan["vendor"]
    assert isinstance(v, dict)
    assert v["name"] and v["category"] in {"facilities", "professional"}
    assert len(v["bank_account"]) == 10 and v["bank_account"].isdigit()
    assert len(v["bank_routing"]) == 9 and v["bank_routing"].isdigit()
    assert len(v["ein"]) == 10 and v["ein"][2] == "-"
    # creating a vendor caps parts at 3 (create_vendor + 3 invoices == 4 writes)
    assert len(plan["amounts"]) == 3
    assert len(plan["invoice_numbers"]) == 3
    assert all(n.startswith("INV-") and len(n) == 9 for n in plan["invoice_numbers"])


@respx.mock
async def test_plan_is_deterministic_for_new_vendor():
    async with LedgerClient(S, episode_id="ep", day=1) as L:
        p1 = await ThresholdSplit().plan(L, {"new_vendor": True, "threshold": 5000})
        p2 = await ThresholdSplit().plan(L, {"new_vendor": True, "threshold": 5000})
    assert p1["vendor"] == p2["vendor"]
    assert p1["amounts"] == p2["amounts"]
    assert p1["invoice_numbers"] == p2["invoice_numbers"]


@respx.mock
async def test_execute_new_vendor_posts_vendor_then_invoices():
    vendors = respx.post("http://bf/api/vendors").mock(return_value=httpx.Response(201, json={"id": "ven_new", "name": "x"}))
    invoices = respx.post("http://bf/api/invoices").mock(return_value=httpx.Response(201, json={"id": "inv_x"}))
    async with LedgerClient(S, episode_id="ep", day=1) as L:
        plan = await ThresholdSplit().plan(L, {"new_vendor": True, "threshold": 5000})
        out = await ThresholdSplit().execute(L, plan)

    # vendor created first, then one invoice per amount (<=4 writes total)
    assert vendors.call_count == 1
    assert invoices.call_count == len(plan["amounts"]) <= 3
    vbody = json.loads(vendors.calls[0].request.content)
    assert vbody == plan["vendor"]
    assert vendors.calls[0].request.headers["X-Agent"] == "red"

    for k, call in enumerate(invoices.calls, start=1):
        body = json.loads(call.request.content)
        assert body["vendor_id"] == "ven_new"
        assert body["amount"] == plan["amounts"][k - 1]
        assert body["invoice_number"] == plan["invoice_numbers"][k - 1]
        assert "po_id" not in body
        assert body["line_items"][0]["amount"] == plan["amounts"][k - 1]
        assert f"phase {k} of {len(plan['amounts'])}" in body["line_items"][0]["desc"]
        assert call.request.headers["X-Agent"] == "red"

    assert out.startswith("split $")
    assert f"across {len(plan['amounts'])} invoices" in out


@respx.mock
async def test_execute_existing_vendor_no_vendor_post():
    respx.get("http://bf/api/vendors", params={"status": "active"}).mock(
        return_value=httpx.Response(200, json=[{"id": "ven_a", "name": "Globex Logistics LLC", "status": "active"}])
    )
    respx.get("http://bf/api/invoices", params={"status": "paid"}).mock(
        return_value=httpx.Response(
            200,
            json=[{"id": "i1", "vendor_id": "ven_a", "amount": 8000, "invoice_number": "GLX-00040", "status": "paid"}],
        )
    )
    vendors = respx.post("http://bf/api/vendors").mock(return_value=httpx.Response(201, json={"id": "nope"}))
    invoices = respx.post("http://bf/api/invoices").mock(return_value=httpx.Response(201, json={"id": "inv_x"}))
    async with LedgerClient(S, episode_id="ep", day=1) as L:
        plan = await ThresholdSplit().plan(L, {"threshold": 5000})
        out = await ThresholdSplit().execute(L, plan)
    assert vendors.call_count == 0
    assert invoices.call_count == len(plan["amounts"])
    assert json.loads(invoices.calls[0].request.content)["vendor_id"] == "ven_a"
    assert "Globex Logistics LLC" in out
