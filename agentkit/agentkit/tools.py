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
"""

from __future__ import annotations

import contextvars
import functools
import json
from collections.abc import Awaitable, Callable
from typing import Any

from .events import EventEmitter
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

    def bind(self, ledger: LedgerClient, emitter: EventEmitter | None, turn: TurnRequest) -> list[contextvars.Token]:
        return [_ledger.set(ledger), _emitter.set(emitter), _turn.set(turn)]

    def unbind(self, tokens: list[contextvars.Token]) -> None:
        for var, tok in zip((_ledger, _emitter, _turn), tokens, strict=True):
            var.reset(tok)


ctx = _Ctx()

ToolFn = Callable[..., Awaitable[str]]


def ledger_tool(name: str, description: str) -> Callable[[ToolFn], ToolFn]:
    """Mark an async function as an agent tool. Wraps it so GateBlocked/LedgerError become
    readable tool output (not exceptions) and so tool_call/tool_result events are emitted."""

    def deco(fn: ToolFn) -> ToolFn:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> str:
            em = ctx.emitter()
            tool_use_id = kwargs.pop("_tool_use_id", None) or LedgerClient.new_tool_use_id()
            if em:
                em.tool_call(name, {**kwargs} if not args else {"args": list(args), **kwargs}, tool_use_id)
            try:
                out = await fn(*args, **kwargs)
                if em:
                    em.tool_result(tool_use_id, True, out[:300])
                return out
            except GateBlocked as gb:
                msg = json.dumps({"blocked": True, "reason": gb.reason, "verdict_id": gb.verdict_id})
                if em:
                    em.tool_result(tool_use_id, False, msg)
                return msg
            except LedgerError as le:
                msg = json.dumps({"error": True, "status": le.status, "detail": str(le.body)[:300]})
                if em:
                    em.tool_result(tool_use_id, False, msg)
                return msg

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
