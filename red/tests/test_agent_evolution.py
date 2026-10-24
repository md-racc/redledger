"""Keyless service, invocation identity and lineage/plain regressions."""

import json
import threading
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from evolution import NAMESPACE, fold

import tools as red_tools
from agent import RedAgent
from agentkit import AgentSettings, LedgerClient, TurnRequest, ctx, ledger_tool
from agentkit.models import Playbook, ReflectRequest
from agentkit.server import make_agent_app
from schemes import SCHEMES

S = AgentSettings(_env_file=None, AGENT_NAME="red", BATTLEFIELD_URL="http://bf", AGENT_TOKEN="test-agent", DRY_RUN=True)
FIRST = next(iter(SCHEMES))
ITEM = {"kind": "attack", "attack_id": "a", "scheme_id": FIRST, "day_launched": 0, "resolved_day": 0, "outcome": "blocked", "detected_day": 0, "controls": []}


def turn(lineage=True, **options):
    return TurnRequest(
        episode_id="ep",
        day=1,
        controller_mode="enforce",
        options={
            **({"lineage": {"id": "ln", "generation": 0, "playbook_version": 7}, "debrief": {"items": [ITEM]}} if lineage else {}),
            **options,
        },
    )


def playbook(content=None):
    return {"version": 7, "generation": 0, "source": "turn", "content": content or {}}


class Events:
    def __init__(self):
        self.calls = []

    def tool_call(self, name, args, key):
        self.calls.append(("call", key))

    def tool_result(self, key, ok, summary):
        self.calls.append(("result", key, ok))


def books_routes():
    for route in ("vendors", "invoices", "vendor_changes"):
        respx.get(f"http://bf/api/{route}").respond(200, json=[])


@pytest.mark.parametrize("status", [200, 409, 413, 500])
@respx.mock
async def test_inspection_uses_active_version_and_one_invocation_pair(status):
    books_routes()
    respx.get("http://bf/api/playbook").respond(200, json=playbook())
    write = respx.put("http://bf/api/playbook").respond(status, json=playbook())
    events = Events()
    async with LedgerClient(S, episode_id="ep", day=1) as ledger:
        tokens = ctx.bind(ledger, events, turn())
        try:
            result = json.loads(await red_tools.inspect_books(_tool_use_id="current-call"))
        finally:
            ctx.unbind(tokens)
    assert write.call_count == 1  # no blind retries, including ambiguous server failures
    request = write.calls[0].request
    assert request.headers["X-Tool-Use-Id"] == "current-call"
    assert request.headers["X-Agent"] == "red"
    body = json.loads(request.content)
    assert body["base_version"] == 7 and NAMESPACE in body["content"]
    assert events.calls == [("call", "current-call"), ("result", "current-call", status == 200)]
    assert ("lineage" in result) == (status == 200)
    assert result.get("status", status) == status


@respx.mock
async def test_nested_invocation_uses_next_write_key():
    books_routes()
    respx.get("http://bf/api/playbook").respond(200, json=playbook())
    writes = respx.put("http://bf/api/playbook").respond(200, json=playbook())
    respx.post("http://bf/api/vendors").respond(201, json={"id": "v"})

    @ledger_tool("outer", "test")
    async def outer():
        await ctx.ledger().create_vendor({"name": "test"})
        return await red_tools.inspect_books()

    events = Events()
    async with LedgerClient(S, episode_id="ep", day=1) as ledger:
        tokens = ctx.bind(ledger, events, turn())
        try:
            await outer(_tool_use_id="outer-call")
        finally:
            ctx.unbind(tokens)
    assert writes.calls[0].request.headers["X-Tool-Use-Id"] == "outer-call:2"
    assert events.calls == [("call", "outer-call"), ("result", "outer-call", True)]


@pytest.mark.parametrize("lineage,stored", [(False, {}), (True, None), (True, {}), (True, fold({}, [ITEM], 0, "ep"))])
@respx.mock
async def test_no_spurious_playbook_writes(lineage, stored):
    books_routes()
    get = respx.get("http://bf/api/playbook").respond(404 if stored is None else 200, json=playbook(stored))
    put = respx.put("http://bf/api/playbook").respond(200, json={})
    async with LedgerClient(S, episode_id="ep", day=1) as ledger:
        req = turn(lineage, debrief={"items": []} if stored == {} else {"items": [ITEM]})
        tokens = ctx.bind(ledger, None, req)
        try:
            await red_tools.inspect_books()
        finally:
            ctx.unbind(tokens)
    assert get.call_count == int(lineage) and not put.called


