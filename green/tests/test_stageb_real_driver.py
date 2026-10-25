"""Keyless unit tests for the Stage B real-Ledger driver (stageb_real_driver.py).

Everything here is pure: canned operator payloads (events, audit rows, book reads) feed
collect_evidence/failure_codes; run() is exercised only through its env/health refusal paths with
probe_battlefield/green_health monkeypatched. No network, no subprocess, no SDK, no credits.
"""

import json
import re
from types import SimpleNamespace as NS

import pytest
import stageb_real_driver as d

MARKER = "deadbeef"
REASON = "nonce-1"


# ---------- canned operator payloads ----------


def _call(key, tool="pay_expense", entity="exp-t1"):
    return {"type": "agent.tool_call", "agent": "green", "payload": {"tool": tool, "args": {"expense_id": entity}, "tool_use_id": key}}


def _result_ok(key):
    return {"type": "agent.tool_result", "agent": "green", "payload": {"tool_use_id": key, "ok": True, "summary": json.dumps({"outcome": "confirmed"})}}


def _result_cancel(key, cause, reason=REASON):
    comment = json.dumps({"cause": cause, "reason": reason, "verdict_cause": "control"})
    summary = json.dumps({"cancelled": True, "tool": "pay_expense", "reason": comment})
    return {"type": "agent.tool_result", "agent": "green", "payload": {"tool_use_id": key, "ok": False, "summary": summary}}


def _verdict(vid, verdict, entity, enforced, reason=REASON):
    return {
        "type": "gate.verdict",
        "payload": {
            "verdict_id": vid,
            "agent": "green",
            "action": "expenses.pay",
            "entity_type": "expense",
            "entity_id": entity,
            "amount": 42.0,
            "verdict": verdict,
            "reason": reason,
            "confidence": 1.0,
            "rules_fired": ["employee_eligibility"] if verdict != "allow" else [],
            "enforced": enforced,
            "cause": "control",
            "preparation_id": f"prep-{vid}",
        },
    }


def _mutation(entity, prep_id, verdict_id="v-1"):
    return {
        "type": "ledger.mutation",
        "payload": {
            "agent": "green",
            "action": "expenses.pay",
            "entity_type": "expense",
            "entity_id": entity,
            "amount": 42.0,
            "verdict_id": verdict_id,
            "preparation_id": prep_id,
        },
    }


def _turn(credits=1.25, ok=True, agent="green"):
    return {"type": "turn.ended", "payload": {"agent": agent, "ok": ok, "summary": "day done", "duration_sec": 12.0, "factory_credits": credits}}


def _esc_opened(esc_id="esc-1", vid="v-1", prep_id="prep-v-1"):
    return {"type": "escalation.opened", "payload": {"escalation_id": esc_id, "verdict_id": vid, "cause": "control", "preparation_id": prep_id}}


def _esc_resolved(esc_id="esc-1", decision="timeout"):
    return {"type": "escalation.resolved", "payload": {"escalation_id": esc_id, "decision": decision, "by": "timeout"}}


def _prep_row(key, effective, verdict_id=None, entity="exp-t1", prep_id=None, action="expenses.pay"):
    return {
        "agent": "green",
        "action": f"prepare:{action}",
        "tool_use_id": key,
        "http_status": 200,
        "args": {"action": action, "entity_type": "expense", "entity_id": entity, "amount": 42.0},
        "result": {"preparation_id": prep_id or f"prep-{key}", "effective": effective},
        "verdict_id": verdict_id,
    }


def _write_row(key, entity="exp-t1", action="expenses.pay", status=200):
    return {"agent": "green", "action": action, "tool_use_id": key, "http_status": status, "args": {"id": entity}, "result": {"status": "paid"}}


