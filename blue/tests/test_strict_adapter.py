"""Offline strict-policy wiring only; no installed SDK, model or live guard bypass."""

import json
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest

from agentkit import DroidAgent
from agentkit.config import AgentSettings
from agentkit.invocation import current_registry, strict_identity
from audit import tools
from audit.agent import AUDIT_TOOL_IDS, AuditAgent

from .audit_helpers import FakeLedger, bound_session, turn
from .test_shared_invocation import SDK_ID, shared_bridge

EXPECTED = (
    "blue-ledger___benford_check",
    "blue-ledger___crs_identity_check",
    "blue-ledger___day_activity",
    "blue-ledger___freeze_vendor",
    "blue-ledger___post_report",
    "blue-ledger___raise_flag",
    "blue-ledger___vendor_dedupe",
)


def agent(*, dry_run=False):
    return AuditAgent(AgentSettings(AGENT_NAME="blue", DRY_RUN=dry_run, DROID_MODEL="unit-test-only", FACTORY_API_KEY="", _env_file=None))


@pytest.fixture(autouse=True)
def no_external_http(monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("No external HTTP in strict adapter tests")

    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)


@pytest.fixture
def sdk(monkeypatch):
    """Public surface double: never imports SDK, starts listeners or executes tools."""
    state = SimpleNamespace(ids=list(EXPECTED), error=None, configs=[], trace=[])
    once = object()

    class Config(SimpleNamespace):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            state.trace.append("config")
            state.configs.append(self)

    class Session:
        def __init__(self, **kwargs):
            assert kwargs["model"] == "unit-test-only"
            assert kwargs["config"] is state.configs[-1]
            state.trace.append("session")

        async def __aenter__(self):
            assert strict_identity() and current_registry().require_permission
            return self

        async def __aexit__(self, *args):
            return None

        async def list_tools(self):
            state.trace.append("list")
            if state.error:
                raise state.error
            return [SimpleNamespace(id=value) for value in state.ids]

        @asynccontextmanager
        async def stream(self, prompt, **kwargs):
            state.trace.append("stream")
            assert kwargs == {"include_partial_messages": True, "timeout": 170}

            class Stream:
                result = SimpleNamespace(usage=None, success=True, text="synthetic")

                async def __aiter__(self):
                    for event in ():
                        yield event

            yield Stream()

    module = SimpleNamespace(
        Session=Session,
        SessionConfig=Config,
        InteractionHandlers=SimpleNamespace,
        Autonomy=SimpleNamespace(OFF="off", LOW="low", MEDIUM="medium", HIGH="high"),
        ToolConfirmationOutcome=SimpleNamespace(PROCEED_ONCE=once),
        ReasoningEffort=lambda value: value,
    )
    for name in ("TextDelta", "ThinkingDelta", "ToolCall", "ToolCallDelta", "ToolResult"):
        setattr(module, name, type(name, (), {}))
    monkeypatch.setitem(sys.modules, "droid_sdk", module)
    monkeypatch.setitem(
        sys.modules,
        "droid_sdk.mcp",
        SimpleNamespace(tool=lambda n, d, f: (n, d, f), create_sdk_mcp_server=lambda **kwargs: SimpleNamespace(**kwargs)),
    )
    state.once = once
    return state


def test_explicit_policy_and_literal_lists_are_isolated_without_sdk(monkeypatch):
    monkeypatch.setitem(sys.modules, "droid_sdk", None)
    first, second = agent(), agent()
    assert first.autonomy == "off" and first.identity == first.identity_policy() == "strict"
    assert first._strict_live() and not agent(dry_run=True)._strict_live()
    assert AUDIT_TOOL_IDS == EXPECTED
    assert first._tool_ids == second._tool_ids == list(EXPECTED)
    first._tool_ids.clear()
    expected = first._expected_tool_ids()
    expected.clear()
    monkeypatch.setattr(first, "tools", lambda: [("unexpected_tool", "", None)])
    assert first._expected_tool_ids() == second._tool_ids == list(EXPECTED)
    assert AuditAgent._learn_tool_ids is DroidAgent._learn_tool_ids


async def test_permission_always_responds_proceed_once(sdk):
    responses = []
    request = SimpleNamespace(respond=lambda value: responses.append(value) or value)
    for _ in range(3):
        assert await agent().on_permission(request) is sdk.once
    assert responses == [sdk.once] * 3


async def shared_turn(subject):
    # Explicit shared entry only in this synthetic test context, never AuditAgent's runtime.
    async with bound_session(FakeLedger(), dry_run=False) as (_, emitter):
        return await DroidAgent._droid_turn(subject, turn(), emitter)


