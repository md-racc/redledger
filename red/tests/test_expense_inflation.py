"""Owner: Dev Al. expense_inflation scheme against a respx-mocked Ledger API. Spec: SCHEMES-SPEC.md §5.1, §7."""

import json

import httpx
import pytest
import respx

from agentkit import AgentSettings, LedgerClient
from schemes.expense_inflation import ExpenseInflation

S = AgentSettings(AGENT_NAME="red", BATTLEFIELD_URL="http://bf", INTERNAL_TOKEN="t")

# Rows look like what GET /api/employees and GET /api/expenses return to red (origin/attack_id are stripped).
EMPLOYEES = [
    {
        "id": "emp_1",
        "episode_id": "ep",
        "name": "Dana Ruiz",
        "role": "Account Manager",
        "department": "Sales",
        "salary": 82000.0,
        "bank_account": "1111222233",
        "start_day": -400,
        "status": "active",
        "hr_record": True,
    },
    {
        "id": "emp_2",
        "episode_id": "ep",
        "name": "Lee Park",
        "role": "Engineer",
        "department": "IT",
        "salary": 98000.0,
        "bank_account": "4444555566",
        "start_day": -200,
        "status": "terminated",
        "hr_record": True,
    },
]
EXPENSES = [
    {"id": "exp_1", "employee_id": "emp_1", "amount": 210.0, "category": "travel", "memo": "client lunch", "submitted_day": -20, "status": "paid"},
    {"id": "exp_2", "employee_id": "emp_1", "amount": 190.0, "category": "travel", "memo": "taxi", "submitted_day": -10, "status": "paid"},
    {"id": "exp_3", "employee_id": "emp_2", "amount": 900.0, "category": "equipment", "memo": "monitor", "submitted_day": -30, "status": "paid"},
]


def _mock_books(employees=EMPLOYEES, expenses=EXPENSES):
    respx.get("http://bf/api/employees").mock(return_value=httpx.Response(200, json=employees))
    respx.get("http://bf/api/expenses").mock(return_value=httpx.Response(200, json=expenses))


def test_catalog_shape():
    c = ExpenseInflation().catalog()
    assert c.id == "expense_inflation" and c.display_name == "Expense Inflation" and c.story.endswith(".")
    assert c.params_schema["properties"]["inflation_pct"]["default"] == 0.2
    assert 0 < c.expected_impact["min"] < c.expected_impact["max"]


@respx.mock
async def test_viable_false_without_history():
    _mock_books(expenses=[])
    async with LedgerClient(S, episode_id="ep", day=3) as L:
        assert await ExpenseInflation().viable(L) is False


@respx.mock
async def test_plan_picks_active_employee_and_inflates_their_average():
    _mock_books()
    async with LedgerClient(S, episode_id="ep", day=3) as L:
        plan = await ExpenseInflation().plan(L, {})
    assert plan["employee_id"] == "emp_1"


@respx.mock
async def test_execute_submits_one_expense():
    _mock_books()
    exp = respx.post("http://bf/api/expenses").mock(return_value=httpx.Response(201, json={"id": "exp_x"}))
    async with LedgerClient(S, episode_id="ep", day=3) as L:
        plan = await ExpenseInflation().plan(L, {})
        await ExpenseInflation().execute(L, plan)
    body = json.loads(exp.calls[0].request.content)
    assert exp.call_count == 1 and body["employee_id"] == "emp_1" and body["amount"] == plan["target_amount"]


@respx.mock
@pytest.mark.parametrize("value,expected", [(-10, 0.01), (10, 1.0)])
async def test_percentage_clamped(value, expected):
    _mock_books()
    async with LedgerClient(S, episode_id="ep", day=3) as ledger:
        plan = await ExpenseInflation().plan(ledger, {"inflation_pct": value})
    assert plan["inflation_pct"] == expected
    assert plan["target_amount"] == round(plan["baseline"] * (1 + expected), 2)


@respx.mock
async def test_invalid_override_rejected():
    _mock_books()
    async with LedgerClient(S, episode_id="ep", day=3) as ledger:
        with pytest.raises(ValueError, match="expense_inflation:"):
            await ExpenseInflation().plan(ledger, {"employee_id": "missing"})


@respx.mock
@pytest.mark.parametrize("value", [float("nan"), float("inf"), "invalid", None])
async def test_invalid_percentage_rejected(value):
    _mock_books()
    async with LedgerClient(S, episode_id="ep", day=3) as ledger:
        with pytest.raises(ValueError, match="expense_inflation:"):
            await ExpenseInflation().plan(ledger, {"inflation_pct": value})


@respx.mock
async def test_plan_is_read_only_and_repeatable():
    _mock_books()
    async with LedgerClient(S, episode_id="ep", day=3) as ledger:
        scheme = ExpenseInflation()
        assert await scheme.viable(ledger)
        assert await scheme.plan(ledger, {}) == await scheme.plan(ledger, {})
    assert all(call.request.method == "GET" for call in respx.calls)


@respx.mock
async def test_trailing_window_category_and_override():
    rows = [dict(EXPENSES[0], id=f"exp_{i:02}", amount=100 + i, submitted_day=i) for i in range(11)]
    _mock_books(expenses=list(reversed(rows)))
    async with LedgerClient(S, episode_id="ep", day=20) as ledger:
        plan = await ExpenseInflation().plan(ledger, {"employee_id": "emp_1", "category": "meals"})
    assert plan["baseline"] == 105.5
    assert plan["target_amount"] == 126.6
    assert plan["category"] == "meals"


@respx.mock
async def test_terminated_employee_override_rejected():
    _mock_books()
    async with LedgerClient(S, episode_id="ep", day=3) as ledger:
        with pytest.raises(ValueError, match="expense_inflation:"):
            await ExpenseInflation().plan(ledger, {"employee_id": "emp_2"})


@respx.mock
async def test_default_category_and_amount():
    _mock_books()
    async with LedgerClient(S, episode_id="ep", day=3) as ledger:
        plan = await ExpenseInflation().plan(ledger, {})
    assert plan["baseline"] == 200
    assert plan["target_amount"] == 240
    assert plan["category"] == "travel"
