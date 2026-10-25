import builtins
import copy
import inspect
import json
import sys
from types import SimpleNamespace
from typing import get_type_hints

import httpx
import pytest
from pydantic import ConfigDict, create_model

from agentkit import ctx, make_agent_app
from agentkit.sync import TurnLock
from audit import readiness, tools
from audit.agent import AUDIT_TOOL_IDS, AuditAgent

from .audit_helpers import turn


@pytest.fixture
def fake_sdk(monkeypatch):
    """Unit double of public registry validation, not evidence about the installed SDK."""

    def tool(name, description, fn):
        hints = get_type_hints(fn)
        fields = {n: (hints[n], ...) for n in inspect.signature(fn).parameters}
        arguments = create_model("Arguments", __config__=ConfigDict(extra="forbid"), **fields)

        async def handler(values):
            return fn(**arguments.model_validate(values).model_dump())

        return SimpleNamespace(name=name, input_schema=arguments.model_json_schema(), handler=handler)

    mcp = SimpleNamespace(tool=tool, create_sdk_mcp_server=lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setitem(sys.modules, "droid_sdk", SimpleNamespace(Session=forbid))
    monkeypatch.setitem(sys.modules, "droid_sdk.mcp", mcp)
    return mcp


def forbid(*args, **kwargs):
    raise AssertionError("No SDK session, probe or external request is permitted")


@pytest.mark.parametrize("available", [False, True])
def test_availability_unlocks_live_audit_after_acceptance(available):
    status = readiness.live_readiness(sdk_available=available)
    assert status.sdk_available is available and status.ready is available
    assert readiness.LIVE_BLOCKERS == ()
    assert status.reason_codes == (() if available else ("sdk_unavailable",))


async def test_actual_shared_registry_construction_with_unit_sdk(fake_sdk, runtime):
    _, ledger, emitter = runtime()
    agent = readiness._offline_agent()
    report = await readiness.inspect_registry(agent)
    assert report["status"] == "registered" and report["extra_metadata_rejected"]
    assert {r["name"] for r in report["tools"]} == set(readiness.PARAMETERS)
    assert all(r["schema_matches"] for r in report["tools"])
    assert agent._tool_ids == list(AUDIT_TOOL_IDS)  # Pinned literals, live-verified (#119).
    assert not ledger.writes and not ledger.read_counts and not emitter.calls
    assert (await agent.health())["droid_ok"] is False  # Health never probes; see agent.py.
    assert readiness.live_readiness(sdk_available=True).ready is True


@pytest.mark.parametrize("fault", ["metadata", "allow_extra", "required", "items", "duplicate"])
async def test_registry_malformed_schema_is_not_ready(fake_sdk, monkeypatch, fault):
    agent = readiness._offline_agent()
    registry = agent._mcp_server()
    item = next(t for t in registry.tools if t.name == "freeze_vendor")
    schema = copy.deepcopy(item.input_schema)
    if fault == "metadata":
        schema["properties"]["_tool_use_id"] = {"type": "string"}
    elif fault == "allow_extra":
        schema["additionalProperties"] = True
    elif fault == "required":
        schema["required"] = [[]]
    elif fault == "items":
        schema["properties"]["finding_ids"]["items"] = {"type": "integer"}
    else:
        registry.tools.append(item)
    item.input_schema = schema
    monkeypatch.setattr(agent, "_mcp_server", lambda: registry)
    report = await readiness.inspect_registry(agent)
    assert report["status"] == "schema_mismatch"
    assert "_tool_use_id" not in json.dumps(report["tools"])


@pytest.mark.parametrize("schema", [None, [], {}, {"type": "object", "properties": []}])
def test_non_schema_values_fail_conservatively(schema):
    assert readiness.schema_matches("freeze_vendor", schema) is False


async def test_registry_exception_is_sanitized(monkeypatch):
    def broken():
        raise RuntimeError("private-bank-and-key-prose")

    agent = readiness._offline_agent()
    monkeypatch.setattr(agent, "_mcp_server", broken)
    assert await readiness.inspect_registry(agent) == {"status": "registry_error", "tools": []}


async def test_shared_bridge_copies_context_but_does_not_verify_blue_identity(monkeypatch):
    monkeypatch.setattr(httpx.AsyncClient, "send", forbid)
    token = tools.INVOCATION.set("outer-diagnostic-marker")
    try:
        report = await readiness.inspect_bridge(readiness._offline_agent())
        assert report == {
            "shared_turn_bound": True,
            "shared_ledger_rebound": True,
            "shared_emitter_bound": True,
            "blue_session_propagated": True,
            "blue_invocation_propagated": True,
            "blue_tool_lock_shared": True,
            "worker_on_owner_loop": False,
            "shared_invocation_bound": True,
            "shared_invocation_source": "local",
            "shared_invocation_verified": False,
            "shared_invocation_id_distinct_from_blue_marker": True,
            "internal_id_kwarg_injected": False,
            "shared_narration_pair_recorded": True,
            "owner_heartbeat_during_call": False,
            "owner_heartbeat_after_call": True,
        }
        assert tools.SESSION.get() is None
        assert tools.INVOCATION.get() == "outer-diagnostic-marker"
        assert ctx.invocation() is None
    finally:
        tools.INVOCATION.reset(token)


async def test_bridge_probe_uses_shared_turn_lock_on_worker_loop(monkeypatch):
    monkeypatch.setattr(httpx.AsyncClient, "send", forbid)
    agent = readiness._offline_agent()
    offload = agent._offload
    locks = []

    def checked_offload(fn):
        async def checked(**kwargs):
            lock = tools.SESSION.get().tool_lock
            locks.append(lock)
            async with lock:
                assert lock.locked()
                return await fn(**kwargs)

        checked._rl_tool = fn._rl_tool
        return offload(checked)

    monkeypatch.setattr(agent, "_offload", checked_offload)
    report = await readiness.inspect_bridge(agent)
    assert len(locks) == 1 and isinstance(locks[0], TurnLock)
    assert not locks[0].locked()
    assert report["blue_tool_lock_shared"] and not report["worker_on_owner_loop"]
    assert report["shared_narration_pair_recorded"]
    assert readiness.live_readiness(sdk_available=True).ready is True


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("installed", [False, True])
async def test_health_is_truthful_without_sdk_or_probe(runtime, monkeypatch, dry_run, installed):
    monkeypatch.setitem(sys.modules, "droid_sdk", SimpleNamespace(Session=forbid) if installed else None)
    monkeypatch.setattr(AuditAgent, "_droid_available", forbid)
    monkeypatch.setattr(readiness, "offline_report", forbid)
    agent, ledger, emitter = runtime(dry_run=dry_run)
    app = make_agent_app(AuditAgent, settings=agent.s)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://blue") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "agent": "blue", "model": agent.s.droid_model, "droid_ok": False, "dry_run": dry_run}
    assert not ledger.writes and not ledger.read_counts and not emitter.calls


async def test_live_turn_delegates_to_the_shared_sdk_path(runtime, fake_sdk, monkeypatch):
    # The hard stop is lifted: a live (non-dry) turn must reach DroidAgent._droid_turn.
    from agentkit import DroidAgent

    calls: list[str] = []

    async def recording_droid_turn(self, req, emitter):
        calls.append("shared_sdk_entry")
        return "delegated", None

    monkeypatch.setattr(DroidAgent, "_droid_turn", recording_droid_turn)
    agent, ledger, emitter = runtime(dry_run=False)
    assert (await readiness.inspect_registry(agent))["status"] == "registered"
    token = tools.INVOCATION.set("offline-not-authenticated")
    try:
        result = await agent.run_turn(turn())
    finally:
        tools.INVOCATION.reset(token)
    assert calls == ["shared_sdk_entry"]
    assert "Live audit unavailable" not in result.summary
    assert agent._tool_ids == list(AUDIT_TOOL_IDS)
    assert readiness.live_readiness(sdk_available=True).ready is True


def test_cli_with_sdk_absent_is_sanitized_and_key_free(monkeypatch, capsys):
    original = builtins.__import__

    def without_sdk(name, *args, **kwargs):
        if name.startswith("droid_sdk"):
            raise ImportError("private-import-diagnostic")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_sdk)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbid)
    monkeypatch.setenv("FACTORY_API_KEY", "private-real-key-marker")
    monkeypatch.setenv("BATTLEFIELD_URL", "http://private-bank-prose.invalid")
    readiness.main()
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["ready"] is False and report["sdk_available"] is False
    assert report["registry"] == {"status": "sdk_unavailable", "tools": []}
    # Both were verified by the authorized live sessions; local availability is irrelevant.
    assert report["session_tool_ids_verified"] and report["authenticated_invocation_verified"]
    assert "private" not in captured.out + captured.err and "offline-marker" not in captured.out
