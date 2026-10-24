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
