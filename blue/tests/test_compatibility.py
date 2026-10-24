"""Offline integration checks for the refreshed shared auth and event contracts."""

import json
from uuid import UUID

import httpx
import pytest
import respx
from server import extra

from agentkit import make_agent_app
from agentkit.config import AgentSettings
from agentkit.events import EventEmitter
from audit.agent import AuditAgent


@pytest.mark.parametrize("path", ["/turn", "/audit", "/gate", "/gate/explain"])
async def test_resolved_agent_token_wins_and_operator_legacy_tokens_are_rejected(runtime, gate_request, path):
    prototype, _, _ = runtime()
    assert prototype.s.internal_token == "test-agent"
    app = make_agent_app(AuditAgent, settings=prototype.s, extra_routes=extra)
    body = {"episode_id": "ep", "day": 5}
    if path == "/turn":
        body["controller_mode"] = "enforce"
    elif path.startswith("/gate"):
        body = gate_request().model_dump()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://blue") as client:
        for wrong in ("test-operator", "test-legacy", "wrong"):
            response = await client.post(path, json=body, headers={"Authorization": f"Bearer {wrong}"})
            assert response.status_code == 401
        response = await client.post(path, json=body, headers={"Authorization": "Bearer test-agent"})
        assert response.status_code == 200


def test_legacy_internal_token_remains_a_fallback(monkeypatch):
    monkeypatch.delenv("AGENT_TOKEN", raising=False)
    settings = AgentSettings(AGENT_NAME="blue", INTERNAL_TOKEN="legacy-only", _env_file=None)
    assert settings.internal_token == "legacy-only"


@respx.mock
async def test_event_batch_uses_agent_auth_and_a_uuid4_write_header():
    route = respx.post("http://battlefield:8000/api/events").mock(return_value=httpx.Response(200, json={}))
    settings = AgentSettings(
        AGENT_NAME="blue",
        BATTLEFIELD_URL="http://battlefield:8000",
        AGENT_TOKEN="test-agent",
        INTERNAL_TOKEN="test-legacy",
        DRY_RUN=True,
        _env_file=None,
    )
    async with EventEmitter(settings, episode_id="ep", day=5, flush_every=3600) as emitter:
        emitter.thinking("Reviewing derived control facts.")
        await emitter.flush()
    assert route.call_count == 1
    request = route.calls[0].request
    assert request.headers["Authorization"] == "Bearer test-agent"
    assert UUID(request.headers["X-Tool-Use-Id"]).version == 4
    assert json.loads(request.content)[0]["type"] == "agent.thinking"
