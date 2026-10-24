"""Invocation identity: one id per agent tool call, the same everywhere that call is visible.

AGENTS.md §3.7: the idempotency key is the Droid `tool_use_id` when a call comes from a Droid tool,
else a UUID4, and a key is never reused across different actions. §3.5: every tool call emits one
`agent.tool_call` and one `agent.tool_result`. This module carries that id from where the SDK reveals
it to everything that runs inside the call:

    permission request ─┐                 ┌─ agent.tool_call / agent.tool_result  (tool_use_id)
    stream ToolCall ────┼─ InvocationRegistry ─ Invocation (ContextVar) ─┤
    MCP call _meta ─────┘   (turn-scoped)                                  └─ LedgerClient writes
                                                                              (X-Tool-Use-Id)

Where droid-sdk 0.5.0 exposes the real id (read from the installed package, not guessed):
  - permission callback: `McpToolAction.tool_use.id` (droid_sdk/_high_level/interactions.py:125-134,
    ToolUseBlock at _high_level/messages.py:61-65), filled from the CLI's `droid.request_permission`
    params (`toolUses[].toolUse.id`, _high_level/interaction_adapter.py:70-76,164-170).
  - stream: `ToolCall.tool_use_id` / `ToolResult.tool_use_id` (_high_level/messages.py:159-185),
    from the CLI's create_message / tool_result notifications (_high_level/streaming.py:461-521).
  - NOT in the tool handler: the in-process MCP server calls `handler(arguments)` with the validated
    arguments only (droid_sdk/mcp.py:132-136 and 285-295). The only request-scoped data reachable
    there is the MCP SDK's `request_ctx` (JSON-RPC request id, `_meta`, HTTP request), and the Droid
    CLI (0.249.0 linux-x64 binary, strings) sends `callTool({name, arguments, _meta:{assemblySessionId,
    caller}})`: no tool_use_id. We still read `_meta` values as *hints*, accepted only if one equals
    an id the SDK already reported for the same tool, so a CLI that starts sending it is picked up
    with no code change and nothing else can be mistaken for it.
  - when the CLI asks permission (same binary, shouldConfirmExecution): an MCP call needs
    confirmation iff its impact level (low=1/medium=2/high=3) exceeds the session autonomy
    (off=0 ... high=3). So at Autonomy.OFF (green) every call of ours is preceded by a permission
    request; at HIGH (red) none is, and the stream ToolCall is the only source.

So an execution is linked to its id by, in order: an explicit `_tool_use_id` (tests, DRY_RUN
callers); an `_meta` value equal to a registered id; else the oldest registered, not yet executed
tool use of the same tool with identical canonical arguments (validated through the same pydantic
model the SDK builds, so defaults and coercions match). This argument correlation is the narrowest
link possible without an SDK/CLI change that passes the id to the handler. Permission requests arrive *before* the CLI
executes the call (it waits for our answer), so under `Autonomy.OFF` the registration always
precedes the execution and the link is deterministic. Without a permission request (red at HIGH) the
stream ToolCall is the only registration, and it races the MCP HTTP call; if it loses, the execution
gets a UUID4 (logged `tool_use_id_unverified`) and the late ToolCall is matched to it (logged
`tool_use_id_late`) instead of being left claimable. Two pending calls with identical tool and
arguments are interchangeable (same action, both approved), so FIFO between them is safe. There is
no "last seen id" anywhere.

Ledger write keys inside one invocation: the first write uses the tool_use_id exactly; the n-th
(n >= 2) uses `f"{tool_use_id}:{n}"`. `put_state` / `post_input` count as writes. A caller-supplied
`tool_use_id=` is used verbatim, reserved, and never handed out again. Green's mirror therefore
keys `POST blue/gate` on the bare tool_use_id, which equals the X-Tool-Use-Id of the call's first
(and for every green gated tool, only) ledger write.
"""

from __future__ import annotations

import contextvars
import inspect
import json
import threading
from collections import Counter, deque
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, get_type_hints

import structlog
from pydantic import ConfigDict, ValidationError, create_model

log = structlog.get_logger(__name__)

