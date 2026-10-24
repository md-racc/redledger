import asyncio
import json
import time

import httpx
import respx

from agentkit.config import AgentSettings
from agentkit.events import EventEmitter

S = AgentSettings(AGENT_NAME="red", BATTLEFIELD_URL="http://bf", AGENT_TOKEN="a")


@respx.mock
async def test_event_batches_carry_agent_headers_and_a_fresh_tool_use_id():
    # battlefield 400s any agent write without X-Tool-Use-Id, which silently dropped all narration
    route = respx.post("http://bf/api/events").mock(return_value=httpx.Response(202, json={"accepted": 1}))
    async with EventEmitter(S, episode_id="ep_1", day=2) as em:
        em.tool_call("list_invoices", {}, "tu_1")
        await em.flush()
        em.tool_result("tu_1", True, "ok")
        await em.flush()

    assert route.call_count == 2
    keys = set()
    for call in route.calls:
        h = call.request.headers
        assert h["Authorization"] == "Bearer a"
        assert (h["X-Agent"], h["X-Episode"], h["X-Day"]) == ("red", "ep_1", "2")
        assert h.get("X-Tool-Use-Id")
        keys.add(h["X-Tool-Use-Id"])
    assert len(keys) == 2  # never reuse a key across different writes (AGENTS.md §3.7)


@respx.mock
async def test_exit_drains_everything_queued_in_batches_of_50():
    # Regression: __aexit__ used to send one batch (≤ 50) and cancel the pump, losing the rest.
    route = respx.post("http://bf/api/events").mock(return_value=httpx.Response(202, json={"accepted": 50}))
    async with EventEmitter(S, episode_id="ep_1", day=2, flush_every=3600) as em:
        for i in range(130):
            em.tool_result(f"tu_{i}", True, "ok")

    assert route.call_count == 3
    sizes = [len(json.loads(c.request.content)) for c in route.calls]
    assert sizes == [50, 50, 30]
    sent = [e["payload"]["tool_use_id"] for c in route.calls for e in json.loads(c.request.content)]
    assert sent == [f"tu_{i}" for i in range(130)]  # in order, none duplicated
    keys = {c.request.headers["X-Tool-Use-Id"] for c in route.calls}
    assert len(keys) == 3


@respx.mock
async def test_flush_includes_buffered_thinking():
    route = respx.post("http://bf/api/events").mock(return_value=httpx.Response(202, json={}))
    async with EventEmitter(S, episode_id="ep_1", day=2, flush_every=3600) as em:
        em.thinking("short thought")  # under the 200-char auto-flush threshold
    (call,) = route.calls
    (ev,) = json.loads(call.request.content)
    assert ev["type"] == "agent.thinking" and ev["payload"]["text"] == "short thought"


@respx.mock
async def test_pump_and_flush_never_double_send():
    route = respx.post("http://bf/api/events").mock(return_value=httpx.Response(202, json={}))
    async with EventEmitter(S, episode_id="ep_1", day=2, flush_every=0.001) as em:
        for i in range(120):
            em.tool_result(f"tu_{i}", True, "ok")
        await asyncio.gather(em.flush(), em.flush(), asyncio.sleep(0.01))
        for i in range(120, 175):
            em.tool_result(f"tu_{i}", True, "ok")
    sent = [e["payload"]["tool_use_id"] for c in route.calls for e in json.loads(c.request.content)]
    assert sorted(sent) == sorted(f"tu_{i}" for i in range(175))
    assert len(sent) == len(set(sent))


@respx.mock
async def test_dead_battlefield_cannot_hang_the_turn(monkeypatch):
    async def never(request):
        await asyncio.sleep(3600)

    respx.post("http://bf/api/events").mock(side_effect=never)
    logs = []
    monkeypatch.setattr("agentkit.events.log.warning", lambda ev, **kw: logs.append((ev, kw)))
    t0 = time.monotonic()
    async with EventEmitter(S, episode_id="ep_1", day=2, flush_every=3600, flush_budget_sec=0.3) as em:
        for i in range(130):
            em.tool_result(f"tu_{i}", True, "ok")
    assert time.monotonic() - t0 < 1.0
    dropped = sum(kw.get("dropped", 0) for ev, kw in logs if ev == "event_emit_error")
    dropped += sum(kw.get("count", 0) for ev, kw in logs if ev == "events_dropped")
    assert dropped == 130  # every lost event is accounted for in the logs


def _dropped_total(logs) -> int:
    n = sum(kw.get("dropped", 0) for ev, kw in logs if ev == "event_emit_error")
    return n + sum(kw.get("count", 0) for ev, kw in logs if ev == "events_dropped")


@respx.mock
async def test_flush_budget_covers_waiting_for_a_pump_stuck_mid_post(monkeypatch):
    # Regression: flush() waited out the pump's in-flight POST (full HTTP_TIMEOUT_SEC) before its budget applied.
    async def never(request):
        await asyncio.sleep(3600)

    respx.post("http://bf/api/events").mock(side_effect=never)
    logs = []
    monkeypatch.setattr("agentkit.events.log.warning", lambda ev, **kw: logs.append((ev, kw)))
    s = AgentSettings(AGENT_NAME="red", BATTLEFIELD_URL="http://bf", AGENT_TOKEN="a", HTTP_TIMEOUT_SEC=3)
    async with EventEmitter(s, episode_id="ep_1", day=2, flush_every=0.05, flush_budget_sec=0.3) as em:
        em.tool_result("a", True, "x")
        await asyncio.sleep(0.1)  # the pump has dequeued it and is hanging on the POST
        for i in range(10):
            em.tool_result(f"b{i}", True, "x")
        t_exit = time.monotonic()
    assert time.monotonic() - t_exit < 0.8  # budget, not the 3 s HTTP timeout
    assert _dropped_total(logs) == 11  # the in-flight batch (cancelled) plus the 10 still queued
    assert any(kw.get("reason") == "cancelled_mid_post" and kw["count"] == 1 for ev, kw in logs if ev == "events_dropped")


@respx.mock
async def test_pump_cancelled_mid_post_logs_its_batch(monkeypatch):
    async def slowish(request):
        await asyncio.sleep(1)
        return httpx.Response(202, json={})

    respx.post("http://bf/api/events").mock(side_effect=slowish)
    logs = []
    monkeypatch.setattr("agentkit.events.log.warning", lambda ev, **kw: logs.append((ev, kw)))
    em = EventEmitter(S, episode_id="ep_1", day=2, flush_every=0.01, flush_budget_sec=5)
    await em.__aenter__()
    em.tool_result("straggler", True, "x")
    await asyncio.sleep(0.05)  # pump is mid-POST
    em._task.cancel()
    try:
        await em._task
    except asyncio.CancelledError:
        pass
    await em._client.aclose()
    assert [(ev, kw["count"], kw["reason"]) for ev, kw in logs] == [("events_dropped", 1, "cancelled_mid_post")]
