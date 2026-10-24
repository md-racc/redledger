"""Unit: the mock blue gate's opt-in MOCK_BLUE_ESCALATE triggers. No database."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from mock_agents import server as mock


def _req(action: str = "invoices.approve", amount: float | None = 1200.0, mode: str = "enforce", **ctx: Any) -> dict[str, Any]:
    return {
        "idempotency_key": "tu_1",
        "episode_id": "ep_1",
        "day": 10,
        "controller_mode": mode,
        "agent": "green",
        "action": action,
        "entity_type": "invoice",
        "entity_id": "inv_1",
        "amount": amount,
        "context": {"vendor": {"created_day": -100}, "invoice": {"invoice_number": "A-1"}, **ctx},
    }


async def _gate(monkeypatch: pytest.MonkeyPatch, spec: str, body: dict[str, Any]) -> dict[str, Any]:
    monkeypatch.setattr(mock, "MOCK_BLUE_ESCALATE", spec)
    monkeypatch.setattr(mock.s, "internal_token", "tok")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=mock.app), base_url="http://blue") as cl:
        r = await cl.post("/gate", json=body, headers={"Authorization": "Bearer tok"})
    assert r.status_code == 200, r.text
    return r.json()


async def test_default_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    j = await _gate(monkeypatch, "", _req())
    assert (j["verdict"], j["rules_fired"]) == ("allow", [])
    young = _req()
    young["context"]["vendor"] = {"created_day": 9}
    assert (await _gate(monkeypatch, "", young))["verdict"] == "block"  # one rule, not near_threshold: block


@pytest.mark.parametrize(
    ("spec", "body", "trigger"),
    [
        ("all", _req(), "all"),
        ("*", _req(action="gl.post"), "*"),
        ("amount>1000", _req(amount=1200.0), "amount>1000"),
        ("action:invoices.pay", _req(action="invoices.pay"), "action:invoices.pay"),
        (" action:invoices.pay , amount>100 ", _req(action="invoices.approve", amount=150.0), "amount>100"),
    ],
)
async def test_trigger_escalates(monkeypatch: pytest.MonkeyPatch, spec: str, body: dict[str, Any], trigger: str) -> None:
    j = await _gate(monkeypatch, spec, body)
    assert j["verdict"] == "escalate" and j["rules_fired"][-1] == f"mock_escalate:{trigger}" and j["reason"].startswith("Needs human review")


async def test_rule_trigger_overrides_block(monkeypatch: pytest.MonkeyPatch) -> None:
    body = _req()
    body["context"]["vendor"] = {"created_day": 9}  # vendor_age_lt_7d → block by default
    j = await _gate(monkeypatch, "vendor_age_lt_7d", body)
    assert j["verdict"] == "escalate" and j["rules_fired"] == ["vendor_age_lt_7d", "mock_escalate:vendor_age_lt_7d"]


@pytest.mark.parametrize(
    "spec", ["amount>5000", "action:invoices.pay", "near_threshold", "amount>abc", ",,"], ids=["below", "other-action", "rule-not-fired", "garbage", "empty"]
)
async def test_non_matching_trigger_keeps_default(monkeypatch: pytest.MonkeyPatch, spec: str) -> None:
    assert (await _gate(monkeypatch, spec, _req()))["verdict"] == "allow"


def test_amount_trigger_ignores_calls_without_an_amount() -> None:
    assert mock.escalate_trigger("amount>0", "vendor_changes.approve", None, []) is None
    assert mock.escalate_trigger("amount>0,action:vendor_changes.approve", "vendor_changes.approve", None, []) == "action:vendor_changes.approve"
