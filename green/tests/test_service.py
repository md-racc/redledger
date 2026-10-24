"""HTTP acceptance of the staged keyless clerk, not Blue/SDK integration."""

import asyncio
import builtins
import json

import httpx
import pytest
import respx
from conftest import change, expense, invoice
from workflow import state

from agent import GreenAgent
from agentkit import AgentSettings, DroidAgent, ctx
from agentkit.server import make_agent_app

TURN = {"episode_id": "ep", "day": 3, "controller_mode": "enforce", "options": {}}


@pytest.fixture
async def service(monkeypatch):
    for key in ("FACTORY_API_KEY", "DROID_MODEL", "DROID_REASONING"):
        monkeypatch.delenv(key, raising=False)
    attempts = []
    original_import, original_probe = builtins.__import__, GreenAgent._droid_available

    def tracked_import(name, *args, **kwargs):
        if name == "droid_sdk" or name.startswith("droid_sdk."):
            attempts.append(name)
            raise ImportError("SDK forbidden in keyless acceptance")
        return original_import(name, *args, **kwargs)

    def tracked_probe():
        attempts.append("availability probe")
        return original_probe()

    monkeypatch.setattr(builtins, "__import__", tracked_import)
    monkeypatch.setattr(GreenAgent, "_droid_available", staticmethod(tracked_probe))
    settings = AgentSettings(
        _env_file=None,
        AGENT_NAME="green",
        AGENT_TOKEN="test-agent",
        INTERNAL_TOKEN="test-legacy",
        BATTLEFIELD_URL="http://bf",
        DRY_RUN=True,
        FACTORY_API_KEY=None,
        DROID_MODEL=None,
        DROID_REASONING=None,
        TURN_TIMEOUT_SEC=180,
        HTTP_TIMEOUT_SEC=15,
    )
    app = make_agent_app(GreenAgent, settings=settings)
    assert isinstance(app.state.agent, GreenAgent)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://green") as client:
        yield client
    # The base probe catches import exceptions: checking only a raised hook assertion is insufficient.
    assert attempts == [], f"DRY_RUN inspected the SDK: {attempts}"


def clean_context():
    with pytest.raises(RuntimeError, match="turn-local"):
        state()
    with pytest.raises(AssertionError):
        ctx.ledger()
    with pytest.raises(AssertionError):
        ctx.turn()
    assert ctx.emitter() is None


async def turn(service, **overrides):
    response = await service.post("/turn", json=TURN | overrides, headers={"Authorization": "Bearer test-agent"})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"ok", "summary", "duration_sec", "usage"}
    assert body["ok"] is True and body["usage"] is None
    assert isinstance(body["duration_sec"], (int, float)) and body["duration_sec"] >= 0
    assert body["summary"].startswith("[dry-run] confirmed ")
    clean_context()
    return body["summary"]


def narration(book):
    assert {e["type"] for e in book.events} == {"agent.thinking", "agent.tool_call", "agent.tool_result"}
    calls = [e["payload"] for e in book.events if e["type"] == "agent.tool_call"]
    results = [e["payload"] for e in book.events if e["type"] == "agent.tool_result"]
    ids = [e["tool_use_id"] for e in calls]
    assert ids == [e["tool_use_id"] for e in results]
    assert len(ids) == len(set(ids))
    serialized = json.dumps(book.events)
    for private in ("test-agent", "test-legacy", "test-operator", "private-bank-value", "private-account", "private-fault"):
        assert private not in serialized
    return calls, results


def ledger_headers(start=0, *, episode="ep", day=3):
    calls = list(respx.calls)[start:]
    assert calls
    write_ids = []
    for call in calls:
        req = call.request
        assert req.url.host == "bf" and req.url.path.startswith("/api/")
        assert req.headers["Authorization"] == "Bearer test-agent"
        assert req.headers["X-Agent"] == "green"
        assert req.headers["X-Episode"] == episode and req.headers["X-Day"] == str(day)
        if req.method != "GET":
            write_ids.append(req.headers["X-Tool-Use-Id"])
        if req.url.path == "/api/events":
            assert req.method == "POST"
    assert all(write_ids) and len(write_ids) == len(set(write_ids))


