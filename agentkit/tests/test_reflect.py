"""POST /reflect on every agent service, DroidAgent.reflect hooks, and the LedgerClient playbook calls."""

import asyncio
import json

import httpx
import respx

from agentkit import AgentSettings, DroidAgent, LedgerClient, ReflectResponse, TurnResponse
from agentkit.server import make_agent_app

REQ = {
    "lineage_id": "ln_1",
    "generation": 2,
    "episode_id": "ep_1",
    "review": {"generation": 2, "items": []},
    "playbook": {"version": 7, "parent_version": 6, "generation": 2, "episode_id": "ep_1", "day": 4, "source": "turn", "content": {"k": 1}, "rationale": "r"},
}
AUTH = {"Authorization": "Bearer t"}


def settings(**kw):
    return AgentSettings(AGENT_NAME="red", BATTLEFIELD_URL="http://bf", INTERNAL_TOKEN="t", **kw)


class _Agent(DroidAgent):
    name = "red"

    def tools(self):
        return []

    async def build_prompt(self, req):
        return ""

    async def dry_run_turn(self, req):
        return ""


class _Evolving(_Agent):
    async def reflect(self, req):
        return ReflectResponse(ok=True, playbook={"k": req.playbook.content["k"] + 1}, rationale="learned", usage={"factory_credits": 1.5})


class _LiveOnly(_Agent):
    async def reflect(self, req):
        raise AssertionError("model call under DRY_RUN")


class _Slow(_Agent):
    async def reflect(self, req):
        await asyncio.sleep(5)
        return ReflectResponse(ok=True, playbook={"never": True})


class _BadShape(_Agent):
    async def reflect(self, req):
        return {"ok": True, "playbook": "not-a-dict"}


class _Broken(_Agent):
    async def reflect(self, req):
        raise RuntimeError("boom")


async def post(app, body=REQ, headers=AUTH):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://agent") as c:
        return await c.post("/reflect", json=body, headers=headers)


async def test_reflect_requires_the_agent_token():
    app = make_agent_app(_Agent, settings=settings())
    assert (await post(app, headers={})).status_code == 401
    assert (await post(app, headers={"Authorization": "Bearer nope"})).status_code == 401


async def test_default_reflect_keeps_the_playbook():
    for dry in (False, True):
        r = await post(make_agent_app(_Agent, settings=settings(DRY_RUN=dry)))
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True and body["playbook"] is None


async def test_dry_run_never_calls_the_live_reflect():
    r = await post(make_agent_app(_LiveOnly, settings=settings(DRY_RUN=True)))
    assert r.status_code == 200
    assert r.json()["ok"] is True and r.json()["playbook"] is None


async def test_overridden_reflect_returns_new_content_and_usage():
    r = await post(make_agent_app(_Evolving, settings=settings()))
    body = r.json()
    assert body["ok"] is True and body["playbook"] == {"k": 2} and body["rationale"] == "learned"
    assert body["usage"]["factory_credits"] == 1.5


async def test_reflect_timeout_and_failure_keep_the_playbook_without_a_500():
    r = await post(make_agent_app(_Slow, settings=settings(TURN_TIMEOUT_SEC=11)))  # budget = 11 - 10 = 1 s
    assert r.status_code == 200 and r.json() == {"ok": False, "playbook": None, "rationale": "reflect timed out", "usage": None}
    r = await post(make_agent_app(_Broken, settings=settings()))
    assert r.status_code == 200 and r.json()["ok"] is False and "boom" in r.json()["rationale"]


async def test_reflect_409s_while_a_turn_holds_the_lock():
    started, release = asyncio.Event(), asyncio.Event()

    class _Busy(_Agent):
        async def run_turn(self, req):
            started.set()
            await release.wait()
            return TurnResponse(ok=True, summary="", duration_sec=0)

    app = make_agent_app(_Busy, settings=settings())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://agent") as c:
        turn = asyncio.create_task(c.post("/turn", json={"episode_id": "ep_1", "day": 1, "controller_mode": "off"}, headers=AUTH))
        await asyncio.wait_for(started.wait(), 2)
        r = await c.post("/reflect", json=REQ, headers=AUTH)
        assert r.status_code == 409
        release.set()
        assert (await turn).status_code == 200
        assert (await c.post("/reflect", json=REQ, headers=AUTH)).status_code == 200


@respx.mock
async def test_playbook_client_paths_headers_and_404s():
    get = respx.get("http://bf/api/playbook").mock(return_value=httpx.Response(200, json={"version": 3, "content": {}}))
    put = respx.put("http://bf/api/playbook").mock(return_value=httpx.Response(201, json={"version": 4}))
    hist = respx.get("http://bf/api/playbook/history").mock(return_value=httpx.Response(200, json=[{"version": 4}]))
    async with LedgerClient(settings(), episode_id="ep_1", day=2) as ledger:
        assert (await ledger.get_playbook())["version"] == 3
        assert (await ledger.put_playbook({"a": 1}, "why", 3, tool_use_id="toolu_1"))["version"] == 4
        assert await ledger.playbook_history(limit=5) == [{"version": 4}]
    req = put.calls.last.request
    assert req.headers["X-Tool-Use-Id"] == "toolu_1"
    assert (req.headers["X-Agent"], req.headers["X-Episode"], req.headers["X-Day"]) == ("red", "ep_1", "2")
    assert json.loads(req.content) == {"content": {"a": 1}, "rationale": "why", "base_version": 3}
    assert hist.calls.last.request.url.params["limit"] == "5"
    assert get.called

    respx.get("http://bf/api/playbook").mock(return_value=httpx.Response(404, json={"error": "not a lineage episode"}))
    respx.get("http://bf/api/playbook/history").mock(return_value=httpx.Response(404, json={"error": "not a lineage episode"}))
    async with LedgerClient(settings(), episode_id="ep_1", day=2) as ledger:
        assert await ledger.get_playbook() is None
        assert await ledger.playbook_history() == []


async def test_reflect_hook_returning_a_bad_shape_is_ok_false_not_a_500():
    r = await post(make_agent_app(_BadShape, settings=settings()))
    assert r.status_code == 200
    assert r.json()["ok"] is False
