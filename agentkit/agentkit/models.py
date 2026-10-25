"""Pydantic models for everything that crosses a process boundary.

Mirrors contracts/events.md and contracts/agent-service.md. If you change a shape here, you are
changing a contract: update the contract file and CHANGELOG in the same PR.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

Agent = Literal["red", "green", "blue"]
Emitter = Literal["red", "green", "blue", "battlefield", "human"]
ControllerMode = Literal["off", "shadow", "enforce"]
VerdictKind = Literal["allow", "block", "escalate"]

# Gated actions blue is asked about. Keep in sync with contracts/agent-service.md.
GatedAction = Literal[
    "invoices.match",
    "invoices.approve",
    "invoices.reject",
    "invoices.pay",
    "vendor_changes.approve",
    "vendor_changes.reject",
    "expenses.approve",
    "expenses.pay",
    "gl.post",
]
GATED_ACTIONS: frozenset[str] = frozenset(get_args(GatedAction))


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
    # lineages (battlefield-only; docs/ARCHITECTURE.md, Evolution)
    GENERATION_STARTED = "generation.started"
    GENERATION_ENDED = "generation.ended"
    PLAYBOOK_UPDATED = "playbook.updated"
    DEBRIEF_DELIVERED = "debrief.delivered"
    LINEAGE_PAUSED = "lineage.paused"
    LINEAGE_RESUMED = "lineage.resumed"


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
    playbook_version: int | None = None  # blue's latest playbook version; lineage episodes only


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
    lineage: LineageInfo | None = None  # lineage episodes only
    debrief: Debrief | None = None


class AuditResponse(BaseModel):
    ok: bool
    flags_raised: int = 0
    report_posted: bool = False
    summary: str = ""
    usage: Usage | None = None  # the live audit turn's usage; battlefield charges factory_credits to the episode


class AttackCreate(BaseModel):
    scheme_id: str
    display_name: str
    story: str
    params: dict[str, Any] = Field(default_factory=dict)
    target_amount: float


# ---------- gate preparations (contracts/ledger-api.yaml POST /preparations) ----------

VerdictCause = Literal["control", "gate_unavailable"]
# Why green's permission handler cancelled a tool call (in its cancel comment and tool_result summary).
CancelCause = Literal["control_hold", "escalation_timeout", "integration_failure", "invalid_state"]
PREPARATION_TTL_SEC = 120  # fixed from created_at, never extended


class PreparationCreate(BaseModel):
    action: GatedAction
    entity_id: str | None = None  # required except for gl.post
    args: dict[str, Any] = Field(default_factory=dict)  # the exact body the execution will send


class Preparation(BaseModel):
    preparation_id: str
    idempotency_key: str
    controller_mode: ControllerMode
    day: int
    action: GatedAction
    entity_type: str | None = None
    entity_id: str | None = None
    amount: float | None = None  # None for gl.post and vendor_changes.*
    effective: Literal["allow", "block", "pending"]  # what execution under this key will do
    enforced: bool = False
    decided_by: Literal["mode", "gate", "human", "timeout"] | None = None  # None exactly while effective == "pending"
    verdict_id: str | None = None  # None in off
    verdict: VerdictKind | None = None
    cause: VerdictCause | None = None
    reason: str = ""
    rules_fired: list[str] = Field(default_factory=list)
    escalation_id: str | None = None
    expires_at: datetime
    consumed: bool
    consumed_status: int | None = None


class PreparationRejected(BaseModel):
    error: Literal["preparation_expired", "preparation_stale", "preparation_consumed", "preparation_pending"]
    preparation_id: str
    detail: str = ""
    consumed_status: int | None = None


# ---------- lineages (contracts/agent-service.md "Lineages") ----------


class HeadlessConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day_pause_sec: float = Field(0.0, ge=0)
    escalation_policy: Literal["block"] = "block"
    escalation_timeout_sec: int = Field(5, ge=1)


class LineageConfig(BaseModel):
    """Validated by battlefield on POST /lineages. Unknown keys are refused."""

    model_config = ConfigDict(extra="forbid")

    generations: int = Field(3, ge=1)
    days: int = Field(6, ge=1)
    controller_mode: ControllerMode = "enforce"
    reveal_days: int = Field(3, ge=0)  # debrief window in completed days; 0 = no daily reveal
    reveal_generations: int = Field(2, ge=0)  # this generation + N-1 summaries; 0 = no review, no /reflect
    headless: HeadlessConfig | None = Field(default_factory=HeadlessConfig)
    max_credits: float = Field(0.0, ge=0)  # whole lineage, turns + reflections; 0 = off


class LineageInfo(BaseModel):
    """`options.lineage` on /turn, `lineage` on blue /audit."""

    id: str
    generation: int
    playbook_version: int


class Debrief(BaseModel):
    """`options.debrief` on /turn, `debrief` on blue /audit. Item shapes per agent: agent-service.md."""

    day: int
    window_days: int
    items: list[dict[str, Any]] = Field(default_factory=list)


class Playbook(BaseModel):
    version: int
    parent_version: int | None = None
    generation: int
    episode_id: str | None = None
    day: int | None = None
    source: Literal["seed", "turn", "reflect", "operator"]
    content: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""
    created_at: datetime | None = None


class ReflectRequest(BaseModel):
    lineage_id: str
    generation: int
    episode_id: str
    review: dict[str, Any] = Field(default_factory=dict)
    playbook: Playbook


class ReflectResponse(BaseModel):
    ok: bool
    playbook: dict[str, Any] | None = None  # new content; None keeps the current version
    rationale: str = ""
    usage: Usage | None = None


AuditRequest.model_rebuild()  # resolves the forward refs to LineageInfo / Debrief above
