"""Pydantic models for everything that crosses a process boundary.

Mirrors contracts/events.md and contracts/agent-service.md. If you change a shape here, you are
changing a contract: update the contract file and CHANGELOG in the same PR.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

Agent = Literal["red", "green", "blue"]
Emitter = Literal["red", "green", "blue", "battlefield", "human"]
ControllerMode = Literal["off", "shadow", "enforce"]
VerdictKind = Literal["allow", "block", "escalate"]

# Gated actions blue is asked about. Keep in sync with contracts/agent-service.md.
GATED_ACTIONS: frozenset[str] = frozenset(
    {
        "invoices.match",
        "invoices.approve",
        "invoices.reject",
        "invoices.pay",
        "vendor_changes.approve",
        "vendor_changes.reject",
        "expenses.approve",
        "expenses.pay",
        "gl.post",
    }
)


class EventType(StrEnum):
    EPISODE_STARTED = "episode.started"
    EPISODE_ENDED = "episode.ended"
    EPISODE_PAUSED = "episode.paused"
    EPISODE_RESUMED = "episode.resumed"
    CONTROLLER_CHANGED = "controller.changed"
    DAY_STARTED = "day.started"
    DAY_ENDED = "day.ended"
    TURN_STARTED = "turn.started"
    TURN_ENDED = "turn.ended"
    ATTACK_LAUNCHED = "attack.launched"
    ATTACK_OUTCOME = "attack.outcome"
    AGENT_THINKING = "agent.thinking"
    AGENT_TOOL_CALL = "agent.tool_call"
    AGENT_TOOL_RESULT = "agent.tool_result"
    LEDGER_MUTATION = "ledger.mutation"
    GATE_VERDICT = "gate.verdict"
    ESCALATION_OPENED = "escalation.opened"
    ESCALATION_RESOLVED = "escalation.resolved"
    FLAG_RAISED = "flag.raised"
    VENDOR_FROZEN = "vendor.frozen"
    VENDOR_UNFROZEN = "vendor.unfrozen"
    REPORT_POSTED = "report.posted"
    SCORE_UPDATED = "score.updated"
    ERROR = "error"


AGENT_EMITTABLE: frozenset[str] = frozenset({EventType.AGENT_THINKING, EventType.AGENT_TOOL_CALL, EventType.AGENT_TOOL_RESULT})


def agent_may_emit(type_: str) -> bool:
    """Agents may emit the three narration types plus any `x.<area>.<name>` custom event
    (frontend renders those generically; no contracts PR needed)."""
    return type_ in AGENT_EMITTABLE or type_.startswith("x.")


class Event(BaseModel):
    id: int | None = None
    ts: datetime | None = None
    episode_id: str
    day: int
    type: str
    agent: Emitter | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentEventCreate(BaseModel):
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)


class Score(BaseModel):
    dollars_extracted: float = 0.0
    dollars_blocked: float = 0.0
    false_positive_cost: float = 0.0
    detection_latency_days: float | None = None
    attacks_launched: int = 0
    attacks_caught: int = 0
    legit_blocked: int = 0
    legit_processed: int = 0


# ---------- agent service ----------


class Usage(BaseModel):
    factory_credits: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class TurnRequest(BaseModel):
    episode_id: str
    day: int
    controller_mode: ControllerMode
    options: dict[str, Any] = Field(default_factory=dict)


class TurnResponse(BaseModel):
    ok: bool
    summary: str = ""
    duration_sec: float = 0.0
    usage: Usage | None = None


class HealthResponse(BaseModel):
    ok: bool
    agent: str
    model: str | None = None
    droid_ok: bool = False
    dry_run: bool = False


class Scheme(BaseModel):
    id: str
    display_name: str
    story: str
    params_schema: dict[str, Any] = Field(default_factory=dict)
    expected_impact: dict[str, float] = Field(default_factory=dict)


class GateRequest(BaseModel):
    idempotency_key: str
    episode_id: str
    day: int
    controller_mode: ControllerMode
    agent: Agent
    action: str
    entity_type: str | None = None
    entity_id: str | None = None
    amount: float | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)


class GateResponse(BaseModel):
    verdict: VerdictKind
    reason: str
    confidence: float | None = None
    rules_fired: list[str] = Field(default_factory=list)
    latency_ms: int | None = None


class AuditRequest(BaseModel):
    episode_id: str
    day: int
    inputs: list[dict[str, Any]] = Field(default_factory=list)


class AuditResponse(BaseModel):
    ok: bool
    flags_raised: int = 0
    report_posted: bool = False
    summary: str = ""


class AttackCreate(BaseModel):
    scheme_id: str
    display_name: str
    story: str
    params: dict[str, Any] = Field(default_factory=dict)
    target_amount: float