# Sources of an invocation's id. The first three are SDK-provided ids.
SOURCE_PERMISSION = "permission"
SOURCE_STREAM = "stream"
SOURCE_MCP_META = "mcp_meta"
SOURCE_EXPLICIT = "explicit"  # caller passed _tool_use_id
SOURCE_LOCAL = "local"  # UUID4: not a Droid call, or the SDK did not reveal the id in time
VERIFIED_SOURCES = frozenset({SOURCE_PERMISSION, SOURCE_STREAM, SOURCE_MCP_META})


def write_key(tool_use_id: str, n: int) -> str:
    """Idempotency key for the n-th (1-based) ledger write of an invocation."""
    return tool_use_id if n == 1 else f"{tool_use_id}:{n}"


class Invocation:
    """One tool call. Thread-safe: the worker thread running the tool issues keys and records the
    outcome while the loop thread that started it may close it on timeout."""

    def __init__(self, tool_use_id: str, tool: str, *, source: str = SOURCE_LOCAL):
        self.tool_use_id = tool_use_id
        self.tool = tool
        self.source = source
        self._lock = threading.Lock()
        self._n = 0
        self._keys: list[str] = []
        self._outcome: tuple[bool, str] | None = None
        self._closed = False
        self._owned = False

    @property
    def verified(self) -> bool:
        """True when the id is the Droid SDK's tool_use_id."""
        return self.source in VERIFIED_SOURCES

    @property
    def keys(self) -> list[str]:
        """Write keys issued or reserved so far, in order."""
        with self._lock:
            return list(self._keys)

    def next_key(self) -> str:
        with self._lock:
            while True:
                self._n += 1
                key = write_key(self.tool_use_id, self._n)
                if key not in self._keys:
                    self._keys.append(key)
                    return key

    def reserve(self, key: str) -> None:
        """A write used a caller-supplied key; never issue it again."""
        with self._lock:
            if key not in self._keys:
                self._keys.append(key)

    def take(self, tool: str) -> bool:
        """The ledger_tool wrapper for `tool` claims this invocation as its own (once)."""
        with self._lock:
            if self._owned or tool != self.tool:
                return False
            self._owned = True
            return True

    def record(self, ok: bool, summary: str) -> bool:
        """Record the tool's own outcome. Ignored once closed (e.g. the tool outlived its deadline)."""
        with self._lock:
            if self._closed or self._outcome is not None:
                return False
            self._outcome = (ok, summary)
            return True

    def close(self) -> tuple[bool, str] | None:
        """Freeze the invocation and return the outcome the tool recorded, if any."""
        with self._lock:
            self._closed = True
            return self._outcome


_current: contextvars.ContextVar[Invocation | None] = contextvars.ContextVar("rl_invocation", default=None)


def current_invocation() -> Invocation | None:
    return _current.get()


@contextmanager
def bind_invocation(inv: Invocation) -> Iterator[Invocation]:
    token = _current.set(inv)
    try:
        yield inv
    finally:
        _current.reset(token)


