"""Owner: Dev Al. Pattern: mock the Ledger API with respx and assert the scheme's calls."""

import json

import httpx
import respx

from agentkit import AgentSettings, LedgerClient
from schemes.ghost_employee import NAMES, GhostEmployee

S = AgentSettings(AGENT_NAME="red", BATTLEFIELD_URL="http://bf", INTERNAL_TOKEN="t")

EMPLOYEES = [
    {"id": "emp_1", "name": "Ada Seed", "role": "Ops", "department": "operations", "salary": 64000, "bank_account": "1234567890", "status": "active"},
    {"id": "emp_2", "name": "Bo Seed", "role": "Sales", "department": "sales", "salary": 80000, "bank_account": "2345678901", "status": "active"},
]
VENDORS = [{"id": "ven_1", "name": "Seed Vendor", "bank_account": "3456789012", "status": "active"}]


def _mock_reads():
    respx.get("http://bf/api/employees").mock(return_value=httpx.Response(200, json=EMPLOYEES))
    respx.get("http://bf/api/vendors").mock(return_value=httpx.Response(200, json=VENDORS))


def test_catalog_shape():
    c = GhostEmployee().catalog()
    assert c.id == "ghost_employee"
    assert c.display_name == "Ghost Employee"
    assert c.story.endswith(".")
    assert set(c.params_schema["properties"]) == {"name", "role", "department", "salary", "claims", "total", "bank_account"}
    assert c.expected_impact == {"min": 600, "max": 2500}


@respx.mock
async def test_plan_defaults():
    _mock_reads()
    async with LedgerClient(S, episode_id="ep", day=1) as L:
        plan = await GhostEmployee().plan(L, {})
    assert len(plan["expenses"]) == 3
    assert abs(sum(e["amount"] for e in plan["expenses"]) - 1480) < 0.01
    assert abs(plan["target_amount"] - 1480) < 0.01
    assert [e["category"] for e in plan["expenses"]] == ["travel", "software", "meals"]
    assert all(60 <= e["amount"] <= 900 and e["memo"] for e in plan["expenses"])
    emp = plan["employee"]
    assert emp["name"] == NAMES[len(EMPLOYEES) % len(NAMES)]
    assert emp["role"] == "Contractor" and emp["department"] == "operations" and emp["salary"] == 72000
    assert len(emp["bank_account"]) == 10 and emp["bank_account"].isdigit()
    assert emp["bank_account"] not in {r["bank_account"] for r in [*EMPLOYEES, *VENDORS]}


@respx.mock
async def test_plan_is_deterministic_and_avoids_taken_accounts():
    _mock_reads()
    async with LedgerClient(S, episode_id="ep", day=1) as L:
        a = await GhostEmployee().plan(L, {"name": "Daniel Whitfield"})
        b = await GhostEmployee().plan(L, {"name": "Daniel Whitfield"})
    assert a == b
    acct = a["employee"]["bank_account"]
    # If the derived account were already an employee's, the salt bumps and a different one comes out.
    respx.get("http://bf/api/employees").mock(return_value=httpx.Response(200, json=[{**EMPLOYEES[0], "bank_account": acct}]))
    async with LedgerClient(S, episode_id="ep", day=1) as L:
        c = await GhostEmployee().plan(L, {"name": "Daniel Whitfield"})
    assert c["employee"]["bank_account"] != acct
    assert len(c["employee"]["bank_account"]) == 10 and c["employee"]["bank_account"].isdigit()


@respx.mock
async def test_plan_single_claim_and_overrides():
    _mock_reads()
    async with LedgerClient(S, episode_id="ep", day=1) as L:
        plan = await GhostEmployee().plan(L, {"claims": 1, "total": 900, "name": "Casey Park", "role": "Field Tech", "bank_account": "5555555555"})
    assert plan["expenses"] == [{"amount": 900.0, "category": "travel", "memo": "Client site visit — mileage and lodging"}]
    assert plan["target_amount"] == 900.0
    assert plan["employee"]["name"] == "Casey Park" and plan["employee"]["role"] == "Field Tech"
    assert plan["employee"]["bank_account"] == "5555555555"


@respx.mock
async def test_plan_clamps_claims_and_total():
    _mock_reads()
    async with LedgerClient(S, episode_id="ep", day=1) as L:
        plan = await GhostEmployee().plan(L, {"claims": 9, "total": 99999})
    assert len(plan["expenses"]) == 3
    assert abs(plan["target_amount"] - 2500) < 0.01


@respx.mock
async def test_execute_creates_employee_then_files_claims():
    _mock_reads()
    emp = respx.post("http://bf/api/employees").mock(return_value=httpx.Response(201, json={"id": "emp_ghost", "name": "x", "hr_record": False}))
    exp = respx.post("http://bf/api/expenses").mock(return_value=httpx.Response(201, json={"id": "exp_x", "status": "pending"}))
    async with LedgerClient(S, episode_id="ep", day=1) as L:
        scheme = GhostEmployee()
        plan = await scheme.plan(L, {})
        out = await scheme.execute(L, plan)

    assert emp.call_count == 1
    emp_body = json.loads(emp.calls[0].request.content)
    assert emp_body == plan["employee"]
    assert emp.calls[0].request.headers["X-Agent"] == "red"

    assert exp.call_count == 3
    for call, planned in zip(exp.calls, plan["expenses"], strict=True):
        body = json.loads(call.request.content)
        assert body == {"employee_id": "emp_ghost", **planned}
        assert call.request.headers["X-Agent"] == "red"
        assert call.request.headers["X-Tool-Use-Id"]
    assert out == f"added {plan['employee']['name']} (Contractor) and filed 3 expense claims totaling $1,480.00"


@respx.mock
async def test_execute_single_claim_summary():
    _mock_reads()
    respx.post("http://bf/api/employees").mock(return_value=httpx.Response(201, json={"id": "emp_ghost"}))
    exp = respx.post("http://bf/api/expenses").mock(return_value=httpx.Response(201, json={"id": "exp_x"}))
    async with LedgerClient(S, episode_id="ep", day=1) as L:
        scheme = GhostEmployee()
        plan = await scheme.plan(L, {"claims": 1, "total": 640})
        out = await scheme.execute(L, plan)
    assert exp.call_count == 1
    assert json.loads(exp.calls[0].request.content)["amount"] == 640.0
    assert out.endswith("filed 1 expense claim totaling $640.00")
