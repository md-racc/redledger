"""Deterministic policy with process-local 120-second singleflight retention."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any

from fastapi import HTTPException

from agentkit.models import GateRequest, GateResponse

from .cache import VerdictCache
from .llm import LLMGate
from .rules import RETIREABLE_RULE_IDS, RuleHit, evaluate

TTL = 120
MAX_ENTRIES = 100_000
MAX_PENDING = 256
_llm = LLMGate.from_env()


def _posted_fields(value: Any) -> tuple[Any, ...]:
    if isinstance(value, dict):
        return ("object", tuple(sorted((key, _posted_fields(item)) for key, item in value.items())))
    if isinstance(value, list):
        return ("array", tuple(_posted_fields(item) for item in value))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = Decimal(str(value))
        return ("number", number if number.is_finite() else str(number))
    return (type(value).__name__, value)


@dataclass(frozen=True)
class ActionBinding:
    action: str
    entity_type: str | None
    entity_id: str | None
    amount: Decimal | None
    posted_fields: tuple[Any, ...] | None

    @classmethod
    def from_request(cls, req: GateRequest) -> ActionBinding:
        return cls(
            req.action,
            req.entity_type,
            None if req.action == "gl.post" else req.entity_id,
            None if req.amount is None else Decimal(str(req.amount)),
            _posted_fields(req.args) if req.action == "gl.post" else None,
        )

    def require_match(self, other: ActionBinding) -> None:
        same_amount = self.amount == other.amount
        if self.amount is not None and other.amount is not None:
            # Match the ledger's sub-cent tolerance without binary-float cent-boundary drift.
            same_amount = (
                abs(self.amount - other.amount) < Decimal("0.01")
                if self.amount.is_finite() and other.amount.is_finite()
                else str(self.amount) == str(other.amount)
            )
        if (self.action, self.entity_type, self.entity_id, self.posted_fields) != (
            other.action,
            other.entity_type,
            other.entity_id,
            other.posted_fields,
        ) or not same_amount:
            raise HTTPException(409, "idempotency key reused for a different action")


@dataclass
class VerdictGeneration:
    last: float
    cache: VerdictCache
    bindings: dict[str, ActionBinding] = field(default_factory=dict)


class RetainedVerdicts:
    """Shard before VerdictCache's destructive capacity clear; retire only expired shards."""

    def __init__(self) -> None:
        self.generations: list[VerdictGeneration] = []

    def prune(self) -> None:
        now = time.monotonic()
        self.generations = [generation for generation in self.generations if now - generation.last <= TTL]

    def get(self, key: str, binding: ActionBinding) -> GateResponse | None:
        self.prune()
        for generation in reversed(self.generations):
            value = generation.cache.get(key)
            if value is not None:
                generation.bindings[key].require_match(binding)
                return value.model_copy(deep=True)
            generation.bindings.pop(key, None)
        return None

    def size(self) -> int:
        self.prune()
        return sum(len(generation.cache._d) for generation in self.generations)

    def put(self, key: str, value: GateResponse, binding: ActionBinding) -> None:
        self.prune()
        if not self.generations or len(self.generations[-1].cache._d) >= 5000:
            self.generations.append(VerdictGeneration(time.monotonic(), VerdictCache(ttl_sec=TTL)))
        generation = self.generations[-1]
        generation.cache.put(key, value.model_copy(deep=True))
        generation.bindings[key] = binding
        generation.last = time.monotonic()


_cache = RetainedVerdicts()
_pending: dict[str, tuple[ActionBinding, asyncio.Task[GateResponse]]] = {}


def namespace(req: GateRequest) -> str:
    return json.dumps([req.episode_id, req.idempotency_key], separators=(",", ":"))


def _reason(hits: list[RuleHit], verdict: str) -> str:
    if not hits:
        return "No applicable control exceptions."
    prefix = {"block": "Control hold", "escalate": "Needs independent verification", "allow": "Allowed with diagnostic notes"}[verdict]
    return f"{prefix} — {'; '.join(h.detail for h in hits)}"


async def _compute(
    req: GateRequest, key: str, binding: ActionBinding, dry_run: bool = False, extra_hits: tuple[RuleHit, ...] = (), retired: frozenset[str] = frozenset()
) -> GateResponse:
    started = time.monotonic()
    try:
        # Only note-only rules can ever be retired; a block or hold rule always stands.
        retired = retired & RETIREABLE_RULE_IDS
        base_hits = [hit for hit in evaluate(req) if hit.id not in retired or hit.effect != "note"]
        hits = base_hits + list(extra_hits)
        effects = {hit.effect for hit in hits}
        base_effects = {hit.effect for hit in base_hits}
        if "block" in base_effects and "unavailable" not in base_effects:
            # Optional learning must never weaken a verified baseline hold.
            effects.discard("unavailable")
        # An unavailable control is diagnostic, never counted as a fraud hit.
        verdict = "escalate" if "unavailable" in effects else "block" if "block" in effects else "escalate" if "review" in effects else "allow"
        if not dry_run and verdict == "escalate" and "review" in effects and "unavailable" not in effects and _llm.enabled:
            # Advisory has no authority over reason, verdict, confidence, or rule IDs.
            await _llm.judge(req, hits)
        response = GateResponse(
            verdict=verdict,
            reason=_reason(hits, verdict),
            confidence=0.98 if verdict == "block" else 0.65 if verdict == "escalate" else 0.99,
            rules_fired=[hit.id for hit in hits],
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        _cache.put(key, response, binding)
        return response
    finally:
        _pending.pop(key, None)


async def decide(req: GateRequest, *, dry_run: bool = False, extra_hits: tuple[RuleHit, ...] = (), retired: frozenset[str] = frozenset()) -> GateResponse:
    key = namespace(req)
    binding = ActionBinding.from_request(req)
    cached = _cache.get(key, binding)
    if cached is not None:
        return cached
    pending = _pending.get(key)
    if pending is None:
        # Reject new admission, never evict a verdict promised for 120 seconds.
        if len(_pending) >= MAX_PENDING or _cache.size() + len(_pending) >= MAX_ENTRIES:
            raise HTTPException(503, "gate capacity unavailable; retry later with the same key")
        work = _compute(req.model_copy(deep=True), key, binding, dry_run, extra_hits, retired)
        task = asyncio.create_task(work)
        _pending[key] = (binding, task)
    else:
        original, task = pending
        original.require_match(binding)
    # Disconnecting one caller must not cancel shared work or invalidate its receipt.
    return (await asyncio.shield(task)).model_copy(deep=True)


def explain(req: GateRequest, *, extra_hits: tuple[RuleHit, ...] = (), retired: frozenset[str] = frozenset()) -> dict[str, Any]:
    retired = retired & RETIREABLE_RULE_IDS
    return {"hits": [asdict(hit) for hit in evaluate(req) if hit.id not in retired or hit.effect != "note"] + [asdict(hit) for hit in extra_hits]}
