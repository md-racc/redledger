"""LedgerClient.get_extension: the public read for team extension routes (/api/x/<area>/...)."""

from __future__ import annotations

import httpx
import pytest
import respx

from agentkit import AgentSettings, LedgerClient, LedgerError

S = AgentSettings(AGENT_NAME="blue", BATTLEFIELD_URL="http://bf", INTERNAL_TOKEN="t")


@respx.mock
async def test_get_extension_reads_the_area_route_with_agent_headers() -> None:
    route = respx.get("http://bf/api/x/blue/crs/employees/emp_1").mock(return_value=httpx.Response(200, json={"persona": "P01"}))
    async with LedgerClient(S, episode_id="ep_1", day=2) as ledger:
        assert await ledger.get_extension("blue", "/crs/employees/emp_1", verbose=None) == {"persona": "P01"}
    req = route.calls.last.request
    assert req.headers["X-Agent"] == "blue" and req.headers["X-Episode"] == "ep_1" and req.headers["X-Day"] == "2"
    assert req.headers["Authorization"] == "Bearer t"
    assert "X-Tool-Use-Id" not in req.headers  # a read, never a keyed write
    assert req.url.params.get("verbose") is None  # None params are dropped, like every other read


@respx.mock
async def test_get_extension_passes_params_and_maps_errors() -> None:
    respx.get("http://bf/api/x/fe/nudges", params={"limit": "5"}).mock(return_value=httpx.Response(200, json=[]))
    respx.get("http://bf/api/x/blue/missing").mock(return_value=httpx.Response(404, json={"detail": "nope"}))
    async with LedgerClient(S, episode_id="ep_1", day=2) as ledger:
        assert await ledger.get_extension("fe", "nudges", limit=5) == []
        with pytest.raises(LedgerError) as e:
            await ledger.get_extension("blue", "missing")
    assert e.value.status == 404


@pytest.mark.parametrize(("area", "path"), [("purple", "x"), ("blue", ""), ("blue", "../events"), ("blue", "a/../../b"), ("blue", "a?b=1")])
async def test_get_extension_refuses_bad_areas_and_paths(area: str, path: str) -> None:
    async with LedgerClient(S, episode_id="ep_1", day=2) as ledger:
        with pytest.raises(ValueError):
            await ledger.get_extension(area, path)
