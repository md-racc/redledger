"""Service-loop-owned, episode/version-scoped playbook snapshots."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass, field

from agentkit.config import AgentSettings
from agentkit.ledger_client import LedgerClient
from agentkit.models import GateRequest

from . import learned, rules

READ_TIMEOUT = 0.5


@dataclass
class Refresh:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0


class Playbooks:
    def __init__(self, settings: AgentSettings):
        self.settings = settings
        self.entries: OrderedDict[tuple[str, int], dict] = OrderedDict()
        self.latest: dict[str, dict] = {}
        self.refreshes: dict[tuple[str, int], Refresh] = {}

    async def hits(self, req: GateRequest) -> list[rules.RuleHit]:
        if req.playbook_version is None or req.action not in rules.INVOICE_ACTIONS:
            return []
        key = (req.episode_id, req.playbook_version)
        try:
            if key in self.entries:
                self.entries.move_to_end(key)
                return learned.evaluate(req, self.entries[key])
            # One bounded read per new episode/version, permitted by the lineage contract.
            # Cached gates never wait for refreshes; unrelated cold keys load independently.
            refresh = self.refreshes.setdefault(key, Refresh())
            refresh.users += 1
            try:
                async with asyncio.timeout(READ_TIMEOUT):
                    async with refresh.lock:
                        if key not in self.entries:
                            async with LedgerClient(self.settings, episode_id=req.episode_id, day=req.day) as ledger:
                                book = await ledger.get_playbook()
                            if not isinstance(book, dict) or type(book.get("version")) is not int or book["version"] != req.playbook_version:
                                raise ValueError("playbook version unavailable")
                            if not isinstance(book.get("content"), dict):
                                raise ValueError("playbook content unavailable")
                            self.entries[key] = deepcopy(book["content"])
                            self.latest[req.episode_id] = deepcopy(book["content"])
                            while len(self.entries) > 128:
                                self.entries.popitem(last=False)
                        self.entries.move_to_end(key)
                        content = self.entries[key]
            finally:
                refresh.users -= 1
                if not refresh.users:
                    self.refreshes.pop(key)
            return learned.evaluate(req, content)
        except Exception:
            stale_content = self.latest.get(req.episode_id)
            if stale_content is not None:
                return learned.evaluate(req, stale_content)
            return [
                rules.RuleHit(
                    "learned:verification_unavailable", 0, "Requested playbook version is unavailable; independent verification is required.", "unavailable"
                )
            ]
