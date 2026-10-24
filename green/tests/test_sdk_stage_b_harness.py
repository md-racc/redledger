"""Keyless Stage B runner tests. Fake SDK/Ledger receipts do not qualify real-Ledger behavior."""

import builtins
import copy
import json
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS

import pytest
import sdk_stage_b_harness as h
from test_invocation_adapter import permission

import tools
from agent import AP_TOOL_IDS, GreenAgent


def install_fake(monkeypatch, *, echo=True, fault=None):
    observations = []
    monkeypatch.setattr(GreenAgent, "_mcp_server", lambda self, registry: (self, registry))

    class Event:
        pass

    class Session:
        def __init__(self, **kwargs):
            self.kw = kwargs
            observations.append(kwargs)
            assert kwargs["model"] == "gemini-3.8-flash" and kwargs["reasoning_effort"] == "low"
            config = kwargs["config"]
            assert config.restrict_tools == list(AP_TOOL_IDS) and config.autonomy == "off" and config.disable_builtin_skills is True
            assert kwargs["api_key"] is None

        async def __aenter__(self):
            if fault == "open":
                raise RuntimeError("private credential")
            return self

        async def __aexit__(self, *args):
            observations.append("closed")

        async def list_tools(self):
            return [NS(id=i) for i in AP_TOOL_IDS]

        @asynccontextmanager
        async def stream(self, prompt, **kwargs):
            assert kwargs == {"include_partial_messages": True, "timeout": h.TURN_TIMEOUT_SEC - 10}
            agent, registry = self.kw["config"].mcp_servers[0]
            assert "private" not in prompt
            if fault == "timeout":
                raise TimeoutError("private credential")
            specs = json.loads(prompt.split("once each, and no others: ")[1].split(". Stop afterwards.")[0]) if "once each" in prompt else {}
            requests = [permission(tool, "sdk-" + tool, args) for tool, args in specs.items()]
            if fault == "unknown_callback":
                requests.insert(0, permission("unknown", "sdk-unknown", {}))
            text = "done"
            for request in requests:
                response = await self.kw["interactions"].on_permission(request)
                if response.selected_option == "proceed_once":
                    for action in request.actions:
                        tool = action.actual_tool_name
                        out = agent._offload(getattr(tools, tool), registry=registry)(**action.tool_use.input)
                        if fault == "duplicate":
                            agent._offload(getattr(tools, tool), registry=registry)(**action.tool_use.input)
                        assert isinstance(out, str)
                else:
                    if echo:
                        text = response.comment
                    if fault == "execute_after_cancel":
                        for action in request.actions:
                            agent._offload(getattr(tools, action.actual_tool_name), registry=registry)(**action.tool_use.input)
            usage = None if fault == "usage" else NS(factory_credits=float("nan") if fault == "nan" else 1.0, input_tokens=1, output_tokens=1)

            class Stream:
                result = NS(text=text, success=fault != "failed", subtype="synthetic_failure", usage=usage)

                def __aiter__(self):
                    return self

                async def __anext__(self):
                    raise StopAsyncIteration

            yield Stream()

    sdk = NS(
        Session=Session,
        SessionConfig=lambda **kw: NS(**kw),
        InteractionHandlers=lambda **kw: NS(**kw),
        ReasoningEffort=lambda value: value,
        Autonomy=NS(OFF="off", LOW="low", MEDIUM="medium", HIGH="high"),
        ToolConfirmationOutcome=NS(CANCEL="cancel", PROCEED_ONCE="proceed_once"),
        **{name: type(name, (Event,), {}) for name in ("TextDelta", "ThinkingDelta", "ToolCall", "ToolCallDelta", "ToolResult")},
    )
    monkeypatch.setitem(sys.modules, "droid_sdk", sdk)
    return observations


@pytest.mark.parametrize("case", h.CASES)
async def test_all_stage_b_cases_pass_with_case_invariants(monkeypatch, case):
    observations = install_fake(monkeypatch)
    e = await h.run_case(case)
    assert e["passed"], e
    assert len([x for x in observations if isinstance(x, dict)]) == 1 and observations[-1] == "closed"
    assert len(e["permissions"]) == len(e["calls"]) == len(e["results"]) == 1
    assert len(e["preparations"]) == 1  # pay_invoice is a mutation: every mode prepares.
    blocked = case in h.BLOCK_CAUSE
    assert len(e["writes"]) == (0 if blocked else 1)
    assert e["consumed"] is (not blocked)
    assert e["payments"] == (0 if blocked else 1) and e["mutated"] is (not blocked)
    assert e["permissions"][0]["outcome"] == ("cancel" if blocked else "proceed_once")
    assert "fixture-" not in json.dumps(e) and "private" not in json.dumps(e)


