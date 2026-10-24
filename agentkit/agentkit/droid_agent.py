"""DroidAgent: base class every red/green/blue-audit agent subclasses.

Responsibilities (so teams don't re-solve them):
  - bind LedgerClient + EventEmitter for the turn (tools reach them via agentkit.tools.ctx)
  - build a Droid Session with a string system prompt, an in-process MCP server of your tools,
    the configured autonomy level, builtin skills disabled, tools restricted to yours
  - stream the turn, forward thinking/tool events to battlefield, enforce the turn timeout
  - DRY_RUN path that calls your `dry_run_turn` with no Droid/LLM access
  - per-turn credit logging
  - invocation identity (agentkit.invocation): the Droid tool_use_id a permission request shows is
    the one on that call's agent.tool_call/agent.tool_result and on its ledger writes' X-Tool-Use-Id;
    a call the permission handler cancels (or that never runs) still gets exactly one event pair

Subclass contract:

    class RedAgent(DroidAgent):
        name = "red"
        autonomy = "high"
        system_prompt = (Path(__file__).parent / "prompts/system.md").read_text()

        def tools(self): return collect_tools(red_tools_module)
        async def build_prompt(self, req): return "Day 3. Pick a scheme and execute it."
        async def dry_run_turn(self, req): ...  # call your tool fns directly
        # optional: async def reflect(self, req) -> ReflectResponse      (live; between generations)
        # optional: async def dry_run_reflect(self, req) -> ReflectResponse  (DRY_RUN; no model calls)
        # optional: async def on_permission(self, request) -> response
        #   self.tool_uses(request) gives [ToolUse(tool_use_id, tool, args, source)] for your tools;
        #   key a mirror on use.tool_use_id: it is the X-Tool-Use-Id of that call's first ledger write.

The Droid SDK is imported lazily so DRY_RUN and tests work without it installed.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import functools
import inspect
import json
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import structlog

from .config import AgentSettings
from .events import EventEmitter
from .invocation import (
    SOURCE_EXPLICIT,
    SOURCE_LOCAL,
    SOURCE_STREAM,
    Invocation,
    InvocationRegistry,
    ToolUse,
    bind_invocation,
    bind_registry,
    current_registry,
)
from .ledger_client import LedgerClient
from .models import ReflectRequest, ReflectResponse, TurnRequest, TurnResponse, Usage
from .tools import ToolFn, _args_payload, ctx, error_summary

log = structlog.get_logger(__name__)

_TOOL_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="droid-tool")
# Extra wait on the calling side past the tool's own deadline, so the in-thread cancellation (which
# closes the tool's HTTP calls cleanly) normally wins and the outer wait only catches a wedged thread.
_TOOL_GRACE_SEC = 2.0
# Floor on a clamped tool budget: a call made with the turn's tool time all but spent still gets to try.
_MIN_TOOL_SEC = 1.0
# Monotonic instant by which every tool of the current turn must have finished (set by run_turn). The
# SDK's tool-handler tasks are created inside the turn and copy this context.
_tool_deadline: contextvars.ContextVar[float | None] = contextvars.ContextVar("rl_tool_deadline", default=None)


class _ToolDeadline(Exception):
    """Our per-tool deadline fired inside the worker (as opposed to a TimeoutError of the tool's own)."""


class _WorkerEmitter:
    """The turn's EventEmitter as seen by a tool running on a worker thread.

    While the call is open, narration is buffered and replayed on the loop thread, in order, before
    the call's agent.tool_result (so nothing a tool says lands after its result). Once the call is
    closed (the tool outlived its deadline), late narration is posted to the loop as best-effort."""

    def __init__(self, inner: EventEmitter, loop: asyncio.AbstractEventLoop):
        self._inner, self._loop = inner, loop
        self._lock = threading.Lock()
        self._buf: list[Callable[[], None]] = []
        self._open = True

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._inner, name)
        if not callable(attr):
            return attr

        def call(*a: Any, **kw: Any) -> None:
            bound = functools.partial(attr, *a, **kw)
            with self._lock:
                if self._open:
                    self._buf.append(bound)
                    return
            self._loop.call_soon_threadsafe(bound)

        return call

    def drain(self) -> None:
        """Loop thread only: replay buffered narration and stop buffering."""
        with self._lock:
            buf, self._buf, self._open = self._buf, [], False
        for bound in buf:
            try:
                bound()
            except Exception as e:  # e.g. a disallowed event type; never fail the tool over narration
                log.warning("tool_narration_failed", error=str(e))


