"""Owner: Dev Al. amount_drift scheme against a respx-mocked Ledger API. Spec: SCHEMES-SPEC.md §5.3, §7."""

import json

import httpx
import pytest
import respx

from agentkit import AgentSettings, LedgerClient
from schemes.amount_drift import AmountDrift

S = AgentSettings(AGENT_NAME="red", BATTLEFIELD_URL="http://bf", INTERNAL_TOKEN="t")

VENDORS = [
    {
        "id": "ven_r",
        "name": "Cloudline SaaS",
        "bank_account": "1212",
        "bank_routing": "021000021",
        "category": "it",
        "created_day": -365,
        "status": "active",
        "created_by": "seed",
    },
    {
        "id": "ven_o",
        "name": "One-off Print Co",
        "bank_account": "3434",
        "bank_routing": "021000021",
        "category": "office",
        "created_day": -100,
        "status": "active",
        "created_by": "seed",
    },
]
# ven_r bills ~$1,200 every 30 days with no PO; ven_o has one paid invoice (not recurring).
PAID = [
    {
        "id": f"inv_r{i}",
        "vendor_id": "ven_r",
        "po_id": None,
        "amount": amt,
        "invoice_number": f"CL-{1000 + i}",
        "line_items": [{"desc": "subscription", "amount": amt}],
        "received_day": day,
        "due_day": day + 30,
        "status": "paid",
        "status_day": day + 5,
    }
    for i, (amt, day) in enumerate([(1195.0, -90), (1200.0, -60), (1210.0, -30)])
] + [
    {
        "id": "inv_o1",
        "vendor_id": "ven_o",
        "po_id": None,
        "amount": 640.0,
        "invoice_number": "OP-77",
        "line_items": [],
        "received_day": -40,
        "due_day": -10,
        "status": "paid",
        "status_day": -35,
    },
]


def _mock_books(vendors=VENDORS, paid=PAID):
    respx.get("http://bf/api/vendors").mock(return_value=httpx.Response(200, json=vendors))
    respx.get("http://bf/api/invoices").mock(return_value=httpx.Response(200, json=paid))


def test_catalog_shape():
    c = AmountDrift().catalog()
    assert c.id == "amount_drift" and c.display_name == "Amount Drift" and c.story.endswith(".")
    assert c.params_schema["properties"]["step_pct"]["default"] == 0.03
    assert 0 < c.expected_impact["min"] < c.expected_impact["max"]


@respx.mock
async def test_viable_false_without_recurring_vendor():
    _mock_books(paid=PAID[3:])  # only the one-off vendor
    async with LedgerClient(S, episode_id="ep", day=3) as L:
        assert await AmountDrift().viable(L) is False


@respx.mock
async def test_plan_picks_recurring_vendor_and_steps_above_its_mean():
    _mock_books()
    async with LedgerClient(S, episode_id="ep", day=3) as L:
        plan = await AmountDrift().plan(L, {})
    assert plan["vendor_id"] == "ven_r" and plan["target_amount"] > 1201.67 and plan.get("po_id") is None


@respx.mock
async def test_execute_submits_one_invoice():
    _mock_books()
    inv = respx.post("http://bf/api/invoices").mock(return_value=httpx.Response(201, json={"id": "inv_x"}))
    async with LedgerClient(S, episode_id="ep", day=3) as L:
        plan = await AmountDrift().plan(L, {})
        await AmountDrift().execute(L, plan)
    body = json.loads(inv.calls[0].request.content)
    assert inv.call_count == 1 and body["vendor_id"] == "ven_r" and body["amount"] == plan["target_amount"]


@respx.mock
@pytest.mark.parametrize("value,expected", [(-10, 0.001), (10, 0.15)])
async def test_percentage_clamped(value, expected):
    _mock_books()
    async with LedgerClient(S, episode_id="ep", day=3) as ledger:
        plan = await AmountDrift().plan(ledger, {"step_pct": value})
    assert plan["step_pct"] == expected
    assert plan["target_amount"] == round(plan["baseline"] * (1 + expected), 2)


@respx.mock
async def test_invalid_override_rejected():
    _mock_books()
    async with LedgerClient(S, episode_id="ep", day=3) as ledger:
        with pytest.raises(ValueError, match="amount_drift:"):
            await AmountDrift().plan(ledger, {"vendor_id": "missing"})


@respx.mock
@pytest.mark.parametrize("value", [float("nan"), float("inf"), "invalid", None])
async def test_invalid_percentage_rejected(value):
    _mock_books()
    async with LedgerClient(S, episode_id="ep", day=3) as ledger:
        with pytest.raises(ValueError, match="amount_drift:"):
            await AmountDrift().plan(ledger, {"step_pct": value})


@respx.mock
async def test_plan_is_read_only_and_repeatable():
    _mock_books()
    async with LedgerClient(S, episode_id="ep", day=3) as ledger:
        scheme = AmountDrift()
        assert await scheme.viable(ledger)
        assert await scheme.plan(ledger, {}) == await scheme.plan(ledger, {})
    assert all(call.request.method == "GET" for call in respx.calls)


@respx.mock
async def test_latest_three_must_be_similar_and_vendor_active():
    _mock_books(paid=PAID + [dict(PAID[0], id="inv_new", amount=5000, received_day=0)])
    async with LedgerClient(S, episode_id="ep", day=3) as ledger:
        assert not await AmountDrift().viable(ledger)
        with pytest.raises(ValueError, match="amount_drift:"):
            await AmountDrift().plan(ledger, {})
    _mock_books(vendors=[dict(VENDORS[0], status="frozen")])
    async with LedgerClient(S, episode_id="ep", day=3) as ledger:
        assert not await AmountDrift().viable(ledger)


@respx.mock
async def test_shuffled_history_preserves_latest_descriptions_and_cents():
    latest = dict(PAID[2], line_items=[{"desc": "subscription", "amount": 800}, {"desc": "support", "amount": 410}])
    _mock_books(paid=[latest, PAID[1], PAID[0], PAID[3]])
    route = respx.post("http://bf/api/invoices").mock(return_value=httpx.Response(201, json={"id": "inv_x"}))
    async with LedgerClient(S, episode_id="ep", day=3) as ledger:
        plan = await AmountDrift().plan(ledger, {"vendor_id": "ven_r"})
        await AmountDrift().execute(ledger, plan)
    assert plan["target_amount"] == 1237.72
    assert [row["desc"] for row in plan["line_items"]] == ["subscription", "support"]
    assert round(sum(row["amount"] for row in plan["line_items"]), 2) == plan["target_amount"]
    assert "po_id" not in json.loads(route.calls[0].request.content)


@respx.mock
async def test_po_backed_history_keeps_latest_po():
    _mock_books(paid=[dict(row, po_id="po_recurring") for row in PAID])
    async with LedgerClient(S, episode_id="ep", day=3) as ledger:
        plan = await AmountDrift().plan(ledger, {})
    assert plan["po_id"] == "po_recurring"


def test_registry_preserves_original_rotation():
    from schemes import SCHEMES

    assert list(SCHEMES) == [
        "ghost_vendor",
        "bank_swap",
        "duplicate_invoice",
        "threshold_split",
        "ghost_employee",
        "expense_inflation",
        "po_mismatch",
        "amount_drift",
    ]