async def test_blocked_case_fixtures_and_causes_stay_distinct(monkeypatch):
    install_fake(monkeypatch)
    block = await h.run_case("enforce_block")
    timeout = await h.run_case("enforce_escalation_timeout")
    assert block["results"][0]["cause"] == "control_hold"
    assert timeout["results"][0]["cause"] == "escalation_timeout"
    assert block["preparations"][0]["decided_by"] == "gate" and not block["preparations"][0]["escalation"]
    assert timeout["preparations"][0]["decided_by"] == "timeout" and timeout["preparations"][0]["escalation"]
    for e in (block, timeout):
        assert e["payments"] == 0 and not e["writes"] and e["mutated"] is False and e["consumed"] is False
        assert e["results"][0]["reason_match"] is True and e["nonce_delivered"] is True


async def test_shadow_records_would_block_but_executes(monkeypatch):
    install_fake(monkeypatch)
    e = await h.run_case("shadow_effective_allow")
    assert e["passed"], e
    prep = e["preparations"][0]
    assert (prep["verdict"], prep["effective"], prep["enforced"], prep["decided_by"]) == ("block", "allow", False, "gate")
    assert prep["verdict_id"] and prep["reason"] and prep["cause"] == "control"
    assert e["writes"][0]["consumed"] is True and e["payments"] == 1


@pytest.mark.parametrize("echo", [True, False])
async def test_block_comment_requires_nonce_delivery(monkeypatch, echo):
    install_fake(monkeypatch, echo=echo)
    e = await h.run_case("enforce_block")
    assert e["passed"] is echo and e["nonce_delivered"] is echo
    assert ("cancel_comment_unobserved" in e["failure_codes"]) is not echo
    assert not e["writes"] and not e["payments"] and e["mutated"] is False


async def test_unknown_callback_cancels_everything_and_cannot_pass(monkeypatch):
    install_fake(monkeypatch, fault="unknown_callback")
    e = await h.run_case("enforce_block")
    assert e["shape"] == [(1, 0), (1, 1)]
    assert not e["passed"] and "unexpected_permission_callback" in e["failure_codes"]
    assert not e["preparations"] and not e["writes"] and not e["payments"] and e["mutated"] is False


async def test_execution_after_cancel_never_reaches_ledger(monkeypatch):
    install_fake(monkeypatch, fault="execute_after_cancel")
    e = await h.run_case("enforce_block")
    assert not e["passed"] and e["failure_codes"]
    assert not e["writes"] and not e["payments"] and e["mutated"] is False
    assert len(e["preparations"]) == 1 and e["consumed"] is False


@pytest.mark.parametrize("fault", ["open", "timeout", "usage", "nan", "failed", "duplicate"])
async def test_runner_failures_never_pass_or_disclose_exception(monkeypatch, fault):
    install_fake(monkeypatch, fault=fault)
    e = await h.run_case("off_allow")
    assert not e["passed"] and e["failure_codes"]
    assert "private" not in json.dumps(e, allow_nan=False)
    if fault in ("open", "timeout"):
        assert not e["writes"] and not e["payments"]


@pytest.mark.parametrize(
    ("case", "field", "value"),
    [
        ("off_allow", "decided_by", "gate"),
        ("off_allow", "verdict", "block"),
        ("shadow_effective_allow", "verdict", "allow"),
        ("shadow_effective_allow", "verdict_id", False),
        ("shadow_effective_allow", "reason", False),
        ("enforce_block", "decided_by", "mode"),
        ("enforce_block", "effective", "allow"),
        ("enforce_escalation_timeout", "decided_by", "gate"),
        ("enforce_escalation_timeout", "verdict", "block"),
        ("enforce_escalation_timeout", "escalation", False),
    ],
)
async def test_wrong_preparation_semantics_fail(monkeypatch, case, field, value):
    install_fake(monkeypatch)
    e = await h.run_case(case)
    assert not h.failure_codes(e)
    e["preparations"][0][field] = value
    assert "preparation_semantics" in h.failure_codes(e)


@pytest.mark.parametrize(
    ("case", "wrong"),
    [("enforce_block", "escalation_timeout"), ("enforce_escalation_timeout", "control_hold")],
)
async def test_swapped_cancel_causes_fail(monkeypatch, case, wrong):
    install_fake(monkeypatch)
    e = await h.run_case(case)
    assert e["results"][0]["cause"] == h.BLOCK_CAUSE[case]
    e["results"][0]["cause"] = wrong
    assert "cancel_cause" in h.failure_codes(e)


