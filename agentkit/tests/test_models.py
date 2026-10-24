"""Owner: Dev Ad."""

import pytest

from agentkit.events import EventEmitter
from agentkit.models import AGENT_EMITTABLE, GATED_ACTIONS, EventType, GateRequest, GateResponse, TurnRequest


def test_gate_roundtrip():
    req = GateRequest(
        idempotency_key="k1",
        episode_id="ep_1",
        day=2,
        controller_mode="enforce",
        agent="green",
        action="invoices.pay",
        entity_type="invoice",
        entity_id="inv_1",
        amount=4920.0,
    )
    assert req.action in GATED_ACTIONS
    resp = GateResponse(verdict="block", reason="vendor is 1 day old", rules_fired=["vendor_age_lt_7d"])
    assert resp.model_dump()["verdict"] == "block"


def test_turn_request_defaults():
    t = TurnRequest(episode_id="ep", day=0, controller_mode="off")
    assert t.options == {}


def test_agent_emittable_is_subset_of_event_types():
    all_types = {e.value for e in EventType}
    assert AGENT_EMITTABLE <= all_types


def test_emitter_rejects_non_agent_types():
    from agentkit.config import AgentSettings

    s = AgentSettings(AGENT_NAME="red")
    em = EventEmitter(s, episode_id="ep", day=0)
    with pytest.raises(ValueError):
        em.emit("gate.verdict", {})


def test_lineage_config_defaults_match_contract():
    from agentkit.models import LineageConfig

    c = LineageConfig()
    assert (c.generations, c.days, c.controller_mode) == (3, 6, "enforce")
    assert (c.reveal_days, c.reveal_generations, c.max_credits) == (3, 2, 0.0)
    assert c.headless is not None
    assert (c.headless.day_pause_sec, c.headless.escalation_policy, c.headless.escalation_timeout_sec) == (0.0, "block", 5)
    assert LineageConfig(headless=None).headless is None


def test_lineage_config_refuses_unknown_and_invalid():
    from pydantic import ValidationError

    from agentkit.models import LineageConfig

    for bad in (
        {"reveal_windw": 3},
        {"generations": 0},
        {"reveal_days": -1},
        {"headless": {"escalation_policy": "approve"}},
        {"headless": {"escalation_timeout_sec": 0}},
    ):
        with pytest.raises(ValidationError):
            LineageConfig.model_validate(bad)


def test_audit_request_lineage_fields_optional():
    from agentkit.models import AuditRequest

    plain = AuditRequest(episode_id="ep", day=1)
    assert plain.lineage is None and plain.debrief is None
    a = AuditRequest.model_validate(
        {
            "episode_id": "ep",
            "day": 4,
            "lineage": {"id": "ln_1", "generation": 2, "playbook_version": 7},
            "debrief": {"day": 3, "window_days": 3, "items": [{"kind": "attack"}]},
        }
    )
    assert a.lineage.playbook_version == 7 and a.debrief.items[0]["kind"] == "attack"


def test_gate_request_playbook_version_optional():
    req = GateRequest(idempotency_key="k", episode_id="ep", day=0, controller_mode="off", agent="green", action="invoices.pay")
    assert req.playbook_version is None


def test_reflect_roundtrip_and_null_keeps_playbook():
    from agentkit.models import ReflectRequest, ReflectResponse

    r = ReflectRequest.model_validate(
        {
            "lineage_id": "ln_1",
            "generation": 2,
            "episode_id": "ep_2",
            "review": {"score": {}},
            "playbook": {"version": 7, "generation": 2, "source": "turn", "content": {"a": 1}},
        }
    )
    assert r.playbook.version == 7 and r.playbook.content == {"a": 1}
    keep = ReflectResponse(ok=True, rationale="dry run")
    assert keep.playbook is None and keep.usage is None


def test_lineage_events_are_battlefield_only():
    from agentkit.models import agent_may_emit

    for t in ("generation.started", "generation.ended", "playbook.updated", "debrief.delivered", "lineage.paused", "lineage.resumed"):
        assert t in {e.value for e in EventType}
        assert not agent_may_emit(t)
