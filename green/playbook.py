"""Deterministic AAR memory only; no turn-policy changes, model calls or ledger I/O."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from agentkit.models import ReflectRequest, ReflectResponse

MEMORY_KEY = "green_reflection"
MAX_REVIEW_ITEMS = 2000
MAX_CONTENT_BYTES = 64 * 1024
OUTCOMES = ("fraud_paid", "fraud_approved", "fraud_blocked", "fraud_rejected", "legit_blocked")
PROCEDURES = (
    "Re-read current entity state and existing payments before dependent writes; count only confirmed receipts.",
    "Respect blocked or rejected work; do not retry it in the same turn.",
    "Account for blocked legitimate work separately from completed work; do not bypass a refusal.",
)
_ACTIONS = {
    "invoice": ("invoices.match", "invoices.approve", "invoices.reject", "invoices.pay"),
    "expense": ("expenses.approve", "expenses.pay"),
    "vendor_change": ("vendor_changes.approve", "vendor_changes.reject"),
}


def _identifier(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 128 and bool(value.strip())


def _observation(item: Any) -> tuple[tuple[str, str], str] | None:
    """IDs are transient deduplication keys, never copied into memory or rationale."""
    if not isinstance(item, dict):
        return None
    entity_type, entity_id, day = item.get("entity_type"), item.get("entity_id"), item.get("day")
    if not isinstance(entity_type, str) or entity_type not in _ACTIONS or not _identifier(entity_id):
        return None
    if type(day) is not int or day < 0:
        return None
    kind = item.get("kind")
    if kind == "fraud":
        outcome = item.get("outcome")
        if outcome not in ("paid", "approved", "blocked", "rejected"):
            return None
        if item.get("green_action") not in _ACTIONS[entity_type] or (entity_type == "vendor_change" and outcome == "paid"):
            return None
        bucket = f"fraud_{outcome}"
    elif kind == "legit_blocked":
        if item.get("action") not in _ACTIONS[entity_type] or not _identifier(item.get("verdict_id")):
            return None
        bucket = "legit_blocked"
    else:
        return None
    return (entity_type, entity_id), bucket


def _fits(content: dict[str, Any]) -> bool:
    try:
        return len(json.dumps(content, ensure_ascii=False, allow_nan=False).encode("utf-8")) <= MAX_CONTENT_BYTES
    except (TypeError, ValueError, UnicodeError):
        return False


def reflect_playbook(req: ReflectRequest) -> ReflectResponse:
    """Snapshot unique, nonconflicting AAR entities; retain only fixed procedural lessons.

    Counts describe the latest accepted review, not cumulative totals. Replays do not
    inflate them, even when Battlefield supplies a newly versioned previous result.
    Unrelated operator content is preserved but is never interpreted as instructions.
    """
    items = req.review.get("items")
    if not isinstance(items, list) or not items:
        return ReflectResponse(ok=True, rationale="No usable Green review items; playbook kept.")
    if len(items) > MAX_REVIEW_ITEMS:
        return ReflectResponse(ok=True, rationale="Green review exceeds the item limit; playbook kept.")
    original = req.playbook.content
    if not _fits(original):
        return ReflectResponse(ok=True, rationale="Green playbook exceeds the supported content limit; playbook kept.")
    previous = original.get(MEMORY_KEY, {})
    if not isinstance(previous, dict) or type(previous.get("schema_version", 1)) is not int or previous.get("schema_version", 1) != 1:
        return ReflectResponse(ok=True, rationale="Green reflection namespace is incompatible; playbook kept.")
    observations: dict[tuple[str, str], set[str]] = {}
    for item in items:
        observation = _observation(item)
        if observation is not None:
            entity, bucket = observation
            observations.setdefault(entity, set()).add(bucket)
    counts = dict.fromkeys(OUTCOMES, 0)
    for buckets in observations.values():
        if len(buckets) == 1:  # Contradictory disclosures are ignored, not classified.
            counts[next(iter(buckets))] += 1
    if not any(counts.values()):
        return ReflectResponse(ok=True, rationale="No usable Green review items; playbook kept.")

    prior = previous.get("procedure_reminders")
    reminders = [p for p in PROCEDURES if isinstance(prior, list) and p in prior]
    for applies, reminder in zip(
        (
            counts["fraud_paid"] + counts["fraud_approved"],
            counts["fraud_blocked"] + counts["fraud_rejected"],
            counts["legit_blocked"],
        ),
        PROCEDURES,
        strict=True,
    ):
        if applies and reminder not in reminders:
            reminders.append(reminder)
    memory = deepcopy(previous)
    memory.update(schema_version=1, last_review_counts=counts, procedure_reminders=[p for p in PROCEDURES if p in reminders])
    content = deepcopy(original)
    content[MEMORY_KEY] = memory
    if content == original:
        return ReflectResponse(ok=True, rationale="Green review already reflected; playbook kept.")
    if not _fits(content):
        return ReflectResponse(ok=True, rationale="Green reflection would exceed the content limit; playbook kept.")
    rationale = "Green AAR: " + ", ".join(f"{key}={counts[key]}" for key in OUTCOMES)
    return ReflectResponse(ok=True, playbook=content, rationale=rationale + ". Procedural memory only; AP execution unchanged.")