@pytest.mark.parametrize(
    "tamper",
    [
        "missing",
        "field",
        "duplicate",
        "wrongid",
        "unverified",
        "args",
        "outcome",
        "write_after_block",
        "preparation_missing",
        "consumed_early",
        "payments",
        "mutation",
        "usage",
        "nan",
        "reason",
    ],
)
async def test_evaluator_rejects_tampered_blocked_evidence(monkeypatch, tamper):
    install_fake(monkeypatch)
    valid = await h.run_case("enforce_block")
    assert not h.failure_codes(valid)
    e = copy.deepcopy(valid)
    if tamper == "missing":
        e["results"] = []
    elif tamper == "field":
        del e["results"]
    elif tamper == "duplicate":
        e["calls"] *= 2
    elif tamper == "wrongid":
        e["preparations"][0]["id"] = "other"
    elif tamper == "unverified":
        e["permissions"][0]["source"] = "local"
    elif tamper == "args":
        e["permissions"][0]["args_match"] = False
    elif tamper == "outcome":
        e["permissions"][0]["outcome"] = "proceed_once"
    elif tamper == "write_after_block":
        e["writes"].append({"id": e["permissions"][0]["id"], "binding": True, "verified": True, "consumed": True})
    elif tamper == "preparation_missing":
        e["preparations"] = []
    elif tamper == "consumed_early":
        e["consumed"] = True
    elif tamper == "payments":
        e["payments"] = 1
    elif tamper == "mutation":
        e["mutated"] = True
    elif tamper == "usage":
        e["credits"] = None
    elif tamper == "nan":
        e["credits"] = float("nan")
    elif tamper == "reason":
        e["results"][0]["reason_match"] = False
    assert h.failure_codes(e)


@pytest.mark.parametrize("tamper", ["duplicate_write", "replayed_write", "unverified_write", "consumption", "preparation_dropped"])
async def test_evaluator_rejects_tampered_allow_evidence(monkeypatch, tamper):
    install_fake(monkeypatch)
    valid = await h.run_case("off_allow")
    assert not h.failure_codes(valid)
    e = copy.deepcopy(valid)
    if tamper == "duplicate_write":
        e["writes"] *= 2
    elif tamper == "replayed_write":
        e["writes"].append({"id": e["permissions"][0]["id"], "binding": False, "verified": True, "consumed": False})
    elif tamper == "unverified_write":
        e["writes"][0]["verified"] = False
    elif tamper == "consumption":
        e["consumed"] = False
    elif tamper == "preparation_dropped":
        e["preparations"] = []
    assert h.failure_codes(e)


def test_help_is_keyless_and_exits_zero_before_any_sdk_access(monkeypatch):
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        assert name not in ("droid_sdk", "agent", "agentkit", "httpx", "respx")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    monkeypatch.setattr(h.os.environ, "pop", lambda *a: pytest.fail("auth touched"))
    monkeypatch.setattr(h, "run_case", lambda *a: pytest.fail("runner touched"))
    with pytest.raises(SystemExit) as exc:
        h.main(["--help"])
    assert exc.value.code == 0


@pytest.mark.parametrize(
    "flags",
    [
        [],
        ["--allow-model-call"],
        ["--operator-approval", "yes"],
        ["--allow-model-call", "--operator-approval", "yes"],
        ["--allow-model-call", "--operator-approval", "yes", "--spend-cap-attestation", h.ATTESTATION],
        ["--allow-model-call", "--operator-approval", "yes", "--isolated-ledger", "http://isolated.invalid"],
        ["--operator-approval", "yes", "--spend-cap-attestation", h.ATTESTATION, "--isolated-ledger", "http://isolated.invalid"],
        ["--allow-model-call", "--operator-approval", "  ", "--spend-cap-attestation", h.ATTESTATION, "--isolated-ledger", "http://isolated.invalid"],
        ["--allow-model-call", "--operator-approval", "yes", "--spend-cap-attestation", h.ATTESTATION, "--isolated-ledger", " "],
    ],
)
def test_missing_gates_refuse_before_imports_auth_settings_network(monkeypatch, flags):
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        assert name not in ("droid_sdk", "agent", "agentkit", "httpx", "respx")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    monkeypatch.setattr(h.os.environ, "pop", lambda *a: pytest.fail("auth touched"))
    monkeypatch.setattr(h, "run_case", lambda *a: pytest.fail("runner touched"))
    with pytest.raises(SystemExit) as exc:
        h.main(["--case", "off_allow", *flags])
    assert exc.value.code == 2


def test_default_invocation_without_case_refuses_keyless(monkeypatch):
    monkeypatch.setattr(h, "run_case", lambda *a: pytest.fail("runner touched"))
    with pytest.raises(SystemExit) as exc:
        h.main([])
    assert exc.value.code == 2