_mcp_context_logged = False


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _strings(v)


def _mcp_request_hints(agent: str) -> list[str]:
    """String values in the current MCP tools/call request's `_meta`. The SDK passes the tool handler
    only its arguments (droid_sdk/mcp.py:132-136, 285-295); the MCP server's request_ctx is the only
    other request data reachable. Droid CLI 0.249.0 sends `_meta:{assemblySessionId, caller}` there (no
    tool_use_id), so today these hints never match; the registry accepts one only if it equals an id the
    SDK reported. The first call per process logs the `_meta` keys and header names (names only) the
    CLI actually sends, so a CLI upgrade that adds the id shows up in the logs."""
    global _mcp_context_logged
    try:
        from mcp.server.lowlevel.server import request_ctx

        rc = request_ctx.get()
    except (ImportError, LookupError):
        return []
    meta = getattr(rc, "meta", None)
    extra = meta.model_dump(exclude_none=True) if meta is not None else {}
    if not _mcp_context_logged:
        _mcp_context_logged = True
        request = getattr(rc, "request", None)
        headers = getattr(request, "headers", None)
        log.info(
            "mcp_call_context",
            agent=agent,
            request_id=str(getattr(rc, "request_id", "")),
            meta_keys=sorted(extra),
            header_names=sorted(headers.keys()) if headers is not None else None,
        )
    return list(_strings(extra))


def _option_value(option: Any) -> Any:
    return getattr(option, "value", option)


def _selected(request: Any, response: Any) -> str:
    """The outcome the SDK will actually apply: an invalid or unoffered response becomes cancel
    (droid_sdk/_high_level/interaction_adapter.py:254-283)."""
    selected = _option_value(getattr(response, "selected_option", None))
    offered = {_option_value(getattr(o, "value", None)) for o in getattr(request, "options", None) or ()}
    if selected is None or selected not in offered:
        return "cancel"
    return str(selected)


def _cancel_response(request: Any, comment: str) -> Any | None:
    for option in getattr(request, "options", None) or ():
        if _option_value(getattr(option, "value", None)) == "cancel":
            return request.respond(option.value, comment=comment)
    return None


