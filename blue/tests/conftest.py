from __future__ import annotations

import copy
import os
import sys
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "blue"), str(ROOT / "agentkit")]
os.environ.setdefault("AGENT_NAME", "blue")
os.environ["DRY_RUN"] = "true"
# Never load developer secrets or a real provider configuration during collection.
for key, value in {
    "AGENT_TOKEN": "test-agent",
    "OPERATOR_TOKEN": "test-operator",
    "INTERNAL_TOKEN": "test-legacy",
    "BLUE_GATE_LLM_PROVIDER": "",
    "BLUE_GATE_LLM_API_KEY": "",
    "BLUE_GATE_LLM_MODEL": "",
}.items():
    os.environ[key] = value

from agentkit.config import AgentSettings  # noqa: E402

AgentSettings.model_config["env_file"] = None

from agentkit.models import GateRequest  # noqa: E402
from gate import engine  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_gate(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setattr(engine, "_cache", engine.RetainedVerdicts())
    monkeypatch.setattr(engine, "_pending", {})


@pytest.fixture
def gate_request():
    def make(action="invoices.pay", amount=1200, day=5, mode="enforce", **overrides):
        context = {
            "vendor": {"id": "v", "episode_id": "ep", "created_day": -100, "status": "active"},
            "invoice": {
                "id": "i",
                "episode_id": "ep",
                "vendor_id": "v",
                "amount": amount,
                "invoice_number": "INV-002",
                "po_id": None,
                "received_day": day,
                "status": "approved",
            },
            "po": None,
            "vendor_paid_invoices": [],
            "vendor_recent_changes": [],
            "flags": [],
        }
        data = dict(
            idempotency_key=uuid4().hex,
            episode_id="ep",
            day=day,
            controller_mode=mode,
            agent="green",
            action=action,
            entity_type="invoice",
            entity_id="i",
            amount=amount,
            context=context,
        )
        data.update(copy.deepcopy(overrides))
        return GateRequest(**data)

    return make


def paid_invoice(**overrides):
    row = {"id": "paid", "vendor_id": "v", "episode_id": "ep", "amount": 1200, "invoice_number": "INV-001", "po_id": None, "status": "paid"}
    return row | overrides


@pytest.fixture
def runtime(monkeypatch):
    import agentkit.droid_agent as shared
    from agentkit.config import AgentSettings
    from audit.agent import AuditAgent

    from .audit_helpers import FakeEmitter, FakeLedger

    def make(ledger=None, *, dry_run=True, timeout=180):
        ledger = ledger or FakeLedger()
        emitter = FakeEmitter()
        monkeypatch.setattr(shared, "LedgerClient", lambda *a, **kw: ledger)
        monkeypatch.setattr(shared, "EventEmitter", lambda *a, **kw: emitter)
        settings = AgentSettings(
            AGENT_NAME="blue", DRY_RUN=dry_run, AGENT_TOKEN="test-agent", INTERNAL_TOKEN="test-legacy", TURN_TIMEOUT_SEC=timeout, _env_file=None
        )
        return AuditAgent(settings), ledger, emitter

    return make
