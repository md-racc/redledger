"""EventEmitter: agents narrate to battlefield via POST /api/events.

Only agent.thinking / agent.tool_call / agent.tool_result are accepted from agents. Emission is
best-effort and batched; a failed emit never fails a turn.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

import httpx
import structlog

from .config import AgentSettings
from .models import AGENT_EMITTABLE, AgentEventCreate, EventType, agent_may_emit

log = structlog.get_logger(__name__)


class EventEmitter:
    def __init__(
        self,
        settings: AgentSettings,
        *,
        episode_id: str,
        day: int,
        flush_every: float = 0.5,
        max_batch: int = 50,
        flush_budget_sec: float | None = None,
    ):
        self.s = settings
        self.episode_id = episode_id
        self.day = day
        self._q: asyncio.Queue[AgentEventCreate] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._client: httpx.AsyncClient | None = None
        self._flush_every = flush_every
        self._max_batch = max_batch
        self._thinking_buf: list[str] = []
        # Total wall-clock budget for the final flush, so a dead battlefield can't hang a turn.
        self._flush_budget = settings.http_timeout_sec if flush_budget_sec is None else flush_budget_sec
        # One sender at a time: the pump and an explicit flush() never interleave POSTs or split a batch.
        self._send_lock = asyncio.Lock()

    async def __aenter__(self) -> EventEmitter:
        self._client = httpx.AsyncClient(
            base_url=f"{self.s.battlefield_url.rstrip('/')}/api",
            timeout=self.s.http_timeout_sec,
            headers={
                "Authorization": f"Bearer {self.s.internal_token}",
                "X-Agent": self.s.agent_name,
                "X-Episode": self.episode_id,
                "X-Day": str(self.day),
            },
        )
        self._task = asyncio.create_task(self._pump())
        return self

    async def __aexit__(self, *exc: object) -> None:
        try:
            await self.flush()
        finally:
            if self._task:
                # flush() already sent (or dropped) everything queued, so the pump is idle here; only
                # stragglers posted after the flush (late call_soon_threadsafe narration) can be lost.
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
            if self._client:
                await self._client.aclose()

    # ---------- public ----------
    def emit(self, type_: str, payload: dict[str, Any]) -> None:
        if not agent_may_emit(type_):
            raise ValueError(f"agents may only emit {sorted(AGENT_EMITTABLE)} or x.<area>.<name>, got {type_}")
        self._q.put_nowait(AgentEventCreate(type=type_, payload=payload))

    def thinking(self, text: str) -> None:
        """Buffer thinking deltas; flushed as one event when >200 chars or on tool call."""
        self._thinking_buf.append(text)
        if sum(len(t) for t in self._thinking_buf) > 200:
            self._flush_thinking()

    def tool_call(self, tool: str, args: dict[str, Any], tool_use_id: str) -> None:
        self._flush_thinking()
        self.emit(EventType.AGENT_TOOL_CALL, {"tool": tool, "args": args, "tool_use_id": tool_use_id})

    def tool_result(self, tool_use_id: str, ok: bool, summary: str) -> None:
        self.emit(EventType.AGENT_TOOL_RESULT, {"tool_use_id": tool_use_id, "ok": ok, "summary": summary[:500]})

    def custom(self, name: str, payload: dict[str, Any]) -> None:
        """Emit `x.<agent>.<name>` — a team-defined event. Frontend shows it generically."""
        self.emit(f"x.{self.s.agent_name}.{name}", payload)

    async def flush(self) -> None:
        """Send everything queued (thinking buffer included), batch by batch, within the flush budget.
        Whatever is still queued when the budget runs out is dropped and logged as `events_dropped`."""
        self._flush_thinking()
        if self._client is None:  # not entered yet: nothing to send with, keep the queue
            return
        deadline = time.monotonic() + self._flush_budget
        async with self._send_lock:
            while not self._q.empty():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._drop_queued("flush_budget_exhausted")
                    return
                await self._send_batch(timeout=remaining)

    # ---------- internals ----------
    def _flush_thinking(self) -> None:
        if self._thinking_buf:
            self.emit(EventType.AGENT_THINKING, {"text": "".join(self._thinking_buf)})
            self._thinking_buf.clear()

    def _drop_queued(self, reason: str) -> None:
        dropped = 0
        while not self._q.empty():
            self._q.get_nowait()
            dropped += 1
        if dropped:
            log.warning("events_dropped", count=dropped, reason=reason, agent=self.s.agent_name, episode_id=self.episode_id, day=self.day)

    async def _pump(self) -> None:
        while True:
            await asyncio.sleep(self._flush_every)
            await self._drain()

    async def _drain(self) -> None:
        """Pump tick: send everything queued, one batch per POST. The lock is taken per batch so a
        flush() waits for at most one in-flight POST before it takes over."""
        while self._client is not None and not self._q.empty():
            async with self._send_lock:
                await self._send_batch(timeout=self.s.http_timeout_sec)

    async def _send_batch(self, *, timeout: float) -> None:
        """Dequeue ≤ max_batch events and POST them. Caller holds `_send_lock` and has checked
        `_client`. Every dequeued event is either sent or logged as dropped, never silently lost."""
        assert self._client is not None
        batch: list[dict[str, Any]] = []
        while not self._q.empty() and len(batch) < self._max_batch:
            batch.append(self._q.get_nowait().model_dump())
        if not batch:
            return
        try:
            # Hard cap on the whole POST (httpx timeouts are per phase); a cut-off batch counts as dropped.
            async with asyncio.timeout(max(timeout, 0.001)):
                # battlefield requires X-Tool-Use-Id on every agent write; a narration batch is its own write
                r = await self._client.post("/events", json=batch, headers={"X-Tool-Use-Id": uuid.uuid4().hex})
            if r.status_code >= 400:
                log.warning("event_emit_failed", status=r.status_code, body=r.text[:200], dropped=len(batch))
        except Exception as e:  # never fail a turn over narration
            log.warning("event_emit_error", error=str(e), dropped=len(batch))
