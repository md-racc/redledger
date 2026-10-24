"""Deterministic policy with process-local 120-second singleflight retention."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict
from typing import Any

from fastapi import HTTPException

from agentkit.models import GateRequest, GateResponse

from .cache import VerdictCache
from .rules import RuleHit, evaluate

TTL = 120
MAX_ENTRIES = 100_000
MAX_PENDING = 256


class RetainedVerdicts:
    """Shard before VerdictCache's destructive capacity clear; retire only expired shards."""

    def __init__(self) -> None:
        self.generations: list[tuple[float, VerdictCache]] = []

    def prune(self) -> None:
        now = time.monotonic()
        self.generations = [(last, cache) for last, cache in self.generations if now - last <= TTL]

    def get(self, key: str) -> GateResponse | None:
        self.prune()
        for _, cache in reversed(self.generations):
            value = cache.get(key)
            if value is not None:
                return value.model_copy(deep=True)
        return None

    def size(self) -> int:
        self.prune()
        return sum(len(cache._d) for _, cache in self.generations)

    def put(self, key: str, value: GateResponse) -> None:
        self.prune()
        if not self.generations or len(self.generations[-1][1]._d) >= 5000:
            self.generations.append((time.monotonic(), VerdictCache(ttl_sec=TTL)))
        _, cache = self.generations[-1]
        cache.put(key, value.model_copy(deep=True))
        self.generations[-1] = (time.monotonic(), cache)


_cache = RetainedVerdicts()
_pending: dict[str, asyncio.Task[GateResponse]] = {}


def namespace(req: GateRequest) -> str:
    return json.dumps([req.episode_id, req.idempotency_key], separators=(",", ":"))


def _reason(hits: list[RuleHit], verdict: str) -> str:
    if not hits:
        return "No applicable control exceptions."
    prefix = {"block": "Control hold", "escalate": "Needs independent verification", "allow": "Allowed with diagnostic notes"}[verdict]
    return f"{prefix} — {'; '.join(h.detail for h in hits)}"


async def _compute(req: GateRequest, key: str, dry_run: bool = False) -> GateResponse:
    started = time.monotonic()
    try:
        hits = evaluate(req)
        effects = {hit.effect for hit in hits}
        # An unavailable control is diagnostic, never counted as a fraud hit.
        verdict = "escalate" if "unavailable" in effects else "block" if "block" in effects else "escalate" if "review" in effects else "allow"
        # Advisory remains disconnected until the privacy-bounded provider lands.
        response = GateResponse(
            verdict=verdict,
            reason=_reason(hits, verdict),
            confidence=0.98 if verdict == "block" else 0.65 if verdict == "escalate" else 0.99,
            rules_fired=[hit.id for hit in hits],
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        _cache.put(key, response)
        return response
    finally:
        _pending.pop(key, None)


async def decide(req: GateRequest, *, dry_run: bool = False) -> GateResponse:
    key = namespace(req)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    task = _pending.get(key)
    if task is None:
        # Reject new admission, never evict a verdict promised for 120 seconds.
        if len(_pending) >= MAX_PENDING or _cache.size() + len(_pending) >= MAX_ENTRIES:
            raise HTTPException(503, "gate capacity unavailable; retry later with the same key")
        task = asyncio.create_task(_compute(req.model_copy(deep=True), key, dry_run))
        _pending[key] = task
    # Disconnecting one caller must not cancel shared work or invalidate its receipt.
    return (await asyncio.shield(task)).model_copy(deep=True)


def explain(req: GateRequest) -> dict[str, Any]:
    return {"hits": [asdict(hit) for hit in evaluate(req)]}
