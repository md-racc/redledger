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
