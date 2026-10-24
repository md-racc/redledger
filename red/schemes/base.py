"""Scheme base class. Owner: Dev Al.

A scheme is one fraud template. It knows how to describe itself (for the judge-facing catalog),
whether it is viable against the current ledger state, and how to execute itself through the
red tool surface. Red's Droid session chooses *which* scheme and *how* to parameterize it; the
scheme keeps execution bounded and legible.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from agentkit import AttackCreate, LedgerClient
from agentkit.models import Scheme


class SchemeBase(ABC):
    id: str
    display_name: str
    story: str  # one sentence a non-technical judge understands
    params_schema: dict[str, Any] = {"type": "object", "properties": {}}
    expected_impact: dict[str, float] = {"min": 0, "max": 0}

    def catalog(self) -> Scheme:
        return Scheme(id=self.id, display_name=self.display_name, story=self.story, params_schema=self.params_schema, expected_impact=self.expected_impact)

    @abstractmethod
    async def viable(self, ledger: LedgerClient) -> bool:
        """Can this scheme run against the current books? (e.g. duplicate_invoice needs a paid invoice)"""

    @abstractmethod
    async def plan(self, ledger: LedgerClient, params: dict[str, Any]) -> dict[str, Any]:
        """Resolve params + ledger state into a concrete plan. Must include 'target_amount'."""

    @abstractmethod
    async def execute(self, ledger: LedgerClient, plan: dict[str, Any]) -> str:
        """Perform the attack through the red tool surface. Return a one-line summary."""

    def attack_decl(self, plan: dict[str, Any], params: dict[str, Any]) -> AttackCreate:
        return AttackCreate(scheme_id=self.id, display_name=self.display_name, story=self.story, params=params, target_amount=float(plan["target_amount"]))
