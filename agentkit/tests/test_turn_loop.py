"""Package B, PR 4: turns on their own loop (B-4), loop ownership + TurnLock (B-5), redact (B-6)."""

import asyncio
import contextvars
import json
import threading
import time

import httpx
import pytest
import respx

import agentkit.droid_agent as da
from agentkit import AgentSettings, DroidAgent, ReflectRequest, TurnLock, TurnRequest, ctx, ledger_tool, make_agent_app
from agentkit.events import EventEmitter
from agentkit.invocation import SOURCE_STREAM, InvocationRegistry
from agentkit.sync import TurnLoopTimeout, run_on_turn_loop

TURN = TurnRequest(episode_id="ep_1", day=3, controller_mode="off")
AUTH = {"Authorization": "Bearer t"}
SCOPE: contextvars.ContextVar[str] = contextvars.ContextVar("scope", default="unset")


def settings(**kw):
    return AgentSettings(AGENT_NAME="blue", BATTLEFIELD_URL="http://bf", INTERNAL_TOKEN="t", DRY_RUN=True, **kw)


@ledger_tool("nap", "Sleep in the worker for a while.")
async def nap(sec: float) -> str:
    await asyncio.sleep(sec)
    return "rested"


@ledger_tool("wait_forever", "Cooperatively wait until cancelled.")
async def wait_forever() -> str:
    await asyncio.sleep(3600)
    return "unreachable"


@ledger_tool("pay", "A tool with a private argument.", redact=lambda a: {k: v for k, v in a.items() if k != "secret"})
async def pay(amount: int, secret: str = "") -> str:
    return f"paid {amount}"


