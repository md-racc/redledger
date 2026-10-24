"""Blue-local typed evidence and effect receipts; no shared contract changes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Family = Literal["integrity", "identity", "destination", "authorization", "structure", "tenure", "amount"]


class Evidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    family: Family
    fact: str = Field(max_length=240)
    substantive: bool = False


class Finding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str
    code: str
    entity_type: Literal["vendor", "invoice", "employee", "vendor_change"]
    entity_id: str
    vendor_id: str | None = None
    severity: Literal["low", "medium", "high"]
    evidence: tuple[Evidence, ...]
    reason: str = Field(max_length=600)


class Coverage(BaseModel):
    dataset: str
    status: Literal["complete", "truncated", "partial", "unavailable"]
    processed: int = 0
    omitted: int = 0
    detail: str = ""


class ConfirmedEffect(BaseModel):
    kind: Literal["flag", "freeze", "report"]
    key: str
    tool_use_id: str
    state: Literal["attempted", "confirmed", "failed", "unknown"] = "attempted"
    receipt_id: str | None = None
    detail: str = ""


class AuditOutcome(BaseModel):
    flags_raised: int = 0
    vendors_frozen: int = 0
    report_posted: bool = False
    partial: bool = False
    summary: str = ""


@dataclass
class Snapshot:
    episode_id: str
    day: int
    datasets: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    coverage: list[Coverage] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    total_findings: int = 0
    leads_reviewed: int = 0
    name_hint_groups: int = 0


@dataclass
class AuditSession:
    episode_id: str
    day: int
    dry_run: bool
    deadline: float
    snapshot: Snapshot | None = None
    effects: list[ConfirmedEffect] = field(default_factory=list)
    unresolved: list[ConfirmedEffect] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    suppressed: set[str] = field(default_factory=set)
    tool_lock: Any = None
    model_succeeded: bool = False

    def outcome(self) -> AuditOutcome:
        flags = sum(e.kind == "flag" and e.state == "confirmed" for e in self.effects)
        freezes = sum(e.kind == "freeze" and e.state == "confirmed" for e in self.effects)
        posted = any(e.kind == "report" and e.state == "confirmed" for e in self.effects)
        incomplete = self.snapshot is None or any(c.status != "complete" for c in self.snapshot.coverage)
        partial = incomplete or bool(self.gaps) or bool(self.unresolved) or any(e.state != "confirmed" for e in self.effects) or not posted
        pending = sum(e.state in {"unknown", "attempted"} for e in self.effects) + len(self.unresolved)
        return AuditOutcome(
            flags_raised=flags,
            vendors_frozen=freezes,
            report_posted=posted,
            partial=partial,
            summary=f"{'Partial audit' if partial else 'Audit complete'}: {flags} confirmed flags, {freezes} confirmed freezes; "
            f"report {'confirmed' if posted else 'not confirmed'}; {pending} unknown writes. "
            f"{'; '.join(self.gaps[:3])}"[:700],
        )
