"""Bounded learning from Red's authorized disclosures, never executable playbook text."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agentkit.models import LineageInfo
from schemes import SCHEMES

NAMESPACE = "red_evolution"
LIMIT = 128
RATIONALE = "Fold own disclosed attack outcomes; prefer schemes without a recent catch."
Outcome = Literal["extracted", "partial", "blocked", "flagged", "failed"]
Control = Literal["allow", "block", "escalate", "flag", "freeze"]


class _Observation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    generation: int = Field(ge=0)
    day: int = Field(ge=0)
    id: str = Field(pattern=r"^[0-9a-f]{64}$")
    scheme: str
    outcome: Outcome
    caught: bool
    controls: list[Control] = Field(max_length=5)


class _Memory(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[1]
    observations: list[_Observation] = Field(max_length=LIMIT)


def lineage_info(options: dict[str, Any]) -> LineageInfo | None:
    """Malformed or absent lineage metadata never enables lineage I/O."""
    try:
        info = LineageInfo.model_validate(options.get("lineage"), strict=True)
        return info if info.id and info.generation >= 0 and info.playbook_version >= 0 else None
    except ValidationError:
        return None


def _fits(value: Any, limit: int = 60_000) -> bool:
    try:
        return len(json.dumps(value, allow_nan=False).encode()) <= limit
    except (ValueError, TypeError, RecursionError):
        return False


def _memory(content: dict[str, Any]) -> _Memory | None:
    if not isinstance(content, dict) or not _fits(content):
        return None
    try:
        memory = _Memory.model_validate(content.get(NAMESPACE, {"version": 1, "observations": []}))
        return memory if all(o.scheme in SCHEMES for o in memory.observations) else None
    except ValidationError:
        return None


def _key(o: _Observation) -> tuple[int, int, str]:
    return o.generation, o.day, o.id


def fold(content: dict[str, Any], items: Any, generation: int, episode_id: str, *, ended: bool = False) -> dict[str, Any] | None:
    """Return changed content or None. Repeated daily/AAR items are a set, not counters.

    Retain the latest 128 launches, including hashed episode/attack identity. Replayed older
    items cannot displace this window. AAR may include unresolved attacks, but pending outcomes
    remain neutral. Unknown namespaces are preserved rather than migrated or overwritten.
    """
    memory = _memory(content)
    if memory is None or type(generation) is not int or generation < 0 or not episode_id or not isinstance(items, list) or len(items) > 4096:
        return None
    rows = {o.id: o for o in memory.observations}
    for item in items:
        if not isinstance(item, dict) or not _fits(item, 16_000):
            continue
        attack, scheme, launched = item.get("attack_id"), item.get("scheme_id"), item.get("day_launched")
        resolved, outcome, detected = item.get("resolved_day"), item.get("outcome"), item.get("detected_day")
        if (
            item.get("kind") != "attack"
            or not isinstance(attack, str)
            or not 0 < len(attack) <= 256
            or not isinstance(scheme, str)
            or scheme not in SCHEMES
            or type(launched) is not int
            or launched < 0
            or outcome not in ("extracted", "partial", "blocked", "flagged", "failed")
            or (not ended and (type(resolved) is not int or resolved < launched))
            or (resolved is not None and (type(resolved) is not int or resolved < launched))
            or (detected is not None and (type(detected) is not int or detected < launched))
        ):
            continue
        identity = hashlib.sha256(json.dumps([episode_id, attack]).encode()).hexdigest()
        if identity in rows:  # frozen disclosures never replace earlier evidence
            continue
        controls = item.get("controls", [])
        if not isinstance(controls, list) or len(controls) > 128:
            continue
        categories = set()
        for control in controls:
            if isinstance(control, dict):
                kind = control.get("kind")
                if kind == "verdict" and control.get("verdict") in ("allow", "block", "escalate"):
                    categories.add(control["verdict"])
                elif kind in ("flag", "freeze"):
                    categories.add(kind)
        rows[identity] = _Observation(
            generation=generation,
            day=launched,
            id=identity,
            scheme=scheme,
            outcome=outcome,
            caught=outcome != "extracted" or detected is not None,
            controls=sorted(categories),
        )
    observations = sorted(rows.values(), key=_key)[-LIMIT:]
    if observations == sorted(memory.observations, key=_key):
        return None
    updated = {**content, NAMESPACE: _Memory(version=1, observations=observations).model_dump()}
    return updated if _fits(updated) else None


def view(content: dict[str, Any], day: int) -> dict[str, Any]:
    """Only typed categorical summaries reach the model; operator prose stays out."""
    memory = _memory(content)
    summaries: dict[str, Any] = {}
    for o in sorted(memory.observations, key=_key) if memory else []:
        summary = summaries.setdefault(o.scheme, {"observed": 0})
        summary.update(observed=summary["observed"] + 1, last_outcome=o.outcome, caught=o.caught, controls=o.controls)
    order = list(SCHEMES)
    order = order[day % len(order) :] + order[: day % len(order)]
    # Latest evidence dominates: an old winning streak cannot outweigh a later catch.
    order.sort(key=lambda s: (1 if summaries[s]["caught"] else -1) if s in summaries else 0)
    return {"schemes": summaries, "preference": order}