async def test_first_config_pins_exact_ids_and_each_turn_revalidates(sdk):
    subject = agent()
    sdk.ids = list(reversed(EXPECTED)) + ["Read", "other-ledger___unrelated"]
    for _ in range(2):
        assert await shared_turn(subject) == ("synthetic", None)
        assert subject._tool_ids == list(EXPECTED)
    assert sdk.trace == ["config", "session", "list", "stream"] * 2
    assert all(config.restrict_tools == list(EXPECTED) for config in sdk.configs)
    assert all(config.autonomy == "off" and config.disable_builtin_skills for config in sdk.configs)
    # A cached successful list must not skip the next strict-live check.
    sdk.ids.remove("blue-ledger___crs_identity_check")
    with pytest.raises(RuntimeError, match="missing"):
        await shared_turn(subject)
    assert sdk.trace[-3:] == ["config", "session", "list"]


@pytest.mark.parametrize("fault", ["missing", "extra", "lookalike", "list_error"])
async def test_bad_list_refuses_before_stream(sdk, fault):
    if fault == "missing":
        sdk.ids.remove("blue-ledger___crs_identity_check")
    elif fault == "extra":
        sdk.ids.append("blue-ledger___unexpected")
    elif fault == "lookalike":
        sdk.ids[0] = "blue-ledger___xbenford_check"
    else:
        sdk.error = RuntimeError("synthetic listing failure")
    with pytest.raises(RuntimeError, match="strict identity"):
        await shared_turn(agent())
    assert sdk.trace == ["config", "session", "list"]
    assert sdk.configs[0].restrict_tools == list(EXPECTED)


async def test_approved_permission_identity_matches_write_receipt_and_events(monkeypatch, sdk):
    async with shared_bridge(monkeypatch) as (subject, session, emitter, requests, _):
        registry = subject._new_registry(emitter)
        action = SimpleNamespace(
            confirmation_type="mcp_tool",
            server_name="blue-ledger",
            actual_tool_name="post_report",
            tool_use=SimpleNamespace(id=SDK_ID, input={}),
        )
        request = SimpleNamespace(
            actions=[action],
            options=[SimpleNamespace(value=sdk.once)],
            respond=lambda value: SimpleNamespace(selected_option=value),
        )
        await subject._permission_entry(registry, request)
        assert json.loads(subject._offload(tools.post_report, registry=registry)())["ok"]
        # The approved identity cannot authorize a second execution.
        assert json.loads(subject._offload(tools.post_report, registry=registry)())["not_run"]
        registry.close()
        assert len(requests) == len(session.effects) == 1
        assert requests[0][0].headers["X-Tool-Use-Id"] == session.effects[0].tool_use_id == SDK_ID
        assert [e["payload"]["tool_use_id"] for e in emitter.events[:2]] == [SDK_ID, SDK_ID]
        assert emitter.events[1]["payload"]["ok"] is True


@pytest.mark.parametrize("source", ["unapproved_stream", "ambiguous", "local", "explicit"])
async def test_untrusted_or_ambiguous_metadata_has_no_blue_effects(monkeypatch, source):
    async with shared_bridge(monkeypatch) as (subject, session, emitter, requests, _):
        registry = subject._new_registry(emitter)
        for key in ["one", "two"] if source == "ambiguous" else ["one"]:
            registry.observe(key, "blue-ledger___post_report", {}, source if source in {"local", "explicit"} else "stream")
            if source != "unapproved_stream":
                registry.permission_resolved(key, approved=True)
        output = json.loads(subject._offload(tools.post_report, registry=registry)())
        assert output.get("not_run") or output.get("ok") is False
        registry.close()
        assert not requests and not session.effects
        assert all(not event["payload"]["ok"] for event in emitter.events if event["type"] == "agent.tool_result")


async def test_keyless_dry_run_retains_uuid4_events_and_receipts(runtime, monkeypatch):
    monkeypatch.setitem(sys.modules, "droid_sdk", None)
    subject, ledger, emitter = runtime(dry_run=True)
    assert (await subject.run_turn(turn())).ok
    ids = [call[2] for call in emitter.calls]
    assert ids and len(ids) == len(set(ids)) and all(UUID(key).version == 4 for key in ids)
    assert [result[0] for result in emitter.results] == ids
    effects = subject.receipts[("ep", 5)]
    assert [effect.tool_use_id for effect in effects] == [write[2] for write in ledger.writes]
    assert effects and all(effect.tool_use_id in ids and effect.state == "confirmed" for effect in effects)


async def test_live_turn_runs_the_shared_sdk_session(runtime, sdk, monkeypatch):
    # Guard lifted: a live turn must enter the shared SDK session (strict identity is
    # asserted inside the sdk double) instead of raising the retired hard stop.
    subject, ledger, emitter = runtime(dry_run=False)
    monkeypatch.setattr(subject.s, "droid_model", "unit-test-only")
    result = await subject.run_turn(turn())
    assert sdk.trace[:2] == ["config", "session"] and "stream" in sdk.trace
    assert "Live audit unavailable" not in result.summary
    assert not ledger.writes  # The synthetic stream issues no tool calls.
    assert (await subject.health())["droid_ok"] is False  # Health never probes the SDK.
