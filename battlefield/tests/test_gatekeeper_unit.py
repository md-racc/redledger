"""Unit: gatekeeper fallback when blue is unreachable, and verdict application per mode. No DB."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.auth import Caller
from app.gate import gatekeeper as gate

C = Caller(agent="green", episode_id="ep_1", day=2, tool_use_id="toolu_1")


def _client_with(handler: Any) -> type:
    real = httpx.AsyncClient

    class Client(real):  # type: ignore[misc,valid-type]
        def __init__(self, *a: Any, **kw: Any) -> None:
            kw["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **kw)

    return Client


def _unreachable(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectTimeout("blue is down", request=request)


async def _ask(mode: str) -> tuple[str, str, float | None, list[str]]:
    return await gate._ask_blue(C, mode, "invoices.pay", "invoice", "inv_1", 100.0, {}, {})


@pytest.mark.parametrize(("mode", "fallback"), [("shadow", "allow"), ("enforce", "escalate")])
async def test_blue_unreachable_falls_back(monkeypatch: pytest.MonkeyPatch, mode: str, fallback: str) -> None:
    monkeypatch.setattr(gate.httpx, "AsyncClient", _client_with(_unreachable))
    verdict, reason, confidence, rules = await _ask(mode)
    assert verdict == fallback
    assert rules == ["gate_timeout"]
    assert confidence is None
    assert "controller unavailable" in reason and "ConnectTimeout" in reason


async def test_blue_5xx_also_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gate.httpx, "AsyncClient", _client_with(lambda req: httpx.Response(500)))
    verdict, _, _, rules = await _ask("enforce")
    assert (verdict, rules) == ("escalate", ["gate_timeout"])


async def test_blue_verdict_is_passed_through(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["auth"] = req.headers["authorization"]
        seen["body"] = req.read()
        return httpx.Response(200, json={"verdict": "block", "reason": "bank changed", "confidence": 0.9, "rules_fired": ["bank_change_recent"]})

    monkeypatch.setattr(gate.httpx, "AsyncClient", _client_with(handler))
    assert await _ask("enforce") == ("block", "bank changed", 0.9, ["bank_change_recent"])
    assert seen["auth"].startswith("Bearer ")
    assert b'"idempotency_key":"toolu_1"' in seen["body"].replace(b" ", b"")


async def test_mode_off_allows_without_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    async def off(_: str) -> str:
        return "off"

    monkeypatch.setattr(gate, "controller_mode", off)
    d = await gate.check(C, action="invoices.pay", entity_type="invoice", entity_id="inv_1", amount=1.0)
    assert d.allowed and d.verdict_id is None and not d.enforced


async def _apply(verdict: str, mode: str) -> gate.Decision:
    return await gate._apply("vd_1", verdict, "why", mode, C, "invoices.pay", "invoice", "inv_1", 100.0)


@pytest.mark.parametrize("verdict", ["allow", "block", "escalate"])
async def test_shadow_always_allows_unenforced(verdict: str) -> None:
    d = await _apply(verdict, "shadow")
    assert d.allowed and not d.enforced
    assert d.verdict == verdict and d.verdict_id == "vd_1"


async def test_enforce_allow() -> None:
    d = await _apply("allow", "enforce")
    assert d.allowed and d.enforced and d.verdict_id == "vd_1"


async def test_enforce_block_raises() -> None:
    with pytest.raises(gate.GateBlockedError) as ei:
        await _apply("block", "enforce")
    assert ei.value.verdict_id == "vd_1" and ei.value.reason == "why"


@pytest.mark.parametrize(("decision", "allowed"), [("approve", True), ("block", False), ("timeout", False)])
async def test_enforce_escalate_waits_for_human(monkeypatch: pytest.MonkeyPatch, decision: str, allowed: bool) -> None:
    async def fake_escalate(*_: Any) -> tuple[str, str]:
        return "esc_1", decision

    monkeypatch.setattr(gate, "_escalate", fake_escalate)
    if allowed:
        d = await _apply("escalate", "enforce")
        assert d.allowed and d.enforced and d.verdict == "escalate"
    else:
        with pytest.raises(gate.GateBlockedError) as ei:
            await _apply("escalate", "enforce")
        assert decision in ei.value.reason and ei.value.escalation_id == "esc_1"


def test_same_action_compares_action_entity_and_amount() -> None:
    from decimal import Decimal

    row = {"action": "invoices.pay", "entity_type": "invoice", "entity_id": "inv_1", "amount": Decimal("100.00"), "args": {}}
    assert gate.same_action(row, "invoices.pay", "invoice", "inv_1", 100.0, {})
    assert gate.same_action(row, "invoices.pay", "invoice", "inv_1", 100.004, {})  # sub-cent float noise
    assert not gate.same_action(row, "invoices.approve", "invoice", "inv_1", 100.0, {})
    assert not gate.same_action(row, "invoices.pay", "invoice", "inv_2", 100.0, {})
    assert not gate.same_action(row, "invoices.pay", "invoice", "inv_1", 101.0, {})
    assert not gate.same_action(row, "invoices.pay", "invoice", "inv_1", None, {})
    gl = {"action": "gl.post", "entity_type": "gl_entry", "entity_id": "gl_a", "amount": Decimal("5"), "args": {"account": "6100", "debit": 5.0}}
    assert gate.same_action(gl, "gl.post", "gl_entry", "gl_b", 5.0, {"account": "6100", "debit": 5.0})  # each attempt mints a new id
    assert not gate.same_action(gl, "gl.post", "gl_entry", "gl_b", 5.0, {"account": "7000", "debit": 5.0})
