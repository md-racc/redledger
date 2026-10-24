"""LLM judgment for ambiguous gate cases. Owner: Dev M.

Direct API call (not Droid) because this is on the hot path. Provider-agnostic shell; wire one
provider (Gemini is the MLH-prize-friendly default) and return structured output. If no key is
configured, `enabled` is False and the engine falls back to escalate/block.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
import structlog

from agentkit.models import GateRequest

from .rules import RuleHit

log = structlog.get_logger(__name__)

SYSTEM = (
    "You are a financial controller reviewing one accounts-payable action. You receive the action, the amount, "
    "deterministic rule hits, and ledger context. Decide allow, block, or escalate (to a human). Respond ONLY with JSON: "
    '{"verdict": "allow|block|escalate", "confidence": 0.0-1.0, "reason": "one or two plain sentences an auditor would write"}. '
    "Block when the evidence points to fraud. Escalate when a reasonable human would want to look. Allow when the rule hit has an innocent explanation in the context."
)


class LLMGate:
    def __init__(self, provider: str | None, api_key: str | None, model: str | None):
        self.provider, self.api_key, self.model = provider, api_key, model

    @classmethod
    def from_env(cls) -> LLMGate:
        return cls(os.environ.get("BLUE_GATE_LLM_PROVIDER"), os.environ.get("BLUE_GATE_LLM_API_KEY"), os.environ.get("BLUE_GATE_LLM_MODEL"))

    @property
    def enabled(self) -> bool:
        return bool(self.provider and self.api_key and self.model)

    async def judge(self, req: GateRequest, hits: list[RuleHit]) -> tuple[str, float, str]:
        payload = {"action": req.action, "amount": req.amount, "day": req.day, "rule_hits": [h.__dict__ for h in hits], "context": _compact(req.context)}
        try:
            text = await self._call(json.dumps(payload))
            j = json.loads(text[text.find("{") : text.rfind("}") + 1])
            v = j.get("verdict", "escalate")
            if v not in ("allow", "block", "escalate"):
                v = "escalate"
            return v, float(j.get("confidence", 0.5)), str(j.get("reason", ""))[:400]
        except Exception as e:
            log.warning("llm_gate_failed", error=str(e))
            return "escalate", 0.5, f"Needs human review — {'; '.join(h.detail for h in hits)} (automated judgment unavailable)."

    async def _call(self, user: str) -> str:
        if self.provider == "gemini":
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
            body = {
                "system_instruction": {"parts": [{"text": SYSTEM}]},
                "contents": [{"parts": [{"text": user}]}],
                "generationConfig": {"response_mime_type": "application/json", "temperature": 0},
            }
            async with httpx.AsyncClient(timeout=6) as c:
                r = await c.post(url, json=body)
                r.raise_for_status()
                return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        if self.provider == "anthropic":
            async with httpx.AsyncClient(timeout=6) as c:
                r = await c.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": self.api_key or "", "anthropic-version": "2023-06-01"},
                    json={"model": self.model, "max_tokens": 300, "system": SYSTEM, "messages": [{"role": "user", "content": user}]},
                )
                r.raise_for_status()
                return r.json()["content"][0]["text"]
        if self.provider == "openai":
            async with httpx.AsyncClient(timeout=6) as c:
                r = await c.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": self.model,
                        "temperature": 0,
                        "response_format": {"type": "json_object"},
                        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
                    },
                )
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"]
        raise ValueError(f"unknown provider {self.provider}")


def _compact(ctx: dict[str, Any]) -> dict[str, Any]:
    """Trim context to what fits a fast call."""
    out: dict[str, Any] = {}
    for k in ("invoice", "vendor", "po", "proposed_po", "vendor_change", "expense", "employee"):
        if ctx.get(k):
            out[k] = ctx[k]
    for k in ("vendor_recent_changes", "vendor_paid_invoices", "vendor_open_invoices", "flags", "employee_expense_history"):
        if ctx.get(k):
            out[k] = ctx[k][:5]
    return out
