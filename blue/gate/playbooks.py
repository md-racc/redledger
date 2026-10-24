"""Service-loop-owned, episode/version-scoped playbook snapshots."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from copy import deepcopy

from agentkit.config import AgentSettings
from agentkit.ledger_client import LedgerClient
from agentkit.models import GateRequest

from . import learned, rules

READ_TIMEOUT = 0.5


class Playbooks:
    def __init__(self, settings: AgentSettings):
        self.settings = settings
        self.entries: OrderedDict[tuple[str, int], dict] = OrderedDict()
        self.lock = asyncio.Lock()

    async def hits(self, req: GateRequest) -> list[rules.RuleHit]:
        if req.playbook_version is None or req.action not in rules.INVOICE_ACTIONS:
            return []
        key = (req.episode_id, req.playbook_version)
        try:
            # One bounded read per new episode/version, permitted by the lineage contract.
            # Common-case gates never read the ledger. Never reuse a different version.
            async with asyncio.timeout(READ_TIMEOUT):
                async with self.lock:
                    if key not in self.entries:
                        async with LedgerClient(self.settings, episode_id=req.episode_id, day=req.day) as ledger:
                            book = await ledger.get_playbook()
                        if not isinstance(book, dict) or type(book.get("version")) is not int or book["version"] != req.playbook_version:
                            raise ValueError("playbook version unavailable")
                        if not isinstance(book.get("content"), dict):
                            raise ValueError("playbook content unavailable")
                        self.entries[key] = deepcopy(book["content"])
                        while len(self.entries) > 128:
                            self.entries.popitem(last=False)
                    self.entries.move_to_end(key)
                    content = self.entries[key]
            return learned.evaluate(req, content)
        except Exception:
            return [
                rules.RuleHit(
                    "learned:verification_unavailable", 0, "Requested playbook version is unavailable; independent verification is required.", "unavailable"
                )
            ]
