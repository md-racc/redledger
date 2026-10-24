"""Gate engine: rules → (optional) LLM → verdict, with an idempotency cache. Owner: Dev M.

Decision policy (tune freely, keep it explainable):
  - any severity-3 hit                      → block
  - two or more hits                        → block
  - exactly one severity-2 hit              → LLM decides (allow/block/escalate) if configured, else escalate in enforce / block in shadow
  - exactly one severity-1 hit              → escalate in enforce mode, allow in shadow
  - no hits                                 → allow
The reason string is what judges read. Write it like a sentence from an auditor.
"""

from __future__ import annotations

import time
from typing import Any

from agentkit.models import GateRequest, GateResponse

from .cache import VerdictCache
from .llm import LLMGate
from .rules import RuleHit, evaluate

_cache = VerdictCache(ttl_sec=120)
_llm = LLMGate.from_env()


def _reason(hits: list[RuleHit], verdict: str) -> str:
    if not hits:
        return "No control exceptions."
    core = "; ".join(h.detail for h in hits)
    return {"block": f"Blocked — {core}.", "escalate": f"Needs human review — {core}.", "allow": f"Allowed with notes — {core}."}[verdict]


async def decide(req: GateRequest) -> GateResponse:
    cached = _cache.get(req.idempotency_key)
    if cached:
        return cached
    t0 = time.monotonic()
    hits = evaluate(req)
    ids = [h.id for h in hits]
    sev = max((h.severity for h in hits), default=0)
    confidence: float | None = None

    if sev >= 3 or len(hits) >= 2:
        verdict = "block"
        confidence = 0.95
    elif sev == 2:
        if _llm.enabled:
            verdict, confidence, llm_reason = await _llm.judge(req, hits)
            resp = GateResponse(
                verdict=verdict, reason=llm_reason, confidence=confidence, rules_fired=ids + ["llm_judgment"], latency_ms=int((time.monotonic() - t0) * 1000)
            )
            _cache.put(req.idempotency_key, resp)
            return resp
        verdict = "escalate" if req.controller_mode == "enforce" else "block"
        confidence = 0.7
    elif sev == 1:
        verdict = "escalate" if req.controller_mode == "enforce" else "allow"
        confidence = 0.6
    else:
        verdict = "allow"
        confidence = 0.99

    resp = GateResponse(verdict=verdict, reason=_reason(hits, verdict), confidence=confidence, rules_fired=ids, latency_ms=int((time.monotonic() - t0) * 1000))
    _cache.put(req.idempotency_key, resp)
    return resp


def explain(req: GateRequest) -> dict[str, Any]:
    """Debug helper: rules and what they'd say, without caching."""
    return {"hits": [h.__dict__ for h in evaluate(req)]}