class _Rec:
    """Stands in for EventEmitter inside a turn; records (kind, args, thread)."""

    def __init__(self):
        self.calls: list[tuple[str, tuple, int]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    def tool_call(self, *a):
        self.calls.append(("tool_call", a, threading.get_ident()))

    def tool_result(self, *a):
        self.calls.append(("tool_result", a, threading.get_ident()))

    def thinking(self, *a):
        self.calls.append(("thinking", a, threading.get_ident()))


class _Agent(DroidAgent):
    name = "blue"
    turn_loop_dry_run = True

    def __init__(self, s, body=None):
        super().__init__(s)
        self.body = body
        self.seen: dict = {}

    def tools(self):
        return [("nap", "nap", nap), ("wait_forever", "w", wait_forever), ("pay", "pay", pay)]

    async def build_prompt(self, req):
        return ""

    async def dry_run_turn(self, req):
        self.seen.update(thread=threading.current_thread().name, ident=threading.get_ident(), scope=SCOPE.get())
        SCOPE.set("changed-inside")
        return await self.body(self) if self.body else "ok"


# ---------- B-4: the service loop stays responsive ----------


async def _max_service_gap(app, turn_body: dict) -> tuple[float, float, httpx.Response]:
    """Run a turn through the app while (a) a heartbeat task ticks every 10 ms and (b) /health is
    polled. Returns (worst heartbeat gap, worst /health latency, the /turn response)."""
    gaps: list[float] = []
    stop = asyncio.Event()

    async def heartbeat():
        last = time.monotonic()
        while not stop.is_set():
            await asyncio.sleep(0.01)
            now = time.monotonic()
            gaps.append(now - last)
            last = now

    beat = asyncio.create_task(heartbeat())
    worst_health = 0.0
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://agent", headers=AUTH) as client:
        running = asyncio.create_task(client.post("/turn", json=turn_body))
        while not running.done():
            t0 = time.monotonic()
            assert (await client.get("/health")).status_code == 200
            worst_health = max(worst_health, time.monotonic() - t0)
            await asyncio.sleep(0.02)
        resp = await running
    stop.set()
    await beat
    return max(gaps) - 0.01, worst_health, resp


@pytest.mark.parametrize("on_turn_loop", [True, False])
async def test_service_loop_answers_within_50ms_while_a_tool_freezes_the_turn_for_2s(monkeypatch, on_turn_loop):
    """The SDK serves our sync tool handler on the session's loop and it blocks until the tool ends
    (DroidAgent._offload). On the turn's own loop that freeze never reaches the service loop; the
    control case (same turn on the service loop) shows what it would do to /health and Blue's /gate."""
    monkeypatch.setattr(da, "EventEmitter", lambda *a, **kw: _Rec())

    async def body(agent):
        return agent._offload(nap)(sec=2.0)  # sync, like the SDK's call: freezes this loop for 2 s

    monkeypatch.setattr(_Agent, "turn_loop_dry_run", on_turn_loop)
    app = make_agent_app(lambda s: _Agent(s, body), settings=settings())  # type: ignore[arg-type]
    gap, health, resp = await _max_service_gap(app, TURN.model_dump())
    assert resp.status_code == 200 and resp.json()["ok"] is True
    if on_turn_loop:
        assert gap <= 0.05 and health <= 0.05, f"service loop stalled: heartbeat gap {gap:.3f}s, /health {health:.3f}s"
    else:
        assert gap >= 1.5  # control: the freeze lands on the service loop


async def test_dry_run_turn_runs_on_its_own_thread_with_the_callers_context(monkeypatch):
    monkeypatch.setattr(da, "EventEmitter", lambda *a, **kw: _Rec())
    agent = _Agent(settings())
    SCOPE.set("set-by-caller")
    resp = await agent.run_turn(TURN)
    assert resp.ok and resp.summary == "[dry-run] ok"
    assert agent.seen["thread"] == "blue-turn-d3" and agent.seen["ident"] != threading.get_ident()
    assert agent.seen["scope"] == "set-by-caller"  # copied in
    assert SCOPE.get() == "set-by-caller"  # and nothing leaks back out


async def test_turn_loop_dry_run_off_keeps_the_turn_on_the_callers_loop(monkeypatch):
    monkeypatch.setattr(da, "EventEmitter", lambda *a, **kw: _Rec())
    monkeypatch.setattr(_Agent, "turn_loop_dry_run", False)
    agent = _Agent(settings())
    assert (await agent.run_turn(TURN)).ok
    assert agent.seen["ident"] == threading.get_ident()


async def test_cancelling_the_turn_from_the_service_loop_closes_the_open_pair_and_joins(monkeypatch):
    rec = _Rec()
    monkeypatch.setattr(da, "EventEmitter", lambda *a, **kw: rec)
    started = threading.Event()

    async def body(agent):
        started.set()
        return await wait_forever()  # direct call (DRY_RUN): the ledger_tool wrapper narrates it

    agent = _Agent(settings(), body)
    task = asyncio.create_task(agent.run_turn(TURN))
    assert await asyncio.to_thread(started.wait, 2)
    t0 = time.monotonic()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert time.monotonic() - t0 < 1.0
    kinds = [k for k, _, _ in rec.calls]
    assert kinds == ["tool_call", "tool_result"]
    result = rec.calls[1][1]
    assert result[0] == rec.calls[0][1][2] and result[1] is False and json.loads(result[2])["cancelled"] is True
    for _ in range(100):  # the thread closes its loop just after handing back the result
        if not any(t.name == "blue-turn-d3" for t in threading.enumerate()):
            break
        await asyncio.sleep(0.01)
    assert not any(t.name == "blue-turn-d3" for t in threading.enumerate())


async def test_a_wedged_turn_loop_hits_the_service_side_ceiling():
    def wedge():
        time.sleep(0.8)  # blocks its loop: no in-loop timeout can fire

    async def fn():
        wedge()
        return "late"

    t0 = time.monotonic()
    with pytest.raises(TurnLoopTimeout):
        await run_on_turn_loop(fn, name="wedged", ceiling_sec=0.1, join_sec=0.1)
    assert time.monotonic() - t0 < 0.5  # the caller stops waiting; the daemon thread finishes later


async def test_run_turn_turns_the_ceiling_into_ok_false(monkeypatch):
    monkeypatch.setattr(da, "EventEmitter", lambda *a, **kw: _Rec())

    async def body(agent):
        time.sleep(1.5)  # wedge the turn loop past the ceiling
        return "late"

    def short(fn, **kw):  # same call run_turn makes, with a test-sized ceiling
        return run_on_turn_loop(fn, **{**kw, "ceiling_sec": 0.2, "join_sec": 0.1})

    monkeypatch.setattr(da, "run_on_turn_loop", short)
    t0 = time.monotonic()
    resp = await _Agent(settings(), body).run_turn(TURN)
    assert resp.ok is False and resp.summary == "turn timed out"
    assert time.monotonic() - t0 < 1.0


async def test_emitter_is_created_and_drained_on_the_turn_loop():
    seen_posts: list[int] = []
    agent = _Agent(settings(), body=lambda a: _call_pay())
    with respx.mock(assert_all_called=False) as router:
        route = router.post("http://bf/api/events").mock(side_effect=lambda req: seen_posts.append(threading.get_ident()) or httpx.Response(201))
        resp = await agent.run_turn(TURN)
    assert resp.ok
    assert route.called and seen_posts and all(t == agent.seen["ident"] for t in seen_posts)
    sent = [e for call in route.calls for e in json.loads(call.request.content)]
    (tc,) = [e for e in sent if e["type"] == "agent.tool_call"]
    assert tc["payload"]["args"] == {"amount": 5} and "secret" not in json.dumps(sent)  # redacted on the wire


async def _call_pay():
    return await pay(amount=5, secret="s3cr3t")


async def test_reflect_runs_on_its_own_loop_too(monkeypatch):
    agent = _Agent(settings())
    where: dict = {}

    async def dry_run_reflect(req):
        where["ident"] = threading.get_ident()
        return {"ok": True, "rationale": "kept"}

    monkeypatch.setattr(agent, "dry_run_reflect", dry_run_reflect)
    req = ReflectRequest(
        lineage_id="ln",
        generation=1,
        episode_id="ep",
        playbook={"version": 0, "generation": 0, "source": "seed", "content": {}},
    )
    r = await agent.run_reflect(req)
    assert r.ok and r.rationale == "kept" and where["ident"] != threading.get_ident()


# ---------- B-5: ownership ----------


async def test_emitter_refuses_emits_from_another_thread():
    async with EventEmitter(settings(), episode_id="ep", day=1, flush_budget_sec=0.01) as em:
        with pytest.raises(RuntimeError, match="owner"):
            await asyncio.to_thread(em.tool_call, "x", {}, "id")
        assert em._q.empty()  # nothing was enqueued from the wrong thread


def test_registry_refuses_calls_from_another_thread():
    reg = InvocationRegistry("blue-ledger", [("nap", nap)])
    err: list[BaseException] = []

    def other():
        try:
            reg.observe("toolu_1", "nap", {"sec": 1}, SOURCE_STREAM)
        except BaseException as e:
            err.append(e)

    t = threading.Thread(target=other)
    t.start()
    t.join()
    assert err and isinstance(err[0], RuntimeError)
    assert reg.observe("toolu_1", "nap", {"sec": 1}, SOURCE_STREAM) is not None  # fine on its own thread


async def test_turnlock_excludes_across_loops_and_threads():
    lock = TurnLock()
    inside = 0
    peak = 0
    order: list[str] = []
    mu = threading.Lock()

    async def work(tag: str):
        nonlocal inside, peak
        async with lock:
            with mu:
                inside += 1
                peak = max(peak, inside)
                order.append(tag)
            await asyncio.sleep(0.02)
            with mu:
                inside -= 1

    def other_loop(tag: str):
        asyncio.run(work(tag))

    def plain_thread(tag: str):
        nonlocal inside, peak
        with lock:
            with mu:
                inside += 1
                peak = max(peak, inside)
                order.append(tag)
            time.sleep(0.02)
            with mu:
                inside -= 1

    threads = [threading.Thread(target=other_loop, args=(f"loop{i}",)) for i in range(3)]
    threads += [threading.Thread(target=plain_thread, args=(f"thread{i}",)) for i in range(2)]
    for t in threads:
        t.start()
    await asyncio.gather(*(work(f"main{i}") for i in range(3)))
    for t in threads:
        t.join(5)
    assert peak == 1 and len(order) == 8 and not lock.locked()


async def test_turnlock_cancelled_waiter_leaves_and_never_holds_it():
    lock = TurnLock()
    await lock.acquire()
    waiter = asyncio.create_task(lock.acquire())
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    lock.release()
    assert not lock.locked()
    async with lock:
        assert lock.locked()


async def test_turnlock_refuses_blocking_with_on_a_loop():
    with pytest.raises(RuntimeError, match="async with"):
        with TurnLock():
            pass


# ---------- B-6: redact ----------


async def test_redact_applies_on_offload_direct_call_and_registry_pairs():
    rec = _Rec()
    agent = _Agent(settings())
    async with da.LedgerClient(agent.s, episode_id="ep", day=1) as ledger:
        tokens = ctx.bind(ledger, rec, TURN)  # type: ignore[arg-type]
        try:
            assert agent._offload(pay)(amount=7, secret="x") == "paid 7"
            assert await pay(amount=8, secret="y") == "paid 8"
        finally:
            ctx.unbind(tokens)
    reg = InvocationRegistry("blue-ledger", [("pay", pay)], rec)
    reg.observe("toolu_9", "pay", {"amount": 9, "secret": "z"}, SOURCE_STREAM)
    reg.close()
    shown = [a[1] for k, a, _ in rec.calls if k == "tool_call"]
    assert shown == [{"amount": 7}, {"amount": 8}, {"amount": 9}]


def test_a_failing_redactor_never_leaks():
    from agentkit.tools import redacted_args

    def boom(_):
        raise ValueError

    fn = type("F", (), {"_rl_redact": staticmethod(boom)})()
    assert redacted_args(fn, {"secret": "x"}) == {"redacted": True}