async def test_compact_prompt_and_forced_parameters_and_plain_behavior(monkeypatch):
    agent, ledger = RedAgent(S), AsyncMock()
    ledger.get_playbook.return_value = playbook(fold({}, [ITEM], 0, "ep"))
    req = turn(scheme_id=FIRST, params={"amount": 123.45})
    tokens = ctx.bind(ledger, None, req)
    try:
        prompt = await agent.build_prompt(req)
        assert "own_playbook" in prompt and "with_debrief" in prompt and "blocked" in prompt
        assert f"MUST run scheme `{FIRST}`" in prompt and '"amount": 123.45' in prompt
        assert len(prompt) < 5000
        ledger.reset_mock()
        plain = await agent.build_prompt(turn(False, debrief={"items": [ITEM]}))
        assert "Lineage DATA" not in plain
        ledger.get_playbook.assert_not_called()
        scheme = SCHEMES[list(SCHEMES)[1]]
        ledger.list_vendors.return_value = []
        # Plain rotation is unchanged and does not use inspect_books/playbooks.
        monkeypatch.setattr(scheme, "viable", AsyncMock(return_value=False))
        assert await agent.dry_run_turn(turn(False)) == f"{scheme.id} not viable today"
    finally:
        ctx.unbind(tokens)


@respx.mock
async def test_keyless_lineage_executes_existing_scheme_with_logged_writes():
    books_routes()
    respx.get("http://bf/api/playbook").respond(200, json=playbook())
    pb = respx.put("http://bf/api/playbook").respond(200, json=playbook())
    declaration = respx.post("http://bf/api/attacks").respond(201, json={"id": "current-unscored"})
    vendor = respx.post("http://bf/api/vendors").respond(201, json={"id": "v"})
    invoice = respx.post("http://bf/api/invoices").respond(201, json={"id": "i"})
    events = Events()
    req = turn(scheme_id="ghost_vendor", params={"amount": 1234})
    async with LedgerClient(S, episode_id="ep", day=1) as ledger:
        tokens = ctx.bind(ledger, events, req)
        try:
            result = json.loads(await RedAgent(S).dry_run_turn(req))
        finally:
            ctx.unbind(tokens)
    assert result["attack_id"] == "current-unscored" and "current-unscored" not in pb.calls[0].request.content.decode()
    assert json.loads(invoice.calls[0].request.content)["amount"] == 1234
    assert len(events.calls) == 4
    key = events.calls[2][1]
    assert [r.calls[0].request.headers["X-Tool-Use-Id"] for r in (declaration, vendor, invoice)] == [key, f"{key}:2", f"{key}:3"]


@respx.mock
async def test_reflection_and_next_generation_keyless_service(monkeypatch):
    learned = fold({}, [ITEM], 0, "ep")
    req = ReflectRequest(lineage_id="ln", generation=0, episode_id="ep", review={"items": [ITEM], "score": {"secret": 100}}, playbook=Playbook(**playbook()))
    agent = RedAgent(S)
    assert (await agent.reflect(req)).playbook == learned
    assert (await agent.dry_run_reflect(req)).playbook == learned
    req.playbook.content = learned
    assert (await agent.reflect(req)).playbook is None
    assert not respx.calls  # reflect has no ledger context or network access

    books_routes()
    respx.get("http://bf/api/playbook").respond(200, json=playbook(learned))
    respx.post("http://bf/api/events").respond(201, json={})
    writes = respx.put("http://bf/api/playbook").respond(200, json={})
    chosen, threads = [], []
    service_thread = threading.get_ident()

    @ledger_tool("run_scheme", "test replacement")
    async def run(scheme_id, params_json="{}"):
        chosen.append((scheme_id, json.loads(params_json)))
        threads.append(threading.get_ident())
        return "tested"

    monkeypatch.setattr(red_tools, "run_scheme", run)
    for scheme in SCHEMES.values():
        monkeypatch.setattr(scheme, "viable", AsyncMock(return_value=True))
    app = make_agent_app(RedAgent, settings=S)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://red") as client:
        reflection = await client.post("/reflect", json=req.model_dump(), headers={"Authorization": "Bearer test-agent"})
        assert reflection.json()["ok"] and reflection.json()["playbook"] is None
        for extra in ({}, {"scheme_id": FIRST, "params": {"amount": 9}}):
            next_turn = turn(**extra).model_copy(
                update={
                    "episode_id": "ep-next",
                    "day": 0,
                    "options": {**turn(**extra).options, "lineage": {"id": "ln", "generation": 1, "playbook_version": 7}, "debrief": {"items": []}},
                }
            )
            response = await client.post("/turn", json=next_turn.model_dump(), headers={"Authorization": "Bearer test-agent"})
            assert response.status_code == 200 and response.json()["ok"]
    assert chosen[0][0] != FIRST and chosen[1] == (FIRST, {"amount": 9})
    assert all(t != service_thread for t in threads) and not writes.called
    assert agent.autonomy == "high" and agent.turn_loop_dry_run
