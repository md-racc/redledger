"""Controlled shared narration and D14 qualification: no SDK, provider, or outbound HTTP."""

import asyncio
import inspect
import json
import threading
from uuid import UUID

import httpx
import pytest
from server import extra

from agentkit import ctx, make_agent_app
from agentkit.ledger_client import LedgerError
from agentkit.sync import TurnLock, run_on_turn_loop
from agentkit.tools import ledger_tool, redacted_args
from audit import tools

from . import test_server
from .audit_helpers import FakeLedger, bound_session, invoice, turn, vendor
from .test_shared_invocation import call_shared, shared_bridge


@pytest.fixture(autouse=True)
def no_external_http(monkeypatch):
    send = httpx.AsyncClient.send

    async def forbidden(client, *args, **kwargs):
        if isinstance(client._transport, httpx.ASGITransport):
            return await send(client, *args, **kwargs)
        raise AssertionError("External HTTP is forbidden in adapter tests")

    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)


async def wait_until(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0.001)


@pytest.mark.parametrize("failure", [False, True])
async def test_dry_pair_delegates_to_shared_decorator_and_sanitizes_errors(monkeypatch, failure):
    decorated = []

    def shared_decorator(name, description, *, redact):
        decorated.append((name, redact))
        return ledger_tool(name, description, redact=redact)

    monkeypatch.setattr(tools, "ledger_tool", shared_decorator)

    @tools.blue_tool("probe", "Offline test double.")
    async def probe(finding_id: str):
        if failure:
            raise RuntimeError("private provider prose and credentials")
        return {"ok": True, "count": 1}

    async with bound_session(FakeLedger()) as (_, emitter):
        token = tools.INVOCATION.set("deterministic-id")
        try:
            result = json.loads(await probe("id"))
        finally:
            tools.INVOCATION.reset(token)
        assert result["ok"] is not failure
        assert emitter.calls == [("probe", {}, "deterministic-id")]
        assert len(emitter.results) == 1
        assert emitter.results[0][:2] == ("deterministic-id", not failure)
        assert "private" not in json.dumps(emitter.results) + json.dumps(result)
        assert ctx.invocation() is None
    assert decorated == [("probe", probe._rl_redact)]


@pytest.mark.parametrize("extra", ["_tool_use_id", "tool_use_id", "invocation"])
async def test_dry_metadata_cannot_replace_private_id_or_authorize_writes(extra):
    async with bound_session(FakeLedger()) as (session, emitter):
        result = await tools.dispatch("post_report", **{extra: "model-supplied-id"})
        assert result["ok"] is False and not session.effects
        assert not emitter.calls and not emitter.results
        assert ctx.invocation() is None and tools.INVOCATION.get() is None


async def test_shared_redactor_covers_execution_and_refused_registration(monkeypatch):
    async with shared_bridge(monkeypatch) as (agent, session, emitter, requests, _):
        args = {"finding_id": "private provider prose", "finding_ids": ["safe", {"private": "value"}], "reason": {"private": "value"}}
        safe = {"finding_ids": ["safe"]}
        for _, _, fn in agent.tools():
            assert redacted_args(fn, args) == safe
        assert not call_shared(agent, emitter, tools.raise_flag, {"finding_id": args["finding_id"]})["ok"]
        assert emitter.events[0]["payload"]["args"] == {}
        registry = agent._new_registry(emitter)
        use = registry.observe("refused-id", "blue-ledger___raise_flag", args, "stream")
        registry.cancelled(use.tool_use_id, "Controlled refusal")
        registry.close()
        assert emitter.events[-2]["payload"]["args"] == safe
        assert len(emitter.events) == 4 and not requests and not session.effects
        assert "private" not in json.dumps(emitter.events)


def test_exact_seven_tools_and_argument_schemas_are_unchanged(runtime):
    agent, _, _ = runtime()
    expected = {
        "day_activity": {},
        "vendor_dedupe": {},
        "benford_check": {},
        "crs_identity_check": {},
        "raise_flag": {"finding_id": "str"},
        "freeze_vendor": {"vendor_id": "str", "finding_ids": "list[str]"},
        "post_report": {},
    }
    assert {name for name, _, _ in agent.tools()} == expected.keys()
    for name, _, fn in agent.tools():
        sig = inspect.signature(fn)
        assert {p: value.annotation for p, value in sig.parameters.items()} == expected[name]
        assert all(p.default is inspect.Parameter.empty for p in sig.parameters.values())
        assert sig.return_annotation is str


