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
