"""TTL cache keyed by idempotency_key so battlefield's call and green's mirror agree. Owner: Dev M."""

from __future__ import annotations

import time

from agentkit.models import GateResponse


class VerdictCache:
    def __init__(self, ttl_sec: int = 120):
        self.ttl = ttl_sec
        self._d: dict[str, tuple[float, GateResponse]] = {}

    def get(self, key: str) -> GateResponse | None:
        item = self._d.get(key)
        if not item:
            return None
        ts, v = item
        if time.monotonic() - ts > self.ttl:
            self._d.pop(key, None)
            return None
        return v

    def put(self, key: str, v: GateResponse) -> None:
        if len(self._d) > 5000:
            self._d.clear()
        self._d[key] = (time.monotonic(), v)