async def test_public_keyless_health(service, book):
    response = await service.get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "agent": "green", "model": None, "droid_ok": False, "dry_run": True}
    assert not book.calls and not respx.calls


async def test_live_health_still_delegates_to_shared_base(monkeypatch):
    sentinel = {"shared": "health"}

    async def shared_health(self):
        return sentinel

    monkeypatch.setattr(DroidAgent, "health", shared_health)
    agent = GreenAgent(AgentSettings.model_construct(agent_name="green", dry_run=False))
    assert await agent.health() is sentinel


@pytest.mark.parametrize("token", [None, "wrong", "test-operator", "test-legacy"])
async def test_turn_rejects_non_agent_tokens_without_ledger_io(service, book, token):
    headers = {} if token is None else {"Authorization": f"Bearer {token}"}
    response = await service.post("/turn", json=TURN, headers=headers)
    assert response.status_code == 401
    assert not book.calls and not respx.calls
    clean_context()


async def test_invalid_controller_mode_never_starts_clerk(service, book):
    response = await service.post("/turn", json=TURN | {"controller_mode": "invalid"}, headers={"Authorization": "Bearer test-agent"})
    assert response.status_code == 422
    assert not book.calls and not respx.calls


@pytest.mark.parametrize("mode", ["off", "shadow", "enforce"])
async def test_http_ap_procedure_and_backlogs(service, book, mode):
    # Modes are accepted against mocked Ledger responses; this does not exercise Blue's gate.
    book.add("vendor_changes", change("c"))
    book.add("purchase_orders", {"id": "po", "vendor_id": "v", "amount": "1200", "created_day": 1, "status": "open"})
    book.add("invoices", invoice("po", po_id="po"), invoice("limit", amount="5000.00"), invoice("above", amount="5000.01"))
    book.add("expenses", expense("new", amount="9000.01"), expense("backlog", status="approved", amount="7000.02"))
    summary = await turn(service, controller_mode=mode)
    assert summary == (
        "[dry-run] confirmed vendor_change.approve 1, invoice.match 1, invoice.approve 1, invoice.pay 2, "
        "expense.approve 1, expense.pay 2; paid $22200.03; blocked 0, deferred 1, failures 0, unknown 0"
    )
    assert book.writes == [
        "vendor_changes/c/approve",
        "invoices/limit/approve",
        "invoices/po/match",
        "invoices/limit/pay",
        "invoices/po/pay",
        "expenses/new/approve",
        "expenses/backlog/pay",
        "expenses/new/pay",
    ]
    assert book.rows["invoices"]["above"]["status"] == "pending"
    assert book.rows["vendor_changes"]["c"]["status"] == "approved"
    assert len(book.rows["payments"]) == 4
    assert all(book.rows["invoices"][i]["status"] == "paid" for i in ("limit", "po"))
    assert all(row["status"] == "paid" for row in book.rows["expenses"].values())
    calls, results = narration(book)
    assert len(calls) == len(book.writes) + 4  # Three queues plus the above-limit hold.
    assert all(e["ok"] for e in results)
    ledger_headers()


@pytest.mark.parametrize(
    "fault,category",
    [
        (httpx.Response(403, json={"verdict": "block", "reason": "private-fault", "verdict_id": "vd"}), "blocked 1, deferred 0, failures 0, unknown 0"),
        (httpx.Response(401, json={"detail": "private-fault"}), "blocked 0, deferred 0, failures 1, unknown 0"),
        (httpx.Response(403, json={"detail": "private-fault"}), "blocked 0, deferred 0, failures 1, unknown 0"),
        (httpx.Response(409, json={"detail": "private-fault"}), "blocked 0, deferred 1, failures 0, unknown 0"),
        (httpx.ReadTimeout("private-fault"), "blocked 0, deferred 0, failures 0, unknown 1"),
    ],
    ids=["controller-block", "ledger-auth", "ledger-forbidden", "stale-conflict", "unknown-write"],
)
async def test_http_item_failure_categories_and_next_request_recovery(service, book, fault, category):
    book.add("invoices", invoice("held"), invoice("good", status="approved", amount="300.00"))
    path = "invoices/held/approve"
    book.faults["POST", path] = fault
    summary = await turn(service)
    assert category in summary and "paid $300.00" in summary
    assert book.writes == [path, "invoices/good/pay"]
    _, results = narration(book)
    failed = [e for e in results if not e["ok"]]
    assert len(failed) == 1
    detail = json.loads(failed[0]["summary"])
    assert bool(detail.get("blocked")) == ("blocked 1" in category)
    if "blocked" not in detail:
        assert detail["status"] == (None if isinstance(fault, Exception) else fault.status_code)
    del book.faults["POST", path]
    summary = await turn(service)
    assert "invoice.approve 1, invoice.pay 1" in summary and "paid $1200.00" in summary
    assert "blocked 0, deferred 0, failures 0, unknown 0" in summary
    assert book.writes == [path, "invoices/good/pay", path, "invoices/held/pay"]
    assert len(book.rows["payments"]) == 2
    narration(book)
    ledger_headers()