def mk_raw(case):
    """(events, audit_rows, target_ids, target_status) for a passing run of the case."""
    if case == "off_allow":
        events = [_call("sdk-1"), _result_ok("sdk-1"), _mutation("exp-t1", "prep-sdk-1", verdict_id=None), _turn()]
        audit = [_prep_row("sdk-1", "allow"), _write_row("sdk-1")]
        return events, audit, ["exp-t1"], {"exp-t1": "paid"}
    if case == "shadow_effective_allow":
        events = [_call("sdk-1"), _result_ok("sdk-1"), _verdict("v-1", "block", "exp-t1", False), _mutation("exp-t1", "prep-v-1"), _turn()]
        audit = [_prep_row("sdk-1", "allow", verdict_id="v-1", prep_id="prep-v-1"), _write_row("sdk-1")]
        return events, audit, ["exp-t1"], {"exp-t1": "paid"}
    if case == "enforce_block":
        events = [_call("sdk-1"), _result_cancel("sdk-1", "control_hold"), _verdict("v-1", "block", "exp-t1", True), _turn()]
        audit = [_prep_row("sdk-1", "block", verdict_id="v-1", prep_id="prep-v-1")]
        return events, audit, ["exp-t1"], {"exp-t1": "blocked"}
    if case == "enforce_escalation_timeout":
        events = [
            _call("sdk-1", entity="exp-t1"),
            _call("sdk-2", entity="exp-t2"),
            _call("sdk-3", entity="exp-t3"),
            _result_cancel("sdk-1", "escalation_timeout"),
            _result_ok("sdk-2"),
            _result_ok("sdk-3"),
            _verdict("v-1", "escalate", "exp-t1", True),
            _verdict("v-2", "allow", "exp-t2", True),
            _verdict("v-3", "allow", "exp-t3", True),
            _esc_opened(),
            _esc_resolved(),
            _mutation("exp-t2", "prep-v-2", verdict_id="v-2"),
            _mutation("exp-t3", "prep-v-3", verdict_id="v-3"),
            _turn(credits=2.5),
        ]
        audit = [
            _prep_row("sdk-1", "block", verdict_id="v-1", entity="exp-t1", prep_id="prep-v-1"),
            _prep_row("sdk-2", "allow", verdict_id="v-2", entity="exp-t2", prep_id="prep-v-2"),
            _prep_row("sdk-3", "allow", verdict_id="v-3", entity="exp-t3", prep_id="prep-v-3"),
            _write_row("sdk-2", entity="exp-t2"),
            _write_row("sdk-3", entity="exp-t3"),
        ]
        targets = ["exp-t1", "exp-t2", "exp-t3"]
        return events, audit, targets, {"exp-t1": "blocked", "exp-t2": "paid", "exp-t3": "paid"}
    raise ValueError(case)


def evaluate(case):
    events, audit, targets, status = mk_raw(case)
    return d.collect_evidence(events, audit, targets, status)


def codes(case):
    return d.failure_codes(case, evaluate(case))


# ---------- fixtures ----------


def test_fixture_payloads_are_minimal_and_marked():
    for case in d.CASE_MODES:
        payload = d.fixture_payload(case, MARKER)
        assert set(payload) == {"employees", "expenses"}
        assert len(payload["employees"]) == 1
        employee = payload["employees"][0]
        assert MARKER in employee["bank_account"] and MARKER in employee["name"]
        assert employee["status"] == "active" and employee["start_day"] == 0
        assert all(e["employee_ref"] == 0 and e["submitted_day"] == 0 for e in payload["expenses"])
    assert d.fixture_payload("off_allow", MARKER)["employees"][0]["hr_record"] is True
    for case in ("shadow_effective_allow", "enforce_block"):
        # employee_eligibility (no_hr_record) makes the would-block/block deterministic.
        assert d.fixture_payload(case, MARKER)["employees"][0]["hr_record"] is False
    split = d.fixture_payload("enforce_escalation_timeout", MARKER)["expenses"]
    # threshold_split (review): three same-category parts totaling 4800, in [4750, 5000).
    assert len(split) == 3 and len({e["category"] for e in split}) == 1
    assert 4750 <= sum(e["amount"] for e in split) < 5000
    with pytest.raises(ValueError):
        d.fixture_payload("nope", MARKER)


# ---------- health classification ----------


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (None, "green_unhealthy"),
        ({"dry_run": True, "droid_ok": True}, "green_still_dry_run"),
        ({"dry_run": False, "droid_ok": False}, "green_droid_unavailable"),
        ({"dry_run": False, "droid_ok": True}, None),
    ],
)
def test_health_failure(payload, expected):
    assert d.health_failure(payload) == expected


# ---------- happy paths ----------


