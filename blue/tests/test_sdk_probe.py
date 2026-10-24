"""Offline probe regressions only, never authenticated SDK evidence."""

import builtins
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from . import sdk_authenticated_probe as probe


def evidence():
    key = "controlled-sdk-id"
    return (
        [(key, "post_report")],
        [{"key": key, "verified": True, "source": "permission", "bound_id": key, "role": "blue"}],
        [{"tool": "post_report", "tool_use_id": key}],
        [{"tool_use_id": key, "ok": True}],
        [SimpleNamespace(tool_use_id=key, kind="report", state="confirmed")],
    )


def test_missing_receipt_is_inconclusive_not_an_index_error():
    permissions, writes, calls, results, _ = evidence()
    assert not probe._binding_matches(permissions, writes, calls, results, [])


def test_complete_controlled_binding():
    assert probe._binding_matches(*evidence())


@pytest.mark.parametrize("index", range(5))
@pytest.mark.parametrize("duplicate", [False, True])
def test_missing_or_duplicate_evidence_never_qualifies(index, duplicate):
    items = list(evidence())
    items[index] = items[index] * 2 if duplicate else []
    assert not probe._binding_matches(*items)


@pytest.mark.parametrize(
    "index,field,value",
    [
        (1, "key", ""),
        (1, "verified", False),
        (1, "source", "local"),
        (1, "source", "explicit"),
        (1, "bound_id", "different"),
        (1, "role", "green"),
        (2, "tool", "day_activity"),
        (2, "tool_use_id", "different"),
        (3, "tool_use_id", "different"),
        (3, "ok", False),
        (4, "tool_use_id", "different"),
        (4, "kind", "flag"),
        (4, "state", "unknown"),
    ],
)
def test_inconsistent_evidence_is_not_binding(index, field, value):
    items = evidence()
    if index == 4:
        setattr(items[index][0], field, value)
    else:
        items[index][0][field] = value
    assert not probe._binding_matches(*items)


def complete_output():
    return {
        "stages": ["actual_session_ids_matched"],
        "turn_ok": True,
        "factory_credits": 1,
        "permission_count": 1,
        "intercepted_report_writes": 1,
        "tool_calls": 1,
        "tool_results": 1,
        "authenticated_id_binding": True,
        "gate_during_intercepted_write": True,
        "gate_http_status": 200,
        "gate_verdict": "allow",
        "gate_ms": 2.5,
        "runtime_guard_changed": False,
        "real_ledger_or_crs_access": False,
    }


def test_controlled_qualification_requires_complete_observations():
    assert probe._failure_codes(complete_output()) == []
    assert probe._failure_codes({})


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("stages", [], "session_ids_unverified"),
        ("turn_ok", False, "turn_not_successful"),
        ("permission_count", 0, "permission_count_not_one"),
        ("intercepted_report_writes", 2, "intercepted_report_writes_not_one"),
        ("tool_calls", 0, "tool_calls_not_one"),
        ("tool_results", 2, "tool_results_not_one"),
        ("authenticated_id_binding", False, "authenticated_id_binding_unverified"),
        ("gate_during_intercepted_write", False, "gate_during_intercepted_write_unverified"),
        ("gate_http_status", 403, "gate_not_allowed"),
        ("gate_verdict", "block", "gate_not_allowed"),
        ("gate_ms", None, "gate_latency_unqualified"),
        ("gate_ms", 8000, "gate_latency_unqualified"),
        ("gate_ms", -1, "gate_latency_unqualified"),
        ("gate_ms", float("nan"), "gate_latency_unqualified"),
        ("gate_ms", float("inf"), "gate_latency_unqualified"),
        ("gate_ms", True, "gate_latency_unqualified"),
        ("factory_credits", None, "usage_unavailable"),
        ("factory_credits", float("nan"), "usage_unavailable"),
        ("cleanup_pending", True, "turn_cleanup_incomplete"),
        ("error_type", "TimeoutError", "probe_exception"),
        ("runtime_guard_changed", True, "probe_isolation_unqualified"),
        ("real_ledger_or_crs_access", True, "probe_isolation_unqualified"),
    ],
)
def test_partial_or_invalid_probe_output_is_inconclusive(field, value, code):
    output = complete_output() | {field: value}
    assert code in probe._failure_codes(output)


@pytest.mark.parametrize(
    "summary,code",
    [
        ("turn timed out: private-prose", "turn_timeout"),
        ("strict identity: private-prose", "strict_identity_failure"),
        ("droid turn ended: private-prose", "sdk_unsuccessful_result"),
        ("Live audit unavailable: private-prose", "runtime_guard_reached"),
        ("private-prose", "turn_not_successful"),
    ],
)
def test_turn_failure_codes_never_publish_raw_errors(summary, code):
    assert probe._turn_failure(SimpleNamespace(ok=False, summary=summary)) == code
    assert probe._turn_failure(RuntimeError(summary)) == code
    assert probe._turn_failure(SimpleNamespace(ok=True)) is None


def test_empty_timeout_preserves_its_failure_kind():
    assert probe._turn_failure(TimeoutError()) == "turn_timeout"


def test_model_opt_in_is_checked_before_runtime_imports(monkeypatch):
    original = builtins.__import__

    def forbid_runtime(name, *args, **kwargs):
        assert name not in {"droid_sdk", "httpx", "respx"}
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", forbid_runtime)
    with pytest.raises(SystemExit) as error:
        probe.main([])
    assert error.value.code == 2


def test_failed_shared_turn_keeps_stages_without_sdk_or_raw_prose(monkeypatch, capsys):
    from agentkit import DroidAgent
    from audit import tools

    async def fail(subject, req, emitter):
        await subject.build_prompt(req)
        raise RuntimeError("droid turn ended: private-prose")

    monkeypatch.setattr(os, "environ", os.environ.copy())
    monkeypatch.setattr(tools, "crs_client", tools.crs_client)
    monkeypatch.setattr(DroidAgent, "_droid_turn", fail)
    previous = Path.cwd()
    assert probe.main(["--allow-model-call"]) == 2
    captured = capsys.readouterr()
    output = json.loads(captured.out)
    assert output["stages"] == ["shared_sdk_entry", "synthetic_prompt_ready", "sdk_unsuccessful_result", "turn_returned"]
    assert output["permission_count"] == output["intercepted_report_writes"] == 0
    assert not output["controlled_probe_passed"] and not output["ready"]
    assert "usage_unavailable" in output["failure_codes"]
    assert not output["runtime_guard_changed"] and not output["real_ledger_or_crs_access"]
    assert "private-prose" not in captured.out + captured.err
    assert Path.cwd() == previous