@pytest.mark.parametrize("action", ["approve", "pay"])
async def test_http_lost_commit_response_reconciles_and_next_turn_does_not_repay(service, book, action):
    book.add("invoices", invoice("i", status="pending" if action == "approve" else "approved"))
    path = f"invoices/i/{action}"
    book.faults["POST", path] = (httpx.ReadTimeout("private-fault"),)
    summary = await turn(service)
    assert f"invoice.{action} 1" in summary and "unknown 0" in summary
    assert book.writes == [path]
    if action == "approve":
        assert "invoice.pay 0" in summary and "deferred 1" in summary
        assert not book.rows["payments"]
    else:
        assert "paid $1200.00" in summary and len(book.rows["payments"]) == 1
    del book.faults["POST", path]
    summary = await turn(service)
    assert f"invoice.pay {int(action == 'approve')}" in summary
    assert book.writes == ([path, "invoices/i/pay"] if action == "approve" else [path])
    assert "paid $0.00" in await turn(service)
    assert len(book.rows["payments"]) == 1 and book.writes.count("invoices/i/pay") == 1
    _, results = narration(book)
    assert sum(not e["ok"] for e in results) == 1
    ledger_headers()


async def test_http_reply_waits_for_complete_multi_batch_narration(service, book):
    ids = [f"i{i:02}" for i in range(12)]
    book.add("invoices", *(invoice(i, amount="100.00") for i in ids))
    summary = await turn(service)
    assert "invoice.approve 12, invoice.pay 12" in summary and "paid $1200.00" in summary
    assert book.writes == [f"invoices/{i}/{action}" for action in ("approve", "pay") for i in ids]
    assert len(book.rows["payments"]) == 12
    calls, results = narration(book)
    assert len(calls) == len(results) == 27 and all(e["ok"] for e in results)
    assert len(book.events) == 55  # More than EventEmitter's 50-event batch, already received at HTTP return.
    assert sum(c.request.url.path == "/api/events" for c in respx.calls) >= 2
    ledger_headers()


async def test_sequential_episode_context_isolation(service, book):
    summaries = []
    for episode, day in (("first", 1), ("second", 7)):
        start, event_start = len(respx.calls), len(book.events)
        summaries.append(await turn(service, episode_id=episode, day=day))
        ledger_headers(start, episode=episode, day=day)
        assert len(book.events) - event_start == 7  # Thinking plus three empty-queue event pairs.
        assert not book.writes
    assert summaries[0] == summaries[1] and "paid $0.00" in summaries[1]
    narration(book)


async def test_overlapping_http_turn_is_rejected_without_starting_another_clerk(service, book):
    entered, release = asyncio.Event(), asyncio.Event()

    async def paused_read(request):
        if request.method == "GET" and request.url.path == "/api/vendor_changes":
            entered.set()
            await release.wait()
        return book.respond(request)

    # Replace the fixture's broad BF handler rather than registering a shadowed later route.
    respx.routes[0].mock(side_effect=paused_read)
    task = asyncio.create_task(turn(service))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        before = len(respx.calls)
        response = await service.post("/turn", json=TURN, headers={"Authorization": "Bearer test-agent"})
        assert response.status_code == 409 and response.json() == {"detail": "turn already in progress"}
        assert len(respx.calls) == before and not book.writes
    finally:
        release.set()
        await task
    clean_context()
    assert len(narration(book)[0]) == 3