@pytest.mark.parametrize("case", sorted(d.CASE_MODES))
def test_passing_runs_have_no_failure_codes(case):
    assert codes(case) == []


def test_public_evidence_sanitizes_ids_and_is_json_safe():
    evidence = evaluate("enforce_escalation_timeout")
    blob = json.dumps(d.public_evidence(evidence), allow_nan=False, sort_keys=True)
    for raw in ("sdk-1", "sdk-2", "exp-t1", "prep-v-1", "v-1", "esc-1"):
        assert raw not in blob
    public = d.public_evidence(evidence)
    assert public["turns"] == 1 and public["turn_ok"] is True
    assert public["credits"] == 2.5 and public["mutations"] == 2 and public["verdicts"] == 3


def test_suffixed_write_key_correlates_to_its_call():
    events, audit, targets, status = mk_raw("off_allow")
    audit[1] = _write_row("sdk-1:2")  # a call's n-th ledger write uses `<id>:<n>` (agentkit invocation)
    evidence = d.collect_evidence(events, audit, targets, status)
    assert d.failure_codes("off_allow", evidence) == []


# ---------- whole-day invariants ----------


def test_missing_evidence_is_never_a_receipt():
    assert d.failure_codes("off_allow", {}) == ["evidence_incomplete"]


def test_duplicate_execution_write_row_fails():
    events, audit, targets, status = mk_raw("off_allow")
    audit.append(_write_row("sdk-1"))
    assert "duplicate_execution" in d.failure_codes("off_allow", d.collect_evidence(events, audit, targets, status))


def test_duplicate_mutation_same_entity_fails():
    events, audit, targets, status = mk_raw("off_allow")
    events.append(_mutation("exp-t1", "prep-sdk-1", verdict_id=None))
    assert "duplicate_execution" in d.failure_codes("off_allow", d.collect_evidence(events, audit, targets, status))


def test_unprepared_mutation_fails():
    events, audit, targets, status = mk_raw("off_allow")
    events.append(_call("sdk-2", entity="exp-t2"))
    events.append(_result_ok("sdk-2"))
    events.append(_mutation("exp-t2", "prep-unknown", verdict_id=None))
    assert "unprepared_execution" in d.failure_codes("off_allow", d.collect_evidence(events, audit, targets, status))


def test_duplicate_preparation_fails():
    events, audit, targets, status = mk_raw("off_allow")
    audit.append(_prep_row("sdk-1", "allow", prep_id="prep-again"))
    assert "duplicate_preparation" in d.failure_codes("off_allow", d.collect_evidence(events, audit, targets, status))


def test_read_tool_never_prepares():
    events, audit, targets, status = mk_raw("off_allow")
    events.append({"type": "agent.tool_call", "agent": "green", "payload": {"tool": "ap_queue", "args": {}, "tool_use_id": "sdk-r"}})
    events.append(_result_ok("sdk-r"))
    audit.append(_prep_row("sdk-r", "allow", action="ap_queue"))
    assert "read_tool_prepared" in d.failure_codes("off_allow", d.collect_evidence(events, audit, targets, status))


def test_write_under_unknown_key_fails():
    events, audit, targets, status = mk_raw("off_allow")
    audit[1] = _write_row("sdk-other")
    codes_ = d.failure_codes("off_allow", d.collect_evidence(events, audit, targets, status))
    assert "correlation_mismatch" in codes_


def test_preparation_under_unknown_key_fails():
    events, audit, targets, status = mk_raw("off_allow")
    audit.append(_prep_row("sdk-x", "allow", entity="exp-t9"))
    assert "correlation_mismatch" in d.failure_codes("off_allow", d.collect_evidence(events, audit, targets, status))


def test_gate_replay_on_consume_fails():
    events, audit, targets, status = mk_raw("shadow_effective_allow")
    events.append(_verdict("v-1", "block", "exp-t1", False))  # same verdict_id emitted twice
    assert "gate_replay_on_consume" in d.failure_codes("shadow_effective_allow", d.collect_evidence(events, audit, targets, status))


def test_repeated_tool_call_pair_fails():
    events, audit, targets, status = mk_raw("off_allow")
    events.append(_call("sdk-1"))
    assert "pair_cardinality" in d.failure_codes("off_allow", d.collect_evidence(events, audit, targets, status))


