"""DroidAgent: base class every red/green/blue-audit agent subclasses.

Responsibilities (so teams don't re-solve them):
  - bind LedgerClient + EventEmitter for the turn (tools reach them via agentkit.tools.ctx)
  - build a Droid Session with a string system prompt, an in-process MCP server of your tools,
    the configured autonomy level, builtin skills disabled, tools restricted to yours
  - stream the turn, forward thinking/tool events to battlefield, enforce the turn timeout
  - DRY_RUN path that calls your `dry_run_turn` with no Droid/LLM access
  - per-turn credit logging

Subclass contract:

    class RedAgent(DroidAgent):
        name = "red"
        autonomy = "high"
        system_prompt = (Path(__file__).parent / "prompts/system.md").read_text()

        def tools(self): return collect_tools(red_tools_module)
        async def build_prompt(self, req): return "Day 3. Pick a scheme and execute it."
        async def dry_run_turn(self, req): ...  # call your tool fns directly
        # optional: async def on_permission(self, request) -> response

The Droid SDK is imported lazily so DRY_RUN and tests work without it installed.
"""

from __future__ import annotations

import asyncio
import functools
import json
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import structlog

from .config import AgentSettings
from .events import EventEmitter
from .ledger_client import LedgerClient
from .models import TurnRequest, TurnResponse, Usage
from .tools import ToolFn, ctx

log = structlog.get_logger(__name__)

_TOOL_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="droid-tool")
# Extra wait on the calling side past the tool's own deadline, so the in-thread cancellation (which
# closes the tool's HTTP calls cleanly) normally wins and the outer wait only catches a wedged thread.
_TOOL_GRACE_SEC = 2.0


class _ThreadSafeEmitter:
    """Lets a tool running on a worker thread narrate through the turn's EventEmitter, whose queue
    belongs to the turn's event loop."""

    def __init__(self, inner: EventEmitter, loop: asyncio.AbstractEventLoop):
        self._inner, self._loop = inner, loop

    def __getattr__(self, name: str) -> Callable[..., None]:
        method = getattr(self._inner, name)
        return lambda *a, **kw: self._loop.call_soon_threadsafe(functools.partial(method, *a, **kw))