@pytest.mark.parametrize("cancel", [False, True])
async def test_service_owned_tool_lock_contends_on_worker_loop_and_restores_context(cancel):
    ledger = FakeLedger()
    async with bound_session(ledger) as (session, emitter):
        assert isinstance(session.tool_lock, TurnLock)
        await session.tool_lock.acquire()
        task = asyncio.create_task(run_on_turn_loop(lambda: tools.dispatch("post_report"), name="blue-lock-test", ceiling_sec=2))
        try:
            await wait_until(lambda: emitter.calls)
            assert not ledger.writes and not session.effects
            if cancel:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(task, 3)
                assert not ledger.writes
            else:
                session.tool_lock.release()
                assert (await asyncio.wait_for(task, 3))["ok"]
                assert session.effects[0].tool_use_id == ledger.writes[0][2] == emitter.calls[0][2]
                assert UUID(emitter.calls[0][2]).version == 4
            assert len(emitter.calls) == len(emitter.results) == 1
            assert emitter.results[0][1] is not cancel
            assert tools.SESSION.get() is session and tools.INVOCATION.get() is None and ctx.invocation() is None
        finally:
            if session.tool_lock.locked():
                session.tool_lock.release()
            if not task.done():
                task.cancel()
            await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 3)
        assert not session.tool_lock.locked()


@pytest.mark.parametrize("first,second", [("/audit", "/turn"), ("/turn", "/audit"), ("/audit", "/audit")])
async def test_dry_turn_loop_preserves_real_overlap_and_gate_assertions(runtime, gate_request, monkeypatch, first, second):
    prototype, ledger, emitter = runtime()
    app = make_agent_app(type(prototype), settings=prototype.s, extra_routes=extra)
    agent = app.state.agent
    agent.turn_loop_dry_run = True  # Per-instance opt-in; no shared default or live guard change.
    service_thread = threading.get_ident()
    worker_threads = []
    prepare = agent._prepare

    async def observed(req):
        worker_threads.append(threading.get_ident())
        return await prepare(req)

    monkeypatch.setattr(agent, "_prepare", observed)
    assert isinstance(agent.audit_lock, TurnLock)
    await test_server.test_audit_turn_overlap_409_gate_stays_responsive((app, agent, ledger, emitter), gate_request, first, second)
    assert worker_threads and all(t != service_thread for t in worker_threads)
    assert agent.outcome("ep", 5).report_posted
    assert ledger.read_active == 0
    assert tools.SESSION.get() is None and tools.INVOCATION.get() is None and ctx.invocation() is None


@pytest.mark.parametrize("failure", [None, LedgerError(503, "private provider prose")])
async def test_canned_turn_loop_replay_cross_day_receipts_and_private_events(runtime, failure):
    ledger = FakeLedger(vendors=[vendor(created_day=5)], invoices=[invoice(amount=4920)])
    if failure:
        ledger.write_failures["flag"] = failure
    agent, _, emitter = runtime(ledger)
    agent.turn_loop_dry_run = True
    first = await asyncio.wait_for(agent.run_turn(turn()), 3)
    count = len(ledger.writes)
    assert await asyncio.wait_for(agent.run_turn(turn()), 3) == first
    assert len(ledger.writes) == count
    await asyncio.wait_for(agent.run_turn(turn(day=6)), 3)
    assert [kind for kind, _, _ in ledger.writes].count("flag") == 1
    assert agent.receipts[("ep", 5)][0].state == ("unknown" if failure else "confirmed")
    assert agent.outcome("ep", 5).report_posted
    assert first.ok is (failure is None)
    assert len(emitter.calls) == len(emitter.results)
    ids = [call[2] for call in emitter.calls]
    assert len(ids) == len(set(ids)) and all(UUID(key).version == 4 for key in ids)
    assert [result[0] for result in emitter.results] == ids
    assert all(key in ids for _, _, key in ledger.writes)
    assert "private" not in json.dumps(emitter.calls + emitter.results + emitter.thoughts)
    assert tools.SESSION.get() is None and ctx.invocation() is None and not agent.audit_lock.locked()


@pytest.mark.parametrize("during_write", [False, True])
async def test_canned_turn_loop_cancellation_is_bounded_and_retains_unknown(runtime, during_write):
    ledger = FakeLedger(vendors=[vendor(created_day=5)], invoices=[invoice(amount=4920)])
    if during_write:
        ledger.write_failures["flag"] = "hang"
    else:
        ledger.read_block = threading.Event()
    agent, _, emitter = runtime(ledger)
    agent.turn_loop_dry_run = True
    task = asyncio.create_task(agent.run_turn(turn()))
    try:
        await wait_until(lambda: ledger.writes if during_write else ledger.read_active)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 3)
        assert ledger.read_active == 0 and not agent.audit_lock.locked()
        assert len(emitter.calls) == len(emitter.results)
        if during_write:
            assert agent.receipts[("ep", 5)][0].state == "unknown"
            assert agent.outcome("ep", 5).report_posted
            assert [kind for kind, _, _ in ledger.writes] == ["flag", "report"]
        else:
            assert not ledger.writes and not agent.outcome("ep", 5).report_posted
        assert tools.SESSION.get() is None and tools.INVOCATION.get() is None and ctx.invocation() is None
    finally:
        if ledger.read_block is not None:
            ledger.read_block.set()
        if not task.done():
            task.cancel()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 3)