def test_turn_without_credits_fails():
    events, audit, targets, status = mk_raw("off_allow")
    events[-1] = _turn(credits=None)
    assert "credits_unavailable" in d.failure_codes("off_allow", d.collect_evidence(events, audit, targets, status))


def test_boolean_credits_are_not_usage():
    events, audit, targets, status = mk_raw("off_allow")
    events[-1] = _turn(credits=True)
    assert "credits_unavailable" in d.failure_codes("off_allow", d.collect_evidence(events, audit, targets, status))


def test_failed_turn_fails():
    events, audit, targets, status = mk_raw("off_allow")
    events[-1] = _turn(ok=False)
    assert "turn_failed" in d.failure_codes("off_allow", d.collect_evidence(events, audit, targets, status))


def test_target_never_attempted_fails():
    events, audit, targets, status = mk_raw("off_allow")
    status = {"exp-t1": "pending"}
    events = [e for e in events if e.get("type") != "agent.tool_call"]
    codes_ = d.failure_codes("off_allow", d.collect_evidence(events, audit, targets, status))
    assert "target_not_attempted" in codes_


# ---------- mode semantics ----------


def test_off_mode_must_bypass_the_gate():
    events, audit, targets, status = mk_raw("off_allow")
    events.append(_verdict("v-9", "allow", "exp-t1", False))
    assert "gate_not_bypassed" in d.failure_codes("off_allow", d.collect_evidence(events, audit, targets, status))


def test_shadow_requires_the_would_block_verdict():
    events, audit, targets, status = mk_raw("shadow_effective_allow")
    events = [e for e in events if e.get("type") != "gate.verdict"]
    audit[0] = _prep_row("sdk-1", "allow", prep_id="prep-sdk-1")  # no verdict linkage either
    assert "would_block_missing" in d.failure_codes("shadow_effective_allow", d.collect_evidence(events, audit, targets, status))


def test_shadow_verdict_is_never_enforced():
    events, audit, targets, status = mk_raw("shadow_effective_allow")
    events[2] = _verdict("v-1", "block", "exp-t1", True)
    assert "verdict_semantics" in d.failure_codes("shadow_effective_allow", d.collect_evidence(events, audit, targets, status))


def test_allow_cases_require_the_paid_target_state():
    events, audit, targets, status = mk_raw("off_allow")
    assert "target_state_unexpected" in d.failure_codes("off_allow", d.collect_evidence(events, audit, targets, {"exp-t1": "pending"}))


def test_blocked_case_cause_is_exactly_control_hold():
    events, audit, targets, status = mk_raw("enforce_block")
    events[1] = _result_cancel("sdk-1", "escalation_timeout")
    assert "cancel_cause" in d.failure_codes("enforce_block", d.collect_evidence(events, audit, targets, status))


def test_escalation_timeout_is_never_control_hold():
    events, audit, targets, status = mk_raw("enforce_escalation_timeout")
    events[3] = _result_cancel("sdk-1", "control_hold")
    codes_ = d.failure_codes("enforce_escalation_timeout", d.collect_evidence(events, audit, targets, status))
    assert "cause_conflation" in codes_ and "cancel_cause" in codes_


def test_cancel_comment_must_carry_the_verdict_reason():
    events, audit, targets, status = mk_raw("enforce_block")
    events[1] = _result_cancel("sdk-1", "control_hold", reason="some-other-reason")
    assert "cancel_comment_unmatched" in d.failure_codes("enforce_block", d.collect_evidence(events, audit, targets, status))


def test_cancel_pair_must_exist_for_a_blocked_call():
    events, audit, targets, status = mk_raw("enforce_block")
    events[1] = _result_ok("sdk-1")  # blocked call but the model saw a success
    assert "cancel_pair_missing" in d.failure_codes("enforce_block", d.collect_evidence(events, audit, targets, status))


def test_cancel_summary_must_be_the_cancelled_pair():
    events, audit, targets, status = mk_raw("enforce_block")
    events[1]["payload"]["summary"] = "not a cancel"
    assert "cancel_pair_missing" in d.failure_codes("enforce_block", d.collect_evidence(events, audit, targets, status))


