"""Gate preparation models (contracts/ledger-api.yaml POST /preparations)."""

from typing import get_args

import pytest
from pydantic import ValidationError

from agentkit.models import GATED_ACTIONS, GatedAction, Preparation, PreparationCreate, PreparationRejected

PREP = {
    "preparation_id": "prep_1",
    "idempotency_key": "toolu_1",
    "controller_mode": "enforce",
    "day": 2,
    "action": "invoices.pay",
    "effective": "block",
    "decided_by": "gate",
    "expires_at": "2026-10-24T10:02:00Z",
    "consumed": False,
}


def test_gated_action_literal_matches_the_gated_set():
    assert set(get_args(GatedAction)) == GATED_ACTIONS


def test_preparation_requires_effective_and_rejects_unknown_values():
    assert Preparation.model_validate(PREP).effective == "block"
    with pytest.raises(ValidationError):
        Preparation.model_validate({k: v for k, v in PREP.items() if k != "effective"})
    with pytest.raises(ValidationError):
        Preparation.model_validate({**PREP, "effective": "maybe"})
    with pytest.raises(ValidationError):
        Preparation.model_validate({**PREP, "cause": "flaky"})


def test_preparation_create_and_rejected():
    assert PreparationCreate(action="gl.post", args={"account": "1000"}).entity_id is None
    with pytest.raises(ValidationError):
        PreparationCreate(action="invoices.delete")
    r = PreparationRejected(error="preparation_consumed", preparation_id="prep_1", consumed_status=200)
    assert r.consumed_status == 200
    with pytest.raises(ValidationError):
        PreparationRejected(error="nope", preparation_id="prep_1")