def thaw(value: Any) -> Any:
    """SDK inputs are frozen mappings/tuples; make them plain JSON-able Python."""
    if isinstance(value, Mapping):
        return {str(k): thaw(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [thaw(v) for v in value]
    return value


def _canonicalizer(fn: Callable[..., Any]) -> Callable[[Mapping[str, Any]], str | None]:
    """Same argument model droid_sdk.mcp.tool builds (mcp.py:90-118), so a permission request's raw
    input and the handler's validated kwargs canonicalize identically (defaults filled, coerced)."""
    try:
        sig = inspect.signature(fn)
        hints = get_type_hints(fn)
        fields: dict[str, Any] = {}
        for pname, p in sig.parameters.items():
            if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD, p.POSITIONAL_ONLY):
                raise TypeError("unsupported parameter kind")
            fields[pname] = (hints.get(pname, Any), ... if p.default is p.empty else p.default)
        model = create_model(f"{getattr(fn, '__name__', 'tool').title()}Canon", __config__=ConfigDict(extra="forbid"), **fields)
    except Exception:
        model = None

    def canon(args: Mapping[str, Any]) -> str | None:
        plain = thaw(args)
        if model is not None:
            try:
                plain = model.model_validate(plain).model_dump(mode="json")
            except ValidationError:
                return None  # the SDK would reject these arguments too; never matchable
        try:
            return json.dumps(plain, sort_keys=True, separators=(",", ":"), default=str)
        except (TypeError, ValueError):
            return None

    return canon


@dataclass(frozen=True)
class ToolUse:
    """A tool use of ours that the Droid SDK told us about."""

    tool_use_id: str
    tool: str  # our short tool name, e.g. "pay_invoice"
    args: dict[str, Any]
    source: str


# entry states
_PENDING, _RUNNING, _DONE, _CLOSED, _UNLINKED = "pending", "running", "done", "closed", "unlinked"


@dataclass
class _Entry:
    use: ToolUse
    canon: str | None
    state: str


class InvocationRegistry:
    """Turn-scoped link between SDK-reported tool uses and executions of our MCP tools.

    Only ever touched on the turn's event-loop thread: the permission handler and the stream run as
    tasks there, and the SDK calls our (sync) tool handler there too. No locking needed."""

    def __init__(self, server_name: str, tools: Iterable[tuple[str, Callable[..., Any]]], emitter: Any | None = None):
        self.server_name = server_name
        self._canon = {name: _canonicalizer(fn) for name, fn in tools}
        self._full = {f"{server_name}___{name}": name for name in self._canon}  # observed MCP tool id format
        self.emitter = emitter
        self._entries: dict[str, _Entry] = {}
        self._pending: dict[tuple[str, str | None], deque[str]] = {}
        self._unlinked: Counter[tuple[str, str | None]] = Counter()
        self._unlinked_by_tool: Counter[str] = Counter()

    # ---------- naming ----------
    def tool_name(self, raw: str | None) -> str | None:
        """Our short tool name for an exact `<tool>` or `<server>___<tool>` id; None if not ours."""
        if not raw:
            return None
        if raw in self._canon:
            return raw
        return self._full.get(raw)

    def canonical(self, tool: str, args: Mapping[str, Any]) -> str | None:
        fn = self._canon.get(tool)
        return fn(args) if fn else None

    # ---------- registration ----------
    def observe(self, tool_use_id: str | None, raw_name: str | None, args: Mapping[str, Any] | None, source: str) -> ToolUse | None:
        tool = self.tool_name(raw_name)
        if tool is None or not tool_use_id:
            return None
        if tool_use_id in self._entries:  # seen already (permission request, then the stream)
            return self._entries[tool_use_id].use
        plain = thaw(args or {})
        use = ToolUse(tool_use_id=tool_use_id, tool=tool, args=plain, source=source)
        canon = self.canonical(tool, plain)
        key = (tool, canon)
        if self._unlinked[key] > 0:  # it already ran under a local id before the SDK told us its id
            self._unlinked[key] -= 1
            self._consume_unlinked(tool)
            self._entries[tool_use_id] = _Entry(use, canon, _UNLINKED)
            log.warning("tool_use_id_late", tool=tool, tool_use_id=tool_use_id, source=source)
            return use
        self._entries[tool_use_id] = _Entry(use, canon, _PENDING)
        self._pending.setdefault(key, deque()).append(tool_use_id)
        return use

    def observe_permission(self, request: Any) -> list[ToolUse]:
        """Register every MCP action of ours in a droid_sdk PermissionRequest (duck-typed so tests and
        DRY_RUN never need the SDK). Idempotent."""
        out: list[ToolUse] = []
        for action in getattr(request, "actions", None) or ():
            if getattr(action, "confirmation_type", None) != "mcp_tool":
                continue
            server = getattr(action, "server_name", None)
            if server is not None and server != self.server_name:
                continue
            tool_use = getattr(action, "tool_use", None)
            name = self.tool_name(getattr(action, "actual_tool_name", None)) or self.tool_name(getattr(action, "tool_name", None))
            use = self.observe(getattr(tool_use, "id", None), name, getattr(tool_use, "input", None), SOURCE_PERMISSION)
            if use is not None:
                out.append(use)
        return out

    # ---------- execution ----------
    def claim(self, tool: str, kwargs: Mapping[str, Any], hints: Iterable[str] = ()) -> ToolUse | None:
        """Link an execution of `tool` to a registered tool use, or None if the SDK hasn't told us."""
        for hint in hints:
            entry = self._entries.get(hint)
            if entry is not None and entry.state == _PENDING and entry.use.tool == tool:
                entry.state = _RUNNING
                return ToolUse(entry.use.tool_use_id, tool, entry.use.args, SOURCE_MCP_META)
        q = self._pending.get((tool, self.canonical(tool, kwargs)))
        while q:
            entry = self._entries[q.popleft()]
            if entry.state == _PENDING:
                entry.state = _RUNNING
                return entry.use
        return None

    def note_unlinked(self, tool: str, kwargs: Mapping[str, Any]) -> None:
        """An execution ran under a local id; a ToolCall seen later for it must not stay claimable."""
        self._unlinked[(tool, self.canonical(tool, kwargs))] += 1
        self._unlinked_by_tool[tool] += 1

    def finished(self, tool_use_id: str) -> None:
        entry = self._entries.get(tool_use_id)
        if entry is not None and entry.state == _RUNNING:
            entry.state = _DONE

    # ---------- calls that never ran ----------
    def cancelled(self, tool_use_id: str, reason: str) -> bool:
        """The permission handler refused the call: emit its tool_call/tool_result pair now, once."""
        entry = self._entries.get(tool_use_id)
        if entry is None or entry.state != _PENDING:
            return False
        self._close_unrun(entry, {"cancelled": True, "tool": entry.use.tool, "reason": reason})
        return True

    def resolved(self, tool_use_id: str, is_error: bool, content: Any) -> None:
        """Stream ToolResult for a call our handler never linked. A non-error result while some
        execution of that tool ran under a local id means it was that one (already narrated). Anything
        else means it never reached our handler (cancelled, arguments rejected by the SDK,
        interrupted): close its pair."""
        entry = self._entries.get(tool_use_id)
        if entry is None:
            return
        if entry.state == _RUNNING:
            entry.state = _DONE
        elif entry.state == _PENDING:
            if not is_error and self._consume_unlinked(entry.use.tool):
                self._drop_pending(entry, _UNLINKED)
                log.warning("tool_use_id_unlinked", tool=entry.use.tool, tool_use_id=tool_use_id)
            else:
                self._close_unrun(entry, {"error": True, "not_run": True, "tool": entry.use.tool, "detail": str(content)[:300]})

    def close(self, reason: str = "turn ended before the tool ran") -> None:
        """Turn end: every registered call that never executed gets its pair."""
        for entry in list(self._entries.values()):
            if entry.state != _PENDING:
                continue
            tool = entry.use.tool
            if self._consume_unlinked(tool):  # may be the one that ran unlinked: don't claim it didn't run
                self._drop_pending(entry, _UNLINKED)
                log.warning("tool_use_id_unlinked", tool=tool, tool_use_id=entry.use.tool_use_id)
                continue
            self._close_unrun(entry, {"error": True, "not_run": True, "tool": tool, "detail": reason})

    def _consume_unlinked(self, tool: str) -> bool:
        if self._unlinked_by_tool[tool] <= 0:
            return False
        self._unlinked_by_tool[tool] -= 1
        return True

    def _drop_pending(self, entry: _Entry, state: str) -> None:
        entry.state = state
        q = self._pending.get((entry.use.tool, entry.canon))
        if q is not None and entry.use.tool_use_id in q:
            q.remove(entry.use.tool_use_id)

    def _close_unrun(self, entry: _Entry, body: dict[str, Any]) -> None:
        self._drop_pending(entry, _CLOSED)
        if self.emitter is not None:
            self.emitter.tool_call(entry.use.tool, entry.use.args, entry.use.tool_use_id)
            self.emitter.tool_result(entry.use.tool_use_id, False, json.dumps(body))


_registry: contextvars.ContextVar[InvocationRegistry | None] = contextvars.ContextVar("rl_invocations", default=None)


def current_registry() -> InvocationRegistry | None:
    return _registry.get()


@contextmanager
def bind_registry(reg: InvocationRegistry) -> Iterator[InvocationRegistry]:
    token = _registry.set(reg)
    try:
        yield reg
    finally:
        _registry.reset(token)