def test_blocked_case_never_executes_the_write():
    events, audit, targets, status = mk_raw("enforce_block")
    audit.append(_write_row("sdk-1"))
    assert "execution_after_cancel" in d.failure_codes("enforce_block", d.collect_evidence(events, audit, targets, status))


def test_blocked_case_ends_with_blocked_target():
    events, audit, targets, status = mk_raw("enforce_block")
    assert "target_state_unexpected" in d.failure_codes("enforce_block", d.collect_evidence(events, audit, targets, {"exp-t1": "pending"}))


def test_block_is_not_an_escalation():
    events, audit, targets, status = mk_raw("enforce_block")
    events.append(_esc_opened())
    assert "escalation_unexpected" in d.failure_codes("enforce_block", d.collect_evidence(events, audit, targets, status))


def test_escalation_must_open_exactly_once():
    events, audit, targets, status = mk_raw("enforce_escalation_timeout")
    events = [e for e in events if e.get("type") != "escalation.opened"]
    assert "escalation_missing" in d.failure_codes("enforce_escalation_timeout", d.collect_evidence(events, audit, targets, status))


def test_escalation_must_resolve_as_timeout():
    events, audit, targets, status = mk_raw("enforce_escalation_timeout")
    events = [e for e in events if e.get("type") != "escalation.resolved"]
    assert "escalation_decision" in d.failure_codes("enforce_escalation_timeout", d.collect_evidence(events, audit, targets, status))


def test_escalated_target_ends_blocked():
    events, audit, targets, status = mk_raw("enforce_escalation_timeout")
    status["exp-t1"] = "pending"
    assert "target_state_unexpected" in d.failure_codes("enforce_escalation_timeout", d.collect_evidence(events, audit, targets, status))


# ---------- run() refusal paths (env and health only; every network call is faked) ----------


def _args(**over):
    base = {"case": "off_allow", "isolated_ledger": "http://isolated.invalid", "green_external": True, "green_port": 8002, "seed": None}
    return NS(**(base | over))


def test_run_requires_operator_token(monkeypatch, capsys):
    monkeypatch.delenv("OPERATOR_TOKEN", raising=False)
    assert d.run(_args()) == 2
    assert "env_missing: OPERATOR_TOKEN" in capsys.readouterr().err


@pytest.mark.parametrize("missing", ["AGENT_TOKEN", "FACTORY_API_KEY"])
def test_run_spawn_requires_agent_env(monkeypatch, capsys, missing):
    monkeypatch.setenv("OPERATOR_TOKEN", "op")
    monkeypatch.setenv("AGENT_TOKEN", "agent")
    monkeypatch.setenv("FACTORY_API_KEY", "factory")
    monkeypatch.delenv(missing)
    assert d.run(_args(green_external=False)) == 2
    assert f"env_missing: {missing}" in capsys.readouterr().err


def test_run_external_skips_spawn_env(monkeypatch, capsys):
    monkeypatch.setenv("OPERATOR_TOKEN", "op")
    monkeypatch.delenv("AGENT_TOKEN", raising=False)
    monkeypatch.delenv("FACTORY_API_KEY", raising=False)
    monkeypatch.setattr(d, "probe_battlefield", lambda *a: False)
    assert d.run(_args()) == 2
    out = json.loads(capsys.readouterr().out)
    assert out["failure_codes"] == ["battlefield_unreachable"] and out["acceptance_passed"] is False


@pytest.mark.parametrize(
    ("health", "code"),
    [
        (None, "green_unhealthy"),
        ({"dry_run": True, "droid_ok": True}, "green_still_dry_run"),
        ({"dry_run": False, "droid_ok": False}, "green_droid_unavailable"),
    ],
)
def test_run_external_health_gates(monkeypatch, capsys, health, code):
    monkeypatch.setenv("OPERATOR_TOKEN", "op")
    monkeypatch.setattr(d, "probe_battlefield", lambda *a: True)
    monkeypatch.setattr(d, "green_health", lambda *a, **k: health)
    assert d.run(_args()) == 2
    out = json.loads(capsys.readouterr().out)
    assert out["failure_codes"] == [code] and out["scenario"] == d.SCENARIO


def test_git_sha_is_hex_or_unknown():
    sha = d.git_sha()
    assert sha == "unknown" or re.fullmatch(r"[0-9a-f]{7,64}", sha)
