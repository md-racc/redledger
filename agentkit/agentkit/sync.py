"""Loop ownership helpers: per-turn event loops and a lock usable from any loop or thread.

Ownership rule (docs/AD-INTEGRATION-DESIGN.md B-5): every asyncio object (Future, Task, Lock, Queue,
httpx client, EventEmitter, InvocationRegistry, Droid Session) belongs to the loop that created it and
is only touched from that loop's thread. Crossing loops goes through `loop.call_soon_threadsafe` (or a
concurrent.futures.Future wrapped with `asyncio.wrap_future`), never a direct call.

Why a turn runs on its own loop: droid-sdk 0.5.0 serves in-process MCP tool handlers from a task on the
Session's loop and the handler must not yield (contracts/CHANGELOG.md Findings), so DroidAgent._offload
runs each tool synchronously and freezes that loop for the tool's duration. If the Session lived on the
service loop, /health, Blue's /gate and every other route would freeze with it. `run_on_turn_loop`
gives each turn a dedicated thread + loop; the service loop only awaits a future and stays responsive.

    result = await run_on_turn_loop(lambda: agent._run_turn_here(req), name="red-turn", ceiling_sec=180)

`TurnLock` is for turn-scoped mutable state shared between the turn loop, the service loop and tool
worker threads: an `asyncio.Lock` only works on one loop, a `threading.Lock` blocks a loop.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import threading
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import structlog

log = structlog.get_logger(__name__)

T = TypeVar("T")

# How long the service loop waits for a cancelled turn's thread to wind down (its finally blocks: the
# event flush, registry.close(), session teardown) before it stops waiting and lets the daemon thread
# finish on its own. A tool frozen inside the turn loop delays the cancel until the tool returns.
CANCEL_JOIN_SEC = 2.0


# How long teardown waits for the turn loop's leftover tasks to finish after cancelling them. Something
# the turn started and never awaited (droid-sdk's in-process MCP server leaves sse_starlette's
# `_shutdown_watcher` behind) would otherwise be destroyed while pending when the loop closes.
TEARDOWN_SEC = 2.0


def _cancel_leftover_tasks(loop: asyncio.AbstractEventLoop, name: str) -> None:
    """asyncio.run's `_cancel_all_tasks`, bounded: cancel what is still pending on `loop`, give it
    TEARDOWN_SEC to unwind, report unexpected exceptions through the loop's exception handler, and log
    (rather than wait forever on) anything that ignores the cancel."""
    tasks = [t for t in asyncio.all_tasks(loop) if not t.done()]
    if not tasks:
        return
    for t in tasks:
        t.cancel()
    _, pending = loop.run_until_complete(asyncio.wait(tasks, timeout=TEARDOWN_SEC))
    if pending:
        log.warning("turn_loop_tasks_abandoned", turn_loop=name, count=len(pending))
    for t in tasks:
        if t in pending or t.cancelled():
            continue
        if (exc := t.exception()) is not None:
            loop.call_exception_handler({"message": "unhandled exception in a leftover turn-loop task", "exception": exc, "task": t})


class TurnLoopTimeout(TimeoutError):
    """The turn did not finish within the service-side ceiling and was cancelled."""


async def run_on_turn_loop(
    fn: Callable[[], Awaitable[T]],
    *,
    name: str,
    ceiling_sec: float | None = None,
    join_sec: float = CANCEL_JOIN_SEC,
) -> T:
    """Run `fn()` to completion on a new event loop in a dedicated thread, under a copy of the caller's
    context (turn-scoped ContextVars a subclass set before calling, e.g. green's clerk_scope or Blue's
    SESSION, are visible inside; changes made inside do not leak back). The calling loop awaits the
    result and keeps serving other work meanwhile.

    Cancellation of the caller (or `ceiling_sec` passing) is forwarded to the turn's task with
    `call_soon_threadsafe(task.cancel)`; the caller then waits up to `join_sec` for the turn's cleanup.
    On the ceiling, TurnLoopTimeout is raised; a forwarded cancel re-raises CancelledError."""
    caller_ctx = contextvars.copy_context()
    done: concurrent.futures.Future[T] = concurrent.futures.Future()
    ready = threading.Event()
    handle: dict[str, Any] = {}

    async def main() -> T:
        handle["task"] = asyncio.current_task()
        ready.set()
        return await fn()

    def target() -> None:
        loop = asyncio.new_event_loop()
        handle["loop"] = loop
        try:
            asyncio.set_event_loop(loop)
            try:
                done.set_result(loop.run_until_complete(main()))
            except BaseException as e:  # noqa: BLE001  — every outcome, incl. cancellation, goes to the caller
                done.set_exception(e)
            finally:
                ready.set()
                try:
                    # The caller already has the result (done is set above), so this teardown never
                    # delays the reply; it runs on the turn thread, like asyncio.run's own cleanup.
                    _cancel_leftover_tasks(loop, name)
                    loop.run_until_complete(loop.shutdown_asyncgens())
                    loop.run_until_complete(loop.shutdown_default_executor())
                except Exception as e:  # cleanup only
                    log.warning("turn_loop_shutdown_error", turn_loop=name, error=str(e))
        finally:
            asyncio.set_event_loop(None)
            loop.close()

    thread = threading.Thread(target=caller_ctx.run, args=(target,), name=name, daemon=True)
    thread.start()
    outer = asyncio.wrap_future(done)
    outer.add_done_callback(_retrieve)  # a turn we stopped waiting for must not log "never retrieved"
    try:
        if ceiling_sec is None:
            return await asyncio.shield(outer)
        return await asyncio.wait_for(asyncio.shield(outer), timeout=ceiling_sec)
    except TimeoutError:
        if outer.done() and not outer.cancelled():
            return outer.result()  # it finished in the same instant
        await _cancel_and_join(name, handle, ready, outer, join_sec, reason="ceiling")
        raise TurnLoopTimeout(f"{name} exceeded {ceiling_sec}s") from None
    except asyncio.CancelledError:
        await _cancel_and_join(name, handle, ready, outer, join_sec, reason="caller_cancelled")
        raise


async def _cancel_and_join(name: str, handle: dict[str, Any], ready: threading.Event, outer: asyncio.Future[Any], join_sec: float, *, reason: str) -> None:
    if not ready.is_set():
        await asyncio.to_thread(ready.wait, join_sec)
    loop, task = handle.get("loop"), handle.get("task")
    if loop is not None and task is not None and not loop.is_closed():
        try:
            loop.call_soon_threadsafe(task.cancel)
        except RuntimeError:  # the loop closed in between: nothing left to cancel
            pass
    try:
        await asyncio.wait({outer}, timeout=join_sec)
    except asyncio.CancelledError:  # cancelled again while joining: stop waiting, the thread is a daemon
        pass
    if outer.done():
        _retrieve(outer)  # the turn's own error after cancellation was already logged inside the turn
        log.info("turn_loop_cancelled", turn_loop=name, reason=reason)
    else:
        log.error("turn_loop_join_timeout", turn_loop=name, reason=reason, join_sec=join_sec, detail="turn thread still winding down; left as a daemon")


def _retrieve(fut: asyncio.Future[Any]) -> None:
    if not fut.cancelled():
        fut.exception()


class _Waiter:
    __slots__ = ("loop", "fut", "event")

    def __init__(self, loop: asyncio.AbstractEventLoop | None):
        self.loop = loop
        self.fut: asyncio.Future[None] | None = loop.create_future() if loop is not None else None
        self.event = threading.Event() if loop is None else None

    def wake(self) -> None:
        """Hand the lock to this waiter, from any thread."""
        if self.loop is None:
            assert self.event is not None
            self.event.set()
            return
        fut = self.fut

        def set_it() -> None:
            assert fut is not None
            if not fut.done():
                fut.set_result(None)

        self.loop.call_soon_threadsafe(set_it)  # RuntimeError if its loop closed: release() tries the next


class TurnLock:
    """A FIFO mutex awaitable from any event loop and acquirable from plain threads.

        lock = TurnLock()
        async with lock:          # on the service loop, the turn loop, or a tool worker's private loop
            ...
        with lock:                # from a thread with no running loop (blocks only that thread)
            ...

    Release hands ownership directly to the next waiter (no barging), waking it on its own loop with
    call_soon_threadsafe. A waiter cancelled while queued leaves the queue; one cancelled after it was
    handed the lock passes it on. Not reentrant."""

    def __init__(self) -> None:
        self._mu = threading.Lock()
        self._locked = False
        self._waiters: deque[_Waiter] = deque()

    def locked(self) -> bool:
        with self._mu:
            return self._locked

    async def acquire(self) -> bool:
        loop = asyncio.get_running_loop()
        with self._mu:
            if not self._locked and not self._waiters:
                self._locked = True
                return True
            w = _Waiter(loop)
            self._waiters.append(w)
        assert w.fut is not None
        try:
            await w.fut
        except asyncio.CancelledError:
            with self._mu:
                if w in self._waiters:  # still queued: just leave
                    self._waiters.remove(w)
                    raise
            self.release()  # ownership was already handed to us: pass it on
            raise
        return True

    def acquire_sync(self, timeout: float | None = None) -> bool:
        """Blocking acquire for a thread without a running loop. Returns False on timeout."""
        with self._mu:
            if not self._locked and not self._waiters:
                self._locked = True
                return True
            w = _Waiter(None)
            self._waiters.append(w)
        assert w.event is not None
        if w.event.wait(timeout):
            return True
        with self._mu:
            if w in self._waiters:
                self._waiters.remove(w)
                return False
        return True  # handed to us just as we gave up: we own it

    def release(self) -> None:
        with self._mu:
            if not self._locked:
                raise RuntimeError("TurnLock.release() of an unlocked lock")
            while self._waiters:
                w = self._waiters.popleft()
                try:
                    w.wake()  # stays locked: ownership moves to w
                    return
                except RuntimeError:  # w's loop is closed; try the next waiter
                    continue
            self._locked = False

    async def __aenter__(self) -> TurnLock:
        await self.acquire()
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.release()

    def __enter__(self) -> TurnLock:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            self.acquire_sync()
            return self
        raise RuntimeError("use `async with TurnLock()` on an event loop; `with` would block the loop")

    def __exit__(self, *exc: object) -> None:
        self.release()
