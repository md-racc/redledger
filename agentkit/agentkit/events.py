"""EventEmitter: agents narrate to battlefield via POST /api/events.

Only agent.thinking / agent.tool_call / agent.tool_result are accepted from agents. Emission is
best-effort and batched; a failed emit never fails a turn.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import structlog

from .config import AgentSettings
from .models import AGENT_EMITTABLE, AgentEventCreate, EventType, agent_may_emit

log = structlog.get_logger(__name__)


class EventEmitter:
    def __init__(self, settings: AgentSettings, *, episode_id: str, day: int, flush_every: float = 0.5, max_batch: int = 50):
        self.s = settings
        self.episode_id = episode_id
        self.day = day
        self._q: asyncio.Queue[AgentEventCreate] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._client: httpx.AsyncClient | None = None
        self._flush_every = flush_every
        self._max_batch = max_batch
        self._thinking_buf: list[str] = []

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
        await self.flush()
        if self._task:
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
        self._flush_thinking()
        await self._drain()

    # ---------- internals ----------
    def _flush_thinking(self) -> None:
        if self._thinking_buf:
            self.emit(EventType.AGENT_THINKING, {"text": "".join(self._thinking_buf)})
            self._thinking_buf.clear()

    async def _pump(self) -> None:
        while True:
            await asyncio.sleep(self._flush_every)
            await self._drain()

    async def _drain(self) -> None:
        if self._client is None:
            return
        batch: list[dict[str, Any]] = []
        while not self._q.empty() and len(batch) < self._max_batch:
            batch.append(self._q.get_nowait().model_dump())
        if not batch:
            return
        try:
            r = await self._client.post("/events", json=batch)
            if r.status_code >= 400:
                log.warning("event_emit_failed", status=r.status_code, body=r.text[:200])
        except Exception as e:  # never fail a turn over narration
            log.warning("event_emit_error", error=str(e))