class DroidAgent(ABC):
    name: str = "agent"
    autonomy: str = "high"  # off | low | medium | high
    system_prompt: str = "You are an agent."

    def __init__(self, settings: AgentSettings):
        self.s = settings
        self._tool_ids: list[str] | None = None

    # ---------- subclass hooks ----------
    @abstractmethod
    def tools(self) -> list[tuple[str, str, ToolFn]]: ...

    @abstractmethod
    async def build_prompt(self, req: TurnRequest) -> str: ...

    @abstractmethod
    async def dry_run_turn(self, req: TurnRequest) -> str:
        """Deterministic stand-in for a model turn. Must make plausible ledger calls. Returns summary."""

    async def on_permission(self, request: Any) -> Any:
        """Default: approve. Green overrides to mirror blue's gate."""
        from droid_sdk import ToolConfirmationOutcome  # lazy

        return request.respond(ToolConfirmationOutcome.PROCEED_ONCE)

    async def health(self) -> dict[str, Any]:
        return {"ok": True, "agent": self.name, "model": self.s.droid_model, "droid_ok": self._droid_available(), "dry_run": self.s.dry_run}

    # ---------- turn entrypoint ----------
    async def run_turn(self, req: TurnRequest) -> TurnResponse:
        t0 = time.monotonic()
        async with (
            LedgerClient(self.s, episode_id=req.episode_id, day=req.day) as ledger,
            EventEmitter(self.s, episode_id=req.episode_id, day=req.day) as emitter,
        ):
            tokens = ctx.bind(ledger, emitter, req)
            try:
                if self.s.dry_run:
                    summary = await asyncio.wait_for(self.dry_run_turn(req), timeout=self.s.turn_timeout_sec - 5)
                    return TurnResponse(ok=True, summary=f"[dry-run] {summary}", duration_sec=time.monotonic() - t0)
                summary, usage = await self._droid_turn(req, emitter)
                return TurnResponse(ok=True, summary=summary, duration_sec=time.monotonic() - t0, usage=usage)
            except TimeoutError:
                log.error("turn_timeout", agent=self.name, day=req.day)
                return TurnResponse(ok=False, summary="turn timed out", duration_sec=time.monotonic() - t0)
            except Exception as e:  # agent failure never kills the episode
                log.exception("turn_failed", agent=self.name, day=req.day)
                return TurnResponse(ok=False, summary=f"turn failed: {e}", duration_sec=time.monotonic() - t0)
            finally:
                ctx.unbind(tokens)

    # ---------- droid plumbing ----------
    @staticmethod
    def _droid_available() -> bool:
        try:
            import droid_sdk  # noqa: F401

            return True
        except Exception:
            return False

    def _autonomy(self) -> Any:
        from droid_sdk import Autonomy

        return {"off": Autonomy.OFF, "low": Autonomy.LOW, "medium": Autonomy.MEDIUM, "high": Autonomy.HIGH}[self.autonomy]

    def _mcp_server(self) -> Any:
        from droid_sdk.mcp import create_sdk_mcp_server, tool

        wrapped = [tool(n, d, self._offload(fn)) for (n, d, fn) in self.tools()]
        return create_sdk_mcp_server(name=f"{self.name}-ledger", tools=wrapped, version="0.1.0")

    def _tool_timeout_sec(self) -> float:
        """Wall-clock cap on one tool call, measured from when the SDK invokes it.

        Must be (a) strictly below the stream timeout (turn_timeout_sec - 10) so the turn's own deadline
        still fires after a hung tool, and (b) above battlefield's escalation hold, because green's
        gated calls legitimately block until a human decides or ESCALATION_TIMEOUT_SEC (90 s) expires,
        and LedgerClient allows that read up to max(http_timeout_sec, 120) s. Cutting such a call
        short would tell the model "failed" while the payment may still go through. So: the turn
        budget minus 20 s (160 s at the default 180), never below 5 s."""
        return max(5.0, self.s.turn_timeout_sec - 20)

    def _offload(self, fn: ToolFn) -> Callable[..., str]:
        """droid-sdk 0.5.0 stalls the whole run (RunTimeoutError) if an in-process tool yields to the
        event loop, even for `await asyncio.sleep(0.3)`; only tools that return without awaiting work.
        So each tool call runs to completion on a private loop in a worker thread, with its own
        LedgerClient for the same turn, and its narration is posted back to the turn's emitter.

        The SDK itself accepts sync or async handlers (droid_sdk.mcp.tool's `invoke` awaits the result
        only if it is awaitable) and serves them from a uvicorn task on the session's loop, so this sync
        wrapper freezes that loop while the tool runs. That freeze is bounded by _tool_timeout_sec():
        the tool is cancelled inside its thread at the deadline and the model gets an error string;
        nothing is raised through the SDK."""

        name = getattr(fn, "_rl_tool", (getattr(fn, "__name__", "tool"), ""))[0]
        is_ledger_tool = hasattr(fn, "_rl_tool")

        @functools.wraps(fn)
        def sync_tool(*args: Any, **kwargs: Any) -> str:
            turn, emitter = ctx.turn(), ctx.emitter()
            proxy = _ThreadSafeEmitter(emitter, asyncio.get_running_loop()) if emitter else None
            budget = self._tool_timeout_sec()
            deadline = time.monotonic() + budget
            tool_use_id = None
            if is_ledger_tool:  # pin the narration id so a timeout can still close the tool_call event
                tool_use_id = kwargs.setdefault("_tool_use_id", LedgerClient.new_tool_use_id())

            async def run() -> str:
                async with asyncio.timeout(max(0.0, deadline - time.monotonic())):
                    async with LedgerClient(self.s, episode_id=turn.episode_id, day=turn.day) as ledger:
                        tokens = ctx.bind(ledger, proxy, turn)  # type: ignore[arg-type]
                        try:
                            return await fn(*args, **kwargs)
                        finally:
                            ctx.unbind(tokens)

            # The coroutine is created in the worker, so a call cancelled while queued leaves no
            # never-awaited coroutine behind.
            future = _TOOL_POOL.submit(lambda: asyncio.run(run()))
            try:
                return future.result(timeout=max(0.0, deadline - time.monotonic()) + _TOOL_GRACE_SEC)
            except TimeoutError:  # concurrent.futures.TimeoutError is TimeoutError on 3.11+; the in-thread
                # asyncio.timeout surfaces here too, re-raised by future.result()
                started = not future.cancel()  # cancel() only succeeds if it never left the pool queue
                msg = json.dumps(
                    {
                        "error": True,
                        "timeout": True,
                        "tool": name,
                        "detail": (
                            f"tool timed out after {budget:.0f}s; "
                            + ("its outcome is unknown, re-read the books before retrying" if started else "it never ran")
                        ),
                    }
                )
                log.error("tool_timeout", agent=self.name, tool=name, day=turn.day, timeout_sec=budget, started=started)
                if emitter and tool_use_id:
                    emitter.tool_result(tool_use_id, False, msg)
                return msg

        return sync_tool

    async def _droid_turn(self, req: TurnRequest, emitter: EventEmitter) -> tuple[str, Usage | None]:
        from droid_sdk import (
            InteractionHandlers,
            Session,
            SessionConfig,
            TextDelta,
            ThinkingDelta,
            ToolCall,
            ToolResult,
        )

        server = self._mcp_server()
        config = SessionConfig(
            autonomy=self._autonomy(),
            disable_builtin_skills=True,
            system_prompt=self.system_prompt,
            mcp_servers=[server],
            # Only our ledger tools: without this the agent also gets Droid's ~30 built-ins (Read, Grep,
            # Execute, …) and spends the turn reading its own source. In-process MCP tool IDs are
            # "<server>___<tool>" (observed with droid-sdk 0.5.0; list_tools reports source=None).
            restrict_tools=self._tool_ids or [f"{self.name}-ledger___{n}" for (n, _, _) in self.tools()],
        )
        prompt = await self.build_prompt(req)
        from droid_sdk import ReasoningEffort

        async with Session(
            model=self.s.droid_model,
            reasoning_effort=ReasoningEffort(self.s.droid_reasoning) if self.s.droid_reasoning else None,
            config=config,
            interactions=InteractionHandlers(on_permission=self.on_permission),
            api_key=self.s.factory_api_key,
        ) as session:
            if self._tool_ids is None:
                await self._learn_tool_ids(session)
            async with session.stream(prompt, include_partial_messages=True, timeout=self.s.turn_timeout_sec - 10) as stream:
                async for ev in stream:
                    if isinstance(ev, (ThinkingDelta, TextDelta)):
                        emitter.thinking(ev.text)
                    elif isinstance(ev, ToolCall):
                        # tools wrapped by ledger_tool already emit; this catches any native tool
                        pass
                    elif isinstance(ev, ToolResult):
                        pass
            result = stream.result
            usage = None
            if result.usage:
                usage = Usage(
                    factory_credits=result.usage.factory_credits,
                    input_tokens=result.usage.input_tokens,
                    output_tokens=result.usage.output_tokens,
                )
                log.info("turn_usage", agent=self.name, day=req.day, credits=result.usage.factory_credits)
            if not result.success:
                raise RuntimeError(f"droid turn ended: {result.subtype}")
            return result.text, usage

    async def _learn_tool_ids(self, session: Any) -> None:
        """Record exact tool IDs for our MCP server so restrict_tools is right from the next turn.
        Record the observed format in contracts/CHANGELOG.md Findings."""
        try:
            tools = await session.list_tools()
            mine = {n for (n, _, _) in self.tools()}
            ids = [t.id for t in tools if t.id.startswith(f"{self.name}-ledger___") and any(t.id.endswith(n) for n in mine)]
            if ids:
                self._tool_ids = ids
                log.info("tool_ids_learned", agent=self.name, ids=ids)
        except Exception as e:
            log.warning("list_tools_failed", error=str(e))
