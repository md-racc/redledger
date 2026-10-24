"""Keyless runner tests. Fake SDK receipts do not qualify live SDK behavior."""

import builtins
import copy
import json
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS

import pytest
import sdk_acceptance_harness as h
from test_invocation_adapter import permission

import tools
from agent import AP_TOOL_IDS, GreenAgent


def install_fake(monkeypatch, *, batch=False, echo=True, fault=None, isolated=True):
    observations = []
    monkeypatch.setattr(GreenAgent, "_mcp_server", lambda self, registry: (self, registry))
    # Fake runs cannot create the harness's disposable cwd; simulate the observation only.
    monkeypatch.setattr(h, "_isolated_cwd", lambda: isolated)

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
            return [NS(id=i) for i in AP_TOOL_IDS[: -1 if fault == "listing" else None]]

        @asynccontextmanager
        async def stream(self, prompt, **kwargs):
            assert kwargs == {"include_partial_messages": True, "timeout": 35}
            agent, registry = self.kw["config"].mcp_servers[0]
            assert "private" not in prompt
            if fault == "timeout":
                raise TimeoutError("private credential")
            specs = json.loads(prompt.split("once each, and no others: ")[1].split(". Stop afterwards.")[0]) if "once each" in prompt else {}
            requests = [permission(tool, "sdk-" + tool, args) for tool, args in specs.items()]
            if fault == "unknown_callback":
                requests.insert(0, permission("unknown", "sdk-unknown", {}))
            if batch and requests:
                requests[0].actions += requests[1].actions
                requests = requests[:1]
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
                elif echo:
                    text = response.comment
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


@pytest.mark.parametrize("tool", h.TOOLS)
async def test_all_ap_fixtures_through_shared_sdk_entry(monkeypatch, tool):
    observations = install_fake(monkeypatch)
    e = await h.run_case(tool)
    assert e["passed"], e
    assert len([x for x in observations if isinstance(x, dict)]) == 1 and observations[-1] == "closed"
    assert len(e["permissions"]) == len(e["calls"]) == len(e["results"]) == 1
    assert len(e["preparations"]) == len(e["writes"]) == int(tool != "ap_queue")
    assert "fixture-" not in json.dumps(e) and "private" not in json.dumps(e)


@pytest.mark.parametrize("echo", [True, False])
async def test_cancel_comment_requires_nonce_delivery(monkeypatch, echo):
    install_fake(monkeypatch, echo=echo)
    e = await h.run_case("cancel")
    assert e["passed"] is echo and e["nonce_delivered"] is echo
    assert not e["writes"] and not e["mutated"]
    assert e["results"][0]["ok"] is False and e["results"][0]["cause"] == "control_hold"
    assert ("cancel_comment_unobserved" in e["failure_codes"]) is not echo


@pytest.mark.parametrize("batch", [True, False])
async def test_granularity_never_partially_prepares_batch(monkeypatch, batch):
    install_fake(monkeypatch, batch=batch)
    e = await h.run_case("granularity")
    assert e["passed"], e
    assert e["batch"] is batch and len(e["preparations"]) == (0 if batch else 2)
    assert not e["writes"] and not e["mutated"] and len(e["results"]) == 2


async def test_restriction_empty_trace_is_inconclusive(monkeypatch):
    observations = install_fake(monkeypatch)
    e = await h.run_case("restriction")
    assert not e["passed"] and e["failure_codes"] == ["restriction_inconclusive_no_observable_sdk_refusal"]
    assert not e["calls"] and not e["writes"]
    assert not observations  # No billable Session for a case that cannot establish acceptance.


async def test_unknown_callback_refuses_later_execution_and_cannot_pass(monkeypatch):
    install_fake(monkeypatch, fault="unknown_callback")
    e = await h.run_case("pay_invoice")
    assert e["shape"] == [(1, 0), (1, 1)]
    assert not e["passed"] and "unexpected_permission_callback" in e["failure_codes"]
    assert not e["preparations"] and not e["writes"] and not e["mutated"]


async def test_isolation_is_observed_not_assumed(monkeypatch):
    install_fake(monkeypatch, isolated=False)
    e = await h.run_case("pay_invoice")
    assert e["isolated"] is False and not e["passed"] and "isolated_unverified" in e["failure_codes"]


async def test_parallel_evidence_correlates_by_id_not_arrival_order(monkeypatch):
    install_fake(monkeypatch)
    e = await h.run_case("granularity")
    for field in ("calls", "results", "preparations", "writes"):
        e[field].reverse()
    assert not h.failure_codes(e)
    e["preparations"][0] = e["preparations"][1].copy()
    assert "preparation_binding" in h.failure_codes(e)


@pytest.mark.parametrize("fault", ["open", "listing", "timeout", "usage", "nan", "failed", "duplicate"])
async def test_runner_failures_never_pass_or_disclose_exception(monkeypatch, fault):
    install_fake(monkeypatch, fault=fault)
    e = await h.run_case("pay_invoice")
    assert not e["passed"] and e["failure_codes"]
    assert "private" not in json.dumps(e, allow_nan=False)
    if fault in ("open", "listing", "timeout"):
        assert not e["writes"]


@pytest.mark.parametrize(
    "tamper", ["missing", "field", "duplicate", "wrongid", "unverified", "truthy", "wrongtool", "failed", "nan", "binding", "mutation", "callback"]
)
async def test_evaluator_rejects_tampered_evidence(monkeypatch, tamper):
    install_fake(monkeypatch)
    valid = await h.run_case("pay_invoice")
    assert not h.failure_codes(valid)
    e = copy.deepcopy(valid)
    if tamper == "missing":
        e["results"] = []
    elif tamper == "field":
        del e["results"]
    elif tamper == "duplicate":
        e["calls"] *= 2
    elif tamper == "wrongid":
        e["writes"][0]["id"] = "other"
    elif tamper == "unverified":
        e["writes"][0]["verified"] = False
    elif tamper == "truthy":
        e["writes"][0]["verified"] = 1
    elif tamper == "wrongtool":
        e["permissions"][0]["tool"] = "pay_expense"
    elif tamper == "failed":
        e["results"][0]["ok"] = False
    elif tamper == "nan":
        e["credits"] = float("nan")
    elif tamper == "binding":
        e["permissions"][0]["args_match"] = False
    elif tamper == "mutation":
        e["mutated"] = False
    elif tamper == "callback":
        e["shape"].insert(0, (1, 0))
    assert h.failure_codes(e)


@pytest.mark.parametrize("flags", [[], ["--allow-model-call"], ["--operator-approval", "yes"], ["--allow-model-call", "--operator-approval", "yes"]])
def test_default_refuses_before_imports_auth_settings_network(monkeypatch, flags):
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        assert name not in ("droid_sdk", "agent", "agentkit", "httpx", "respx")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    monkeypatch.setattr(h.os.environ, "pop", lambda *a: pytest.fail("auth touched"))
    monkeypatch.setattr(h, "run_case", lambda *a: pytest.fail("runner touched"))
    with pytest.raises(SystemExit) as exc:
        h.main(["--case", "pay_invoice", *flags])
    assert exc.value.code == 2
