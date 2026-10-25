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
callers); an `_meta` value equal to a registered id; else a registered, not yet executed tool use of
the same tool with identical canonical arguments (validated through the same pydantic model the SDK
builds, so defaults and coercions match), preferring the oldest whose permission request was
approved. This argument correlation is the narrowest link possible without an SDK/CLI change that
passes the id to the handler. Permission requests arrive *before* the CLI executes the call (it
waits for our answer), so under `Autonomy.OFF` only approved entries are claimable
(`require_permission`) and a cancelled or still-undecided call can never lend its id to an
execution. Without a permission request (red at HIGH) the stream ToolCall is the only registration,
and it races the MCP HTTP call; if it loses, the execution gets a UUID4 (logged
`tool_use_id_unverified`) and the late ToolCall gets a link pair pointing at it (logged
`tool_use_id_late`) instead of being left claimable. Identical approved calls are interchangeable
(same action, same verdict), so oldest-first between them is safe. There is no "last seen id"
anywhere, and every registered id gets exactly one event pair (see InvocationRegistry).

Streamed arguments (CLI 0.249.0 with gpt-5.x): the CLI reports a tool call as soon as it is detected
("tool-call-start", with the arguments known so far, often `{}`) and again with the full arguments
("tool-call-progress"), both as a stream ToolCallDelta under the same id, before the permission request.
So a stream sighting is not the call's final word: until the CLI asks permission for an id, the latest
sighting with valid arguments re-keys its pending entry, and the permission request's arguments, once
seen, are the ones it is approved and claimed under (see InvocationRegistry._resight).