class DroidAgent(ABC):
    name: str = "agent"
    autonomy: str = "high"  # off | low | medium | high
    system_prompt: str = "You are an agent."

    def __init__(self, settings: AgentSettings):
        self.s = settings
        self._tool_ids: list[str] | None = None
        tool_cap = self._tool_timeout_sec()
        if tool_cap < settings.escalation_timeout_sec + settings.http_timeout_sec:
            # A gated call may legitimately wait ESCALATION_TIMEOUT_SEC for a human. Cut off sooner, the
            # model hears "timed out" while battlefield may still execute it, and a retry can double-pay.
            log.warning(
                "tool_timeout_below_escalation_hold",
                agent=self.name,
                tool_timeout_sec=tool_cap,
                escalation_timeout_sec=settings.escalation_timeout_sec,
                http_timeout_sec=settings.http_timeout_sec,
                turn_timeout_sec=settings.turn_timeout_sec,
                hint="raise TURN_TIMEOUT_SEC to at least ESCALATION_TIMEOUT_SEC + HTTP_TIMEOUT_SEC + 20",
            )

    # ---------- subclass hooks ----------
    @abstractmethod
    def tools(self) -> list[tuple[str, str, ToolFn]]: ...

    @abstractmethod
    async def build_prompt(self, req: TurnRequest) -> str: ...

    @abstractmethod
    async def dry_run_turn(self, req: TurnRequest) -> str:
        """Deterministic stand-in for a model turn. Must make plausible ledger calls. Returns summary."""

    async def on_permission(self, request: Any) -> Any:
        """Default: approve. Green overrides to mirror blue's gate.

        Runs inside _permission_entry, which has already registered the request's tool uses (so
        `self.tool_uses(request)` and the later execution agree on each tool_use_id) and which emits
        the event pair for every one of ours if this returns CANCEL (or raises: fail closed)."""
        from droid_sdk import ToolConfirmationOutcome  # lazy

        return request.respond(ToolConfirmationOutcome.PROCEED_ONCE)

    def tool_uses(self, request: Any) -> list[ToolUse]:
        """Our MCP tool uses in a droid_sdk PermissionRequest: tool_use_id (the Droid SDK's), short tool
        name, arguments. The id is what this call's agent.tool_call/tool_result carry and the
        X-Tool-Use-Id of its first ledger write (`<id>:<n>` for the n-th), so a mirror of the ledger
        gate (green -> POST blue/gate) uses it as idempotency_key."""
        reg = current_registry() or self._new_registry(None)
        return reg.observe_permission(request)

    def record_cancelled(self, use: ToolUse, reason: str, *, registry: InvocationRegistry | None = None) -> None:
        """Emit agent.tool_call + agent.tool_result(ok=false, reason) for a tool use that will not run.
        Exactly once per tool_use_id; a no-op if that call already ran or was already closed. Called
        for you on CANCEL; override to add narration (call super)."""
        reg = registry or current_registry()
        if reg is None:  # outside a live turn: nothing else can narrate it
            em = ctx.emitter()
            if em:
                em.tool_call(use.tool, use.args, use.tool_use_id)
                em.tool_result(use.tool_use_id, False, json.dumps({"cancelled": True, "tool": use.tool, "reason": reason}))
            return
        reg.observe(use.tool_use_id, use.tool, use.args, use.source)
        reg.cancelled(use.tool_use_id, reason)

    async def reflect(self, req: ReflectRequest) -> ReflectResponse:
        """Between generations of a lineage: read `req.review` (the after-action review) and the current
        `req.playbook`, return new playbook content, or `playbook=None` to keep it. Battlefield writes the
        version; do not write the ledger here (no active turn, so it would 409). Default keeps it."""
        return ReflectResponse(ok=True, rationale="default reflect: playbook kept")

    async def dry_run_reflect(self, req: ReflectRequest) -> ReflectResponse:
        """DRY_RUN stand-in for `reflect`: deterministic, no model calls. Default keeps the playbook."""
        return ReflectResponse(ok=True, rationale="[dry-run] playbook kept")

    async def health(self) -> dict[str, Any]:
        return {"ok": True, "agent": self.name, "model": self.s.droid_model, "droid_ok": self._droid_available(), "dry_run": self.s.dry_run}

    # ---------- turn entrypoint ----------
    async def run_turn(self, req: TurnRequest) -> TurnResponse:
        t0 = time.monotonic()
        async with (
            LedgerClient(self.s, episode_id=req.episode_id, day=req.day) as ledger,
            EventEmitter(self.s, episode_id=req.episode_id, day=req.day, flush_budget_sec=self._flush_budget_sec()) as emitter,
        ):
            tokens = ctx.bind(ledger, emitter, req)
            deadline_token = _tool_deadline.set(t0 + self._tool_timeout_sec())
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
                _tool_deadline.reset(deadline_token)
                ctx.unbind(tokens)

    # ---------- reflect entrypoint ----------
    async def run_reflect(self, req: ReflectRequest) -> ReflectResponse:
        """POST /reflect. A failure or timeout keeps the playbook (ok=false), never a 500."""
        hook = self.dry_run_reflect if self.s.dry_run else self.reflect
        try:
            return await asyncio.wait_for(hook(req), timeout=self.s.turn_timeout_sec - 10)
        except TimeoutError:
            log.error("reflect_timeout", agent=self.name, lineage_id=req.lineage_id, generation=req.generation)
            return ReflectResponse(ok=False, rationale="reflect timed out")
        except Exception as e:
            log.exception("reflect_failed", agent=self.name, lineage_id=req.lineage_id, generation=req.generation)
            return ReflectResponse(ok=False, rationale=f"reflect failed: {e}")

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

    def _new_registry(self, emitter: EventEmitter | None) -> InvocationRegistry:
        return InvocationRegistry(f"{self.name}-ledger", [(n, fn) for (n, _, fn) in self.tools()], emitter, require_permission=self.autonomy == "off")

    def _mcp_server(self, registry: InvocationRegistry | None = None) -> Any:
        from droid_sdk.mcp import create_sdk_mcp_server, tool

        wrapped = [tool(n, d, self._offload(fn, registry=registry)) for (n, d, fn) in self.tools()]
        return create_sdk_mcp_server(name=f"{self.name}-ledger", tools=wrapped, version="0.1.0")

    async def _permission_entry(self, registry: InvocationRegistry, request: Any) -> Any:
        """What the SDK actually calls. Registers the request's tool uses before on_permission runs (the
        CLI executes only after we answer, so the registration always precedes the execution), and
        closes the event pair of every one of ours that will not run."""
        uses = registry.observe_permission(request)
        try:
            response = self.on_permission(request)
            if inspect.isawaitable(response):
                response = await response
        except Exception as e:  # fail closed, with the reason logged (the SDK would cancel silently)
            log.warning("permission_handler_error", agent=self.name, error=str(e), tool_use_ids=[u.tool_use_id for u in uses])
            response = _cancel_response(request, f"permission handler error: {type(e).__name__}")
            if response is None:
                raise
        if _selected(request, response) == "cancel":
            reason = getattr(response, "comment", None) or "cancelled by the permission handler"
            for use in uses:
                self.record_cancelled(use, reason, registry=registry)
        else:
            for use in uses:
                registry.permission_resolved(use.tool_use_id, approved=True)
        return response

    def _flush_budget_sec(self) -> float:
        """Cap on the end-of-turn event flush. The stream may use up to TURN_TIMEOUT_SEC - 10 and
        battlefield waits TURN_TIMEOUT_SEC + 5 for the HTTP reply, so the flush gets at most 5 s of the
        remaining 15 s (session teardown needs the rest)."""
        return min(self.s.http_timeout_sec, 5.0)

    def _tool_timeout_sec(self) -> float:
        """Wall-clock cap on one tool call, measured from when the SDK invokes it.

        Must be (a) strictly below the stream timeout (turn_timeout_sec - 10). While a tool runs the
        SDK's loop is frozen (see _offload), so the stream timeout cannot fire mid-tool; this cap is
        what ends the freeze, and it has to leave the turn time to wrap up once the loop resumes. And
        (b) above battlefield's escalation hold, because green's gated calls legitimately block until a
        human decides or ESCALATION_TIMEOUT_SEC (90 s) expires, and LedgerClient.read_timeout_sec()
        allows that read (hold + gate + 15 s). Cutting such a call short would tell the model "failed"
        while the payment may still go through (__init__ warns when (b) can't hold). So: the turn budget
        minus 20 s (160 s at the default 180), never below 5 s. It is also the turn-wide window: run_turn
        sets the tool deadline to turn start + this, and _tool_budget_sec() clamps each call to it."""
        return max(5.0, self.s.turn_timeout_sec - 20)

    def _tool_budget_sec(self, tool: str) -> float:
        """This call's budget: _tool_timeout_sec(), clamped to what the turn has left. The cap alone is
        per call, so a second long call (two held escalations) could run past the stream timeout and
        battlefield's TURN_TIMEOUT_SEC + 5 wait for /turn; the turn-wide deadline (turn start +
        _tool_timeout_sec()) keeps every call inside the same window one call gets. A budget below the
        escalation hold is logged: a gated call may then be cut off while battlefield still holds it
        for a human (its outcome is then unknown to the model)."""
        cap = self._tool_timeout_sec()
        deadline = _tool_deadline.get()
        if deadline is None:  # called outside run_turn
            return cap
        budget = max(_MIN_TOOL_SEC, min(cap, deadline - time.monotonic()))
        if budget < self.s.escalation_timeout_sec:
            log.warning(
                "tool_budget_below_escalation_hold",
                agent=self.name,
                tool=tool,
                budget_sec=round(budget, 1),
                escalation_timeout_sec=self.s.escalation_timeout_sec,
                detail="turn time is mostly spent; a held gated call may be cut off before the human decides",
            )
        return budget

    def _begin_invocation(self, name: str, kwargs: dict[str, Any], registry: InvocationRegistry | None) -> Invocation:
        explicit = kwargs.pop("_tool_use_id", None)
        if explicit:
            return Invocation(explicit, name, source=SOURCE_EXPLICIT)
        if registry is not None:
            use = registry.claim(name, kwargs, _mcp_request_hints(self.name))
            if use is not None:
                return Invocation(use.tool_use_id, name, source=use.source)
            local_id = LedgerClient.new_tool_use_id()
            registry.note_unlinked(name, kwargs, local_id)
            log.warning(
                "tool_use_id_unverified",
                agent=self.name,
                tool=name,
                tool_use_id=local_id,
                detail="the SDK reported no matching approved tool use; using a UUID4",
            )
            return Invocation(local_id, name, source=SOURCE_LOCAL)
        return Invocation(LedgerClient.new_tool_use_id(), name, source=SOURCE_LOCAL)

    def _offload(self, fn: ToolFn, *, registry: InvocationRegistry | None = None) -> Callable[..., str]:
        """droid-sdk 0.5.0 stalls the whole run (RunTimeoutError) if an in-process tool yields to the
        event loop, even for `await asyncio.sleep(0.3)`; only tools that return without awaiting work.
        So each tool call runs to completion on a private loop in a worker thread, with its own
        LedgerClient for the same turn, under a copy of the calling context (so turn-scoped ContextVars
        a subclass sets, e.g. green's clerk_scope, are visible inside the tool).

        The SDK accepts sync or async handlers (droid_sdk.mcp.tool's `invoke` awaits the result only if
        it is awaitable) and serves them from a uvicorn task on the session's loop, so this sync wrapper
        freezes that loop while the tool runs: nothing on it (the stream and its turn timeout, the
        event pump, permission requests) makes progress until the tool returns. The only bound on that
        freeze is _tool_budget_sec(): the tool is cancelled inside its thread at the deadline (and the
        outer wait gives up _TOOL_GRACE_SEC later on a thread that won't yield), and the model gets an
        error string; nothing is raised through the SDK. The stream timeout can fire only afterwards.

        Narration: this wrapper, on the loop thread, emits the call's agent.tool_call before the tool
        starts and its single agent.tool_result after it ends (ok, ledger refusal, exception, timeout),
        with the tool's own narration replayed in between. The id is the Droid tool_use_id when the
        registry links this execution to one (see agentkit.invocation), else a UUID4; ledger writes
        inside use it as X-Tool-Use-Id."""

        name = getattr(fn, "_rl_tool", (getattr(fn, "__name__", "tool"), ""))[0]

        @functools.wraps(fn)
        def sync_tool(*args: Any, **kwargs: Any) -> str:
            loop = asyncio.get_running_loop()
            turn, emitter = ctx.turn(), ctx.emitter()
            reg = registry if registry is not None else current_registry()
            inv = self._begin_invocation(name, kwargs, reg)
            budget = self._tool_budget_sec(name)
            deadline = time.monotonic() + budget
            if emitter:
                emitter.tool_call(name, _args_payload(args, kwargs), inv.tool_use_id)
            proxy = _WorkerEmitter(emitter, loop) if emitter else None
            worker_ctx = contextvars.copy_context()

            async def run() -> str:
                timer = asyncio.timeout(max(0.0, deadline - time.monotonic()))
                try:
                    async with timer:
                        async with LedgerClient(self.s, episode_id=turn.episode_id, day=turn.day) as ledger:
                            tokens = ctx.bind(ledger, proxy, turn)  # type: ignore[arg-type]
                            try:
                                with bind_invocation(inv):
                                    return await fn(*args, **kwargs)
                            finally:
                                ctx.unbind(tokens)
                except TimeoutError:
                    if timer.expired():
                        raise _ToolDeadline from None
                    raise

            # The coroutine is created in the worker, so a call cancelled while queued leaves no
            # never-awaited coroutine behind.
            future = _TOOL_POOL.submit(worker_ctx.run, lambda: asyncio.run(run()))
            done, _ = concurrent.futures.wait([future], timeout=max(0.0, deadline - time.monotonic()) + _TOOL_GRACE_SEC)
            ok, out, summary = False, "", ""
            if not done or isinstance(future.exception(), _ToolDeadline):
                started = not future.cancel()  # cancel() only succeeds if it never left the pool queue
                out = summary = json.dumps(
                    {
                        "error": True,
                        "timeout": True,
                        "tool": name,
                        "detail": (
                            f"tool timed out after {round(budget, 1):g}s; "
                            + ("its outcome is unknown, re-read the books before retrying" if started else "it never ran")
                        ),
                    }
                )
                log.error("tool_timeout", agent=self.name, tool=name, day=turn.day, timeout_sec=budget, started=started, tool_use_id=inv.tool_use_id)
                inv.close()  # a result the tool records later is discarded: one tool_result per call
            elif future.exception() is not None:
                e = future.exception()
                log.error("tool_failed", agent=self.name, tool=name, day=turn.day, error=f"{type(e).__name__}: {e}", tool_use_id=inv.tool_use_id)
                out = summary = error_summary(name, e)  # type: ignore[arg-type]
                inv.close()
            else:
                out = future.result()
                recorded = inv.close()
                ok, summary = recorded if recorded is not None else (True, out[:300] if isinstance(out, str) else str(out)[:300])
            if proxy:
                proxy.drain()
            if emitter:
                emitter.tool_result(inv.tool_use_id, ok, summary)
            if reg is not None:
                reg.finished(inv.tool_use_id, ok)
            return out

        return sync_tool

    async def _droid_turn(self, req: TurnRequest, emitter: EventEmitter) -> tuple[str, Usage | None]:
        from droid_sdk import (
            InteractionHandlers,
            Session,
            SessionConfig,
            TextDelta,
            ThinkingDelta,
            ToolCall,
            ToolCallDelta,
            ToolResult,
        )

        registry = self._new_registry(emitter)
        server = self._mcp_server(registry)
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

        # Bound before the Session opens: the SDK's reader and MCP server tasks are created inside it and
        # copy this context, so the permission handler and the tool handler see this turn's registry.
        with bind_registry(registry):
            try:
                async with Session(
                    model=self.s.droid_model,
                    reasoning_effort=ReasoningEffort(self.s.droid_reasoning) if self.s.droid_reasoning else None,
                    config=config,
                    interactions=InteractionHandlers(on_permission=functools.partial(self._permission_entry, registry)),
                    api_key=self.s.factory_api_key,
                ) as session:
                    if self._tool_ids is None:
                        await self._learn_tool_ids(session)
                    async with session.stream(prompt, include_partial_messages=True, timeout=self.s.turn_timeout_sec - 10) as stream:
                        async for ev in stream:
                            if isinstance(ev, (ThinkingDelta, TextDelta)):
                                emitter.thinking(ev.text)
                            elif isinstance(ev, ToolCallDelta):  # "completed tool-call input": the earliest sighting
                                tu = ev.tool_use
                                registry.observe(tu.id, tu.name, tu.input, SOURCE_STREAM)
                            elif isinstance(ev, ToolCall):
                                # narration comes from _offload (or the registry, for calls that never
                                # run); here we only learn the SDK's id for the call
                                if registry.observe(ev.tool_use_id, ev.name, ev.input, SOURCE_STREAM) is None:
                                    log.info("tool_call_not_ours", agent=self.name, tool=ev.name, tool_use_id=ev.tool_use_id)
                            elif isinstance(ev, ToolResult):
                                registry.resolved(ev.tool_use_id, ev.is_error, ev.content)
                    result = stream.result
            finally:
                registry.close()  # every registered call that never ran gets its event pair
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
