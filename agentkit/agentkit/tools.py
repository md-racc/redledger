"""Declare agent tools without importing the Droid SDK at module import time.

    from agentkit.tools import ledger_tool, ctx

    @ledger_tool("list_pending_invoices", "List invoices awaiting processing.")
    async def list_pending_invoices() -> str:
        rows = await ctx.ledger().list_invoices(status="pending")
        return json.dumps(rows)

DroidAgent collects functions marked by `ledger_tool` and wraps them with `droid_sdk.mcp.tool`
when it builds the session. Under DRY_RUN the same functions are called directly by your
`dry_run_turn`. Tool functions must return `str` (JSON text is fine).

Tools reach the current turn's LedgerClient / EventEmitter through `ctx`, which is backed by
contextvars set by DroidAgent.run_turn.

Each call of a `ledger_tool` is one invocation (agentkit.invocation): its agent.tool_call and
agent.tool_result carry the invocation's tool_use_id, and every LedgerClient write it makes uses that
id as X-Tool-Use-Id (first write) or `<id>:<n>` (n-th write). Called directly (DRY_RUN) the id is the
`_tool_use_id=` keyword if given, else a UUID4, and the wrapper narrates. Run by the Droid SDK through
DroidAgent._offload, the id is the SDK's tool_use_id and _offload narrates, in order, on the turn's
loop; the wrapper only records the outcome. A ledger_tool called from inside another tool is part of
the outer invocation: no events of its own, writes continue the outer key sequence.
"""

from __future__ import annotations

import contextvars
import functools
import json
from collections.abc import Awaitable, Callable
from typing import Any

from .events import EventEmitter
from .invocation import SOURCE_EXPLICIT, SOURCE_LOCAL, Invocation, bind_invocation, current_invocation
from .ledger_client import GateBlocked, LedgerClient, LedgerError
from .models import TurnRequest

_ledger: contextvars.ContextVar[LedgerClient | None] = contextvars.ContextVar("rl_ledger", default=None)
_emitter: contextvars.ContextVar[EventEmitter | None] = contextvars.ContextVar("rl_emitter", default=None)
_turn: contextvars.ContextVar[TurnRequest | None] = contextvars.ContextVar("rl_turn", default=None)


class _Ctx:
    def ledger(self) -> LedgerClient:
        v = _ledger.get()
        assert v is not None, "no LedgerClient in context; tool called outside run_turn"
        return v

    def emitter(self) -> EventEmitter | None:
        return _emitter.get()

    def turn(self) -> TurnRequest:
        v = _turn.get()
        assert v is not None
        return v

    def invocation(self) -> Invocation | None:
        """The tool call in progress (its tool_use_id and write keys), or None outside a tool."""
        return current_invocation()

    def bind(self, ledger: LedgerClient, emitter: EventEmitter | None, turn: TurnRequest) -> list[contextvars.Token]:
        return [_ledger.set(ledger), _emitter.set(emitter), _turn.set(turn)]

    def unbind(self, tokens: list[contextvars.Token]) -> None:
        for var, tok in zip((_ledger, _emitter, _turn), tokens, strict=True):
            var.reset(tok)


ctx = _Ctx()

ToolFn = Callable[..., Awaitable[str]]


def _args_payload(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    return {**kwargs} if not args else {"args": list(args), **kwargs}


async def _call(fn: ToolFn, args: tuple[Any, ...], kwargs: dict[str, Any]) -> tuple[bool, str, str]:
    """Run the tool body. Returns (ok, output for the model, event summary). Ledger refusals become
    readable output; any other exception propagates to the caller."""
    try:
        out = await fn(*args, **kwargs)
        return True, out, out[:300]
    except GateBlocked as gb:
        msg = json.dumps({"blocked": True, "reason": gb.reason, "verdict_id": gb.verdict_id})
        return False, msg, msg
    except LedgerError as le:
        msg = json.dumps({"error": True, "status": le.status, "detail": str(le.body)[:300]})
        return False, msg, msg


def error_summary(name: str, e: BaseException) -> str:
    detail = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
    return json.dumps({"error": True, "tool": name, "detail": detail[:300]})


def ledger_tool(name: str, description: str) -> Callable[[ToolFn], ToolFn]:
    """Mark an async function as an agent tool. Wraps it so GateBlocked/LedgerError become
    readable tool output (not exceptions) and so tool_call/tool_result events are emitted (also when
    the body raises: the result closes ok=false and the exception propagates)."""

    def deco(fn: ToolFn) -> ToolFn:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> str:
            explicit = kwargs.pop("_tool_use_id", None)
            inv = current_invocation()
            if inv is not None and inv.take(name):
                # DroidAgent._offload bound this invocation for us and narrates it; record the outcome.
                try:
                    ok, out, summary = await _call(fn, args, kwargs)
                except Exception as e:
                    inv.record(False, error_summary(name, e))
                    raise
                inv.record(ok, summary)
                return out
            if inv is not None:  # nested inside another tool's invocation
                return (await _call(fn, args, kwargs))[1]
            inv = Invocation(explicit or LedgerClient.new_tool_use_id(), name, source=SOURCE_EXPLICIT if explicit else SOURCE_LOCAL)
            inv.take(name)
            em = ctx.emitter()
            with bind_invocation(inv):
                if em:
                    em.tool_call(name, _args_payload(args, kwargs), inv.tool_use_id)
                try:
                    ok, out, summary = await _call(fn, args, kwargs)
                except Exception as e:
                    if em:
                        em.tool_result(inv.tool_use_id, False, error_summary(name, e))
                    raise
                if em:
                    em.tool_result(inv.tool_use_id, ok, summary)
                return out

        wrapper._rl_tool = (name, description)  # type: ignore[attr-defined]
        return wrapper

    return deco


def collect_tools(obj: Any) -> list[tuple[str, str, ToolFn]]:
    """Find all `ledger_tool`-marked callables on an object or module."""
    out: list[tuple[str, str, ToolFn]] = []
    for attr in dir(obj):
        fn = getattr(obj, attr, None)
        meta = getattr(fn, "_rl_tool", None)
        if callable(fn) and meta:
            out.append((meta[0], meta[1], fn))
    return out