Ledger write keys inside one invocation: the first write uses the tool_use_id exactly; the n-th
(n >= 2) uses `f"{tool_use_id}:{n}"`. `put_state` / `post_input` count as writes. A caller-supplied
`tool_use_id=` is used verbatim and never handed out again; passing one this invocation already
used (its own id after its first write, or any `<id>:<n>` it issued) raises IdempotencyKeyReused
before anything is sent. Green's preparation therefore
keys `POST /preparations` on the bare tool_use_id, which equals the X-Tool-Use-Id of the call's first
(and for every green gated tool, only) ledger write (the green → blue mirror was removed in D1 / #80).
"""

from __future__ import annotations

import contextvars
import inspect
import json
import threading
from collections import deque
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
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

# Identity policies (design D7). best_effort: today's linking, UUID4 when the SDK hasn't revealed the id.
# strict (green, blue live): an execution runs only under an SDK-reported id, unambiguously linked.
IDENTITY_STRICT = "strict"
IDENTITY_BEST_EFFORT = "best_effort"
IDENTITY_POLICIES = (IDENTITY_STRICT, IDENTITY_BEST_EFFORT)
# Why a strict claim refused an execution (the `identity` field of its not_run result).
REFUSE_UNVERIFIED = "unverified"  # no registered tool use matches it
REFUSE_AMBIGUOUS = "ambiguous"  # more than one equally preferred identical tool use (D8: refuse them all)
REFUSE_CONFLICTING = "conflicting"  # an _meta hint names one of ours that the arguments don't match
REFUSE_EXPLICIT = "explicit"  # a caller-supplied _tool_use_id


def write_key(tool_use_id: str, n: int) -> str:
    """Idempotency key for the n-th (1-based) ledger write of an invocation."""
    return tool_use_id if n == 1 else f"{tool_use_id}:{n}"


class IdempotencyKeyReused(ValueError):
    """An explicit tool_use_id= repeats a key this invocation already sent."""


class UnverifiedInvocation(RuntimeError):
    """Strict identity, live: a ledger write (or preparation) without a verified SDK tool_use_id. Raised
    before anything is sent."""


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
        """A write is about to use a caller-supplied key; never issue it again. Raises
        IdempotencyKeyReused if this invocation already used it (a programming error: two different
        writes under one key would make battlefield replay the first one's verdict for the second)."""
        with self._lock:
            if key in self._keys:
                raise IdempotencyKeyReused(f"X-Tool-Use-Id {key!r} was already used by this {self.tool} call; pass a new key or none")
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


_strict: contextvars.ContextVar[bool] = contextvars.ContextVar("rl_strict_identity", default=False)


def strict_identity() -> bool:
    """True inside a live turn of a strict-identity agent (bound by DroidAgent; copied into tool workers)."""
    return _strict.get()


@contextmanager
def bind_strict(strict: bool) -> Iterator[bool]:
    token = _strict.set(strict)
    try:
        yield strict
    finally:
        _strict.reset(token)


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
_PENDING, _RUNNING, _DONE, _CLOSED = "pending", "running", "done", "closed"
# permission state of an entry
_PERM_NONE, _PERM_ASKED, _PERM_APPROVED, _PERM_DENIED = "none", "asked", "approved", "denied"
_TOOL_MISMATCH = "\x00tool-mismatch"  # a conflict marker no canonical JSON can equal


@dataclass
class _Entry:
    use: ToolUse
    canon: str | None
    state: str
    perm: str = _PERM_NONE
    # the SDK reported other valid arguments for this id after its permission request: never claimable
    conflicts: set[str] = field(default_factory=set)


@dataclass
class _UnlinkedRun:
    """An execution that ran under a local id because no registered tool use matched it."""

    local_id: str
    ok: bool | None = None  # set when it finishes
    linked_to: str | None = None


class InvocationRegistry:
    """Turn-scoped link between SDK-reported tool uses and executions of our MCP tools.

    Only ever touched on the thread that created it, the turn's event-loop thread: the permission
    handler and the stream run as tasks there, and the SDK calls our (sync) tool handler there too. No
    locking; a call from any other thread (a tool worker) raises RuntimeError instead of racing.

    Guarantee: every registered tool_use_id gets exactly one agent.tool_call/agent.tool_result pair.
    Executed and linked: _offload narrates it. Never ran (cancelled, rejected by the SDK, turn ended):
    `ok=false`, `not_run`/`cancelled`. Ran under a local id before the SDK revealed its id (red's
    stream race): a link pair `{"ran_as": <local id>}` carrying the execution's ok, so the id is
    accounted for and points at the events/ledger writes that actually happened.

    `require_permission` (the agent runs at Autonomy.OFF, where the CLI asks before every MCP call):
    only entries whose permission request was approved can be claimed by an execution. Otherwise an
    approved entry is still preferred over one never asked about, and an entry that was asked but not
    (yet) approved, or denied, is never claimed.

    An entry is claimed by argument correlation only under valid canonical arguments: one whose
    arguments do not validate (a streamed `{}` for a tool with a required argument) is registered
    tentatively, outside the pending index, until a later sighting completes them (`_resight`)."""

    def __init__(self, server_name: str, tools: Iterable[tuple[str, Callable[..., Any]]], emitter: Any | None = None, *, require_permission: bool = False):
        tools = list(tools)
        self.server_name = server_name
        self._owner = threading.get_ident()
        self._redact = dict(tools)  # name -> fn, for ledger_tool(redact=)
        self._canon = {name: _canonicalizer(fn) for name, fn in tools}
        self._full = {f"{server_name}___{name}": name for name in self._canon}  # observed MCP tool id format
        self.emitter = emitter
        self.require_permission = require_permission
        self._entries: dict[str, _Entry] = {}
        self._pending: dict[tuple[str, str | None], deque[str]] = {}
        self._unlinked: dict[tuple[str, str | None], deque[_UnlinkedRun]] = {}
        self._runs: dict[str, _UnlinkedRun] = {}

    def _own(self) -> None:
        if threading.get_ident() != self._owner:
            raise RuntimeError("InvocationRegistry used off the thread that owns it (its turn loop); hop with call_soon_threadsafe")

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
        self._own()
        tool = self.tool_name(raw_name)
        if tool is None or not tool_use_id:
            return None
        plain = thaw(args or {})
        canon = self.canonical(tool, plain)
        entry = self._entries.get(tool_use_id)
        if entry is not None:  # seen already (streamed arguments, permission request, complete ToolCall)
            return self._resight(entry, tool, plain, canon, source)
        use = ToolUse(tool_use_id=tool_use_id, tool=tool, args=plain, source=source)
        entry = _Entry(use, canon, _PENDING)
        self._entries[tool_use_id] = entry
        # A permission request means the call has not run yet; only a stream sighting can be late.
        if source != SOURCE_PERMISSION and self._link_unlinked(entry):
            log.warning("tool_use_id_late", tool=tool, tool_use_id=tool_use_id, source=source)
            return use
        self._file(entry)
        return use

    def _resight(self, entry: _Entry, tool: str, plain: dict[str, Any], canon: str | None, source: str) -> ToolUse:
        """A later sighting of a registered id. Rule (streamed arguments, see the module docstring):
        - pending and never asked about: the arguments may still be streaming, so a permission request,
          or a stream sighting with valid arguments, replaces them and re-files the entry (a sighting
          that fails validation never replaces valid ones);
        - pending and asked about: the permission request's arguments are bound (they are what the
          handler decided on); other valid arguments for the id mark it conflicting, never claimable;
        - claimed, executed or closed: never re-keyed (logged)."""
        if tool != entry.use.tool:
            log.error("tool_use_id_tool_mismatch", tool=entry.use.tool, seen_as=tool, tool_use_id=entry.use.tool_use_id, source=source)
            if entry.state == _PENDING:
                entry.conflicts.add(_TOOL_MISMATCH)
            return entry.use
        if canon is not None and canon == entry.canon:
            return entry.use  # the same action again
        if entry.state != _PENDING:
            if canon is not None:
                log.warning("tool_use_args_changed_after_claim", tool=tool, tool_use_id=entry.use.tool_use_id, state=entry.state, source=source)
            return entry.use
        if entry.perm == _PERM_NONE:
            if source == SOURCE_PERMISSION or canon is not None or entry.canon is None:
                self._unfile(entry)
                entry.use = ToolUse(tool_use_id=entry.use.tool_use_id, tool=tool, args=plain, source=source)
                entry.canon = canon
                if source != SOURCE_PERMISSION and self._link_unlinked(entry):
                    log.warning("tool_use_id_late", tool=tool, tool_use_id=entry.use.tool_use_id, source=source)
                else:
                    self._file(entry)
            return entry.use
        if canon is not None:
            entry.conflicts.add(canon)
            log.warning(
                "tool_use_args_conflict",
                tool=tool,
                tool_use_id=entry.use.tool_use_id,
                perm=entry.perm,
                source=source,
                detail="arguments differ from the permission request's; the call is refused",
            )
        return entry.use

    def observe_permission(self, request: Any) -> list[ToolUse]:
        """Register every MCP action of ours in a droid_sdk PermissionRequest (duck-typed so tests and
        DRY_RUN never need the SDK) and mark it asked. Idempotent."""
        self._own()
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
            if use is None:
                continue
            entry = self._entries[use.tool_use_id]
            if entry.state in (_RUNNING, _DONE) and entry.perm == _PERM_NONE:
                # an execution already took this id without a permission request, but the CLI is only
                # now asking about it: that execution was a different (identical) call
                log.error("tool_use_id_misbound", tool=use.tool, tool_use_id=use.tool_use_id)
            if entry.perm == _PERM_NONE:
                entry.perm = _PERM_ASKED
            out.append(use)
        return out

    def permission_resolved(self, tool_use_id: str, approved: bool) -> None:
        self._own()
        entry = self._entries.get(tool_use_id)
        if entry is not None and entry.perm in (_PERM_NONE, _PERM_ASKED):
            entry.perm = _PERM_APPROVED if approved else _PERM_DENIED

    # ---------- execution ----------
    def _claimable(self, entry: _Entry, approved_only: bool) -> bool:
        if entry.state != _PENDING or entry.canon is None or entry.conflicts:
            return False
        if entry.perm == _PERM_APPROVED:
            return True
        return not approved_only and entry.perm == _PERM_NONE

    def claim(self, tool: str, kwargs: Mapping[str, Any], hints: Iterable[str] = ()) -> ToolUse | None:
        """Link an execution of `tool` to a registered tool use, or None if the SDK hasn't told us.
        Preference: an `_meta` hint naming a claimable entry; the oldest approved identical entry;
        unless require_permission, the oldest identical entry never asked about."""
        self._own()
        for hint in hints:
            entry = self._entries.get(hint)
            if entry is not None and entry.use.tool == tool and self._claimable(entry, self.require_permission):
                return self._take(entry, ToolUse(entry.use.tool_use_id, tool, entry.use.args, SOURCE_MCP_META))
        canon = self.canonical(tool, kwargs)
        q = self._pending.get((tool, canon)) if canon is not None else None
        if not q:
            return None
        for approved_only in (True, False) if not self.require_permission else (True,):
            for tid in q:
                entry = self._entries[tid]
                if self._claimable(entry, approved_only):
                    return self._take(entry, entry.use)
        return None

    def claim_checked(self, tool: str, kwargs: Mapping[str, Any], hints: Iterable[str] = ()) -> tuple[ToolUse | None, str | None]:
        """Strict claim: the linked tool use, or (None, reason) with reason in REFUSE_*. Never guesses
        between candidates: a hint that names one of our ids must agree with the arguments, and more than
        one equally preferred identical entry is ambiguous (all of them stay unclaimed, so every identical
        execution is refused and each id is closed not_run at turn end; D8)."""
        self._own()
        canon = self.canonical(tool, kwargs)
        named = {h for h in hints if (e := self._entries.get(h)) is not None and e.use.tool == tool}
        if named:
            if len(named) > 1:
                return None, REFUSE_CONFLICTING
            entry = self._entries[next(iter(named))]
            if canon is None or entry.canon != canon or not self._claimable(entry, self.require_permission):
                return None, REFUSE_CONFLICTING
            return self._take(entry, ToolUse(entry.use.tool_use_id, tool, entry.use.args, SOURCE_MCP_META)), None
        if canon is None:
            return None, REFUSE_UNVERIFIED
        q = list(self._pending.get((tool, canon)) or ())
        tiers = [lambda e: e.perm == _PERM_APPROVED]
        if not self.require_permission:
            tiers.append(lambda e: e.perm == _PERM_NONE)
        for tier in tiers:
            cands = [self._entries[t] for t in q if self._entries[t].state == _PENDING and tier(self._entries[t])]
            if any(c.conflicts for c in cands):
                return None, REFUSE_CONFLICTING
            if len(cands) > 1:
                return None, REFUSE_AMBIGUOUS
            if cands:
                return self._take(cands[0], cands[0].use), None
        if any(e.state == _PENDING and e.use.tool == tool and canon in e.conflicts for e in self._entries.values()):
            return None, REFUSE_CONFLICTING
        return None, REFUSE_UNVERIFIED

    def _take(self, entry: _Entry, use: ToolUse) -> ToolUse:
        self._drop_pending(entry, _RUNNING)
        return use

    def note_unlinked(self, tool: str, kwargs: Mapping[str, Any], local_id: str) -> None:
        """An execution runs under a local id; a ToolCall seen later for it gets linked to it."""
        self._own()
        run = _UnlinkedRun(local_id)
        self._runs[local_id] = run
        self._unlinked.setdefault((tool, self.canonical(tool, kwargs)), deque()).append(run)

    def finished(self, tool_use_id: str, ok: bool | None = None) -> None:
        self._own()
        entry = self._entries.get(tool_use_id)
        if entry is not None and entry.state == _RUNNING:
            entry.state = _DONE
        run = self._runs.get(tool_use_id)
        if run is not None:
            run.ok = ok

    # ---------- calls that never ran ----------
    def cancelled(self, tool_use_id: str, reason: str) -> bool:
        """The permission handler refused the call: emit its tool_call/tool_result pair now, once.
        Returns False if the id already has its pair (closed earlier, or an execution took it)."""
        self._own()
        entry = self._entries.get(tool_use_id)
        if entry is None:
            return False
        if entry.perm in (_PERM_NONE, _PERM_ASKED):
            entry.perm = _PERM_DENIED
        if entry.state == _PENDING:
            self._close_unrun(entry, {"cancelled": True, "tool": entry.use.tool, "reason": reason})
            return True
        if entry.state in (_RUNNING, _DONE):
            # Its pair comes from the execution that took the id. Not silent: this means that execution
            # was another identical call (only possible without require_permission).
            log.error("permission_cancel_after_execution", tool=entry.use.tool, tool_use_id=tool_use_id, reason=reason)
        return False

    def resolved(self, tool_use_id: str, is_error: bool, content: Any) -> None:
        """Stream ToolResult. For a call our handler never linked: if an identical call ran under a
        local id, this is it (link pair); otherwise it never reached our handler (cancelled, arguments
        rejected by the SDK, interrupted): not_run pair."""
        self._own()
        entry = self._entries.get(tool_use_id)
        if entry is None:
            return
        if entry.state == _RUNNING:
            entry.state = _DONE
        elif entry.state == _PENDING:
            if is_error or not self._link_unlinked(entry):
                self._close_unrun(entry, {"error": True, "not_run": True, "tool": entry.use.tool, "detail": str(content)[:300]})

    def close(self, reason: str = "turn ended before the tool ran") -> None:
        """Turn end: every registered call that has no pair yet gets one."""
        self._own()
        for entry in list(self._entries.values()):
            if entry.state != _PENDING:
                continue
            if not self._link_unlinked(entry):
                self._close_unrun(entry, {"error": True, "not_run": True, "tool": entry.use.tool, "detail": reason})

    # ---------- internals ----------
    def _link_unlinked(self, entry: _Entry) -> bool:
        """Pair `entry` with the oldest unlinked execution of the exact same tool + valid arguments."""
        if entry.canon is None or entry.conflicts:
            return False
        runs = self._unlinked.get((entry.use.tool, entry.canon))
        if not runs:
            return False
        run = runs.popleft()
        run.linked_to = entry.use.tool_use_id
        self._drop_pending(entry, _DONE)
        if self.emitter is not None:
            body = {
                "ran_as": run.local_id,
                "tool": entry.use.tool,
                "detail": "executed before the SDK reported this tool_use_id; its events and ledger writes carry ran_as",
            }
            self.emitter.tool_call(entry.use.tool, self._shown(entry.use), entry.use.tool_use_id)
            self.emitter.tool_result(entry.use.tool_use_id, bool(run.ok), json.dumps(body))
        return True

    def _shown(self, use: ToolUse) -> dict[str, Any]:
        from .tools import redacted_args  # tools imports this module

        return redacted_args(self._redact.get(use.tool), use.args)

    def _file(self, entry: _Entry) -> None:
        """Index a pending entry for argument correlation; a tentative one (invalid arguments) stays out."""
        if entry.canon is not None:
            self._pending.setdefault((entry.use.tool, entry.canon), deque()).append(entry.use.tool_use_id)

    def _unfile(self, entry: _Entry) -> None:
        q = self._pending.get((entry.use.tool, entry.canon))
        if q is not None and entry.use.tool_use_id in q:
            q.remove(entry.use.tool_use_id)

    def _drop_pending(self, entry: _Entry, state: str) -> None:
        entry.state = state
        self._unfile(entry)

    def _close_unrun(self, entry: _Entry, body: dict[str, Any]) -> None:
        self._drop_pending(entry, _CLOSED)
        if self.emitter is not None:
            self.emitter.tool_call(entry.use.tool, self._shown(entry.use), entry.use.tool_use_id)
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
