"""LedgerClient under strict identity (design B-2) and the gate-preparation calls."""

from __future__ import annotations

import httpx
import pytest
import respx

from agentkit import AgentSettings, GateBlocked, LedgerClient, LedgerError, PreparationRejected, UnverifiedInvocation
from agentkit.invocation import SOURCE_EXPLICIT, SOURCE_LOCAL, SOURCE_PERMISSION, Invocation, ToolUse, bind_invocation, bind_strict

LIVE = AgentSettings(AGENT_NAME="green", BATTLEFIELD_URL="http://bf", INTERNAL_TOKEN="t")
DRY = AgentSettings(AGENT_NAME="green", BATTLEFIELD_URL="http://bf", INTERNAL_TOKEN="t", DRY_RUN=True)

PREP = {
    "preparation_id": "prep_1",
    "idempotency_key": "toolu_1",
    "controller_mode": "enforce",
    "day": 3,
    "action": "invoices.pay",
    "entity_type": "invoice",
    "entity_id": "inv_1",
    "amount": 4920.0,
    "effective": "block",
    "enforced": True,
    "decided_by": "gate",
    "verdict_id": "vd_1",
    "verdict": "block",
    "cause": "control",
    "reason": "vendor age < 7d",
    "rules_fired": ["vendor_age_lt_7d"],
    "escalation_id": None,
    "expires_at": "2026-10-24T15:00:00Z",
    "consumed": False,
}


def _client(s=LIVE):
    return LedgerClient(s, episode_id="ep_1", day=3)


@respx.mock
@pytest.mark.parametrize("inv", [None, Invocation("loc", "pay_invoice", source=SOURCE_LOCAL), Invocation("exp", "pay_invoice", source=SOURCE_EXPLICIT)])
async def test_strict_live_write_without_a_verified_invocation_raises_before_sending(inv):
    route = respx.route(host="bf").mock(return_value=httpx.Response(200, json={}))
    async with _client() as L:
        with bind_strict(True):
            if inv is None:
                with pytest.raises(UnverifiedInvocation):
                    await L.pay_invoice("inv_1")
            else:
                with bind_invocation(inv), pytest.raises(UnverifiedInvocation):
                    await L.pay_invoice("inv_1")
    assert route.calls.call_count == 0


@respx.mock
async def test_strict_live_write_under_a_verified_invocation_uses_its_keys_and_refuses_foreign_ones():
    route = respx.route(host="bf").mock(return_value=httpx.Response(200, json={}))
    async with _client() as L:
        with bind_strict(True), bind_invocation(Invocation("toolu_1", "pay_invoice", source=SOURCE_PERMISSION)):
            await L.pay_invoice("inv_1")
            await L.approve_invoice("inv_1", tool_use_id="toolu_1:5")
            with pytest.raises(UnverifiedInvocation):
                await L.pay_invoice("inv_2", tool_use_id="someone-else")
    assert [c.request.headers["X-Tool-Use-Id"] for c in route.calls] == ["toolu_1", "toolu_1:5"]


@respx.mock
@pytest.mark.parametrize("settings,strict", [(DRY, True), (LIVE, False)])
async def test_dry_run_and_best_effort_keep_uuid4_keys(settings, strict):
    route = respx.route(host="bf").mock(return_value=httpx.Response(200, json={}))
    async with _client(settings) as L:
        with bind_strict(strict):
            await L.pay_invoice("inv_1")
    (key,) = [c.request.headers["X-Tool-Use-Id"] for c in route.calls]
    assert len(key) == 32


@respx.mock
async def test_prepare_sends_the_sdk_id_and_returns_the_preparation_even_for_a_block():
    route = respx.post("http://bf/api/preparations").mock(return_value=httpx.Response(200, json=PREP))
    use = ToolUse("toolu_1", "pay_invoice", {"invoice_id": "inv_1"}, SOURCE_PERMISSION)
    async with _client() as L:
        with bind_strict(True):  # outside any invocation, as from the permission handler
            prep = await L.prepare(use, "invoices.pay", "inv_1", {})
    assert prep.effective == "block" and prep.cause == "control"
    (call,) = route.calls
    assert call.request.headers["X-Tool-Use-Id"] == "toolu_1"


@pytest.mark.parametrize("source", [SOURCE_LOCAL, SOURCE_EXPLICIT])
async def test_prepare_refuses_a_use_the_sdk_did_not_report(source):
    async with _client() as L:
        with pytest.raises(UnverifiedInvocation):
            await L.prepare(ToolUse("x", "pay_invoice", {}, source), "invoices.pay", "inv_1")


@respx.mock
async def test_get_preparation_reads_by_key_and_maps_404_to_none():
    respx.get("http://bf/api/preparations/toolu_1").mock(return_value=httpx.Response(200, json=PREP))
    respx.get("http://bf/api/preparations/nope").mock(return_value=httpx.Response(404, json={"detail": "not found"}))
    async with _client() as L:
        assert (await L.get_preparation("toolu_1")).preparation_id == "prep_1"
        assert await L.get_preparation("nope") is None


@respx.mock
async def test_a_rejected_preparation_is_typed_and_other_409s_are_not():
    rejected = {"error": "preparation_consumed", "preparation_id": "prep_1", "detail": "already executed", "consumed_status": 200}
    respx.post("http://bf/api/invoices/inv_1/pay").mock(return_value=httpx.Response(409, json=rejected))
    respx.post("http://bf/api/invoices/inv_2/pay").mock(return_value=httpx.Response(409, json={"error": "no active turn for this agent"}))
    async with _client(DRY) as L:
        with pytest.raises(PreparationRejected) as e:
            await L.pay_invoice("inv_1")
        assert e.value.error == "preparation_consumed" and e.value.consumed_status == 200
        with pytest.raises(LedgerError) as other:
            await L.pay_invoice("inv_2")
        assert not isinstance(other.value, PreparationRejected)


@respx.mock
async def test_gate_blocked_keeps_cause_escalation_and_preparation():
    body = {"verdict": "block", "reason": "r", "verdict_id": "vd_1", "cause": "gate_unavailable", "escalation_id": "esc_1", "preparation_id": "prep_1"}
    respx.post("http://bf/api/invoices/inv_1/pay").mock(return_value=httpx.Response(403, json=body))
    async with _client(DRY) as L:
        with pytest.raises(GateBlocked) as e:
            await L.pay_invoice("inv_1")
    assert (e.value.cause, e.value.escalation_id, e.value.preparation_id) == ("gate_unavailable", "esc_1", "prep_1")


@respx.mock
@pytest.mark.parametrize(
    "response,expected_body",
    [
        (httpx.Response(409, content=b"{not json", headers={"content-type": "application/json"}), "{not json"),
        (httpx.Response(409, text="conflict"), "conflict"),
        (
            httpx.Response(409, json={"error": "preparation_unknown_kind", "preparation_id": "prep_1"}),
            {"error": "preparation_unknown_kind", "preparation_id": "prep_1"},
        ),
    ],
)
async def test_malformed_or_unknown_409s_stay_plain_ledger_errors(response, expected_body):
    respx.post("http://bf/api/invoices/inv_1/pay").mock(return_value=response)
    async with _client(DRY) as L:
        with pytest.raises(LedgerError) as e:
            await L.pay_invoice("inv_1")
    assert not isinstance(e.value, PreparationRejected) and e.value.status == 409 and e.value.body == expected_body
