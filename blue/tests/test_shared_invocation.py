"""Offline API integration only: controlled registrations are not authenticated SDK proof."""

import asyncio
import inspect
import json
import sys
from contextlib import asynccontextmanager
from enum import Enum
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest

from agentkit import ctx
from agentkit.config import AgentSettings
from agentkit.events import EventEmitter
from agentkit.invocation import Invocation, bind_invocation
from audit import tools
from audit.agent import AuditAgent

from .audit_helpers import FakeLedger, bound_session, invoice, turn, vendor

SDK_ID = "toolu_sdk_style_blue_0123456789"
PRIVATE = "copied-private-marker"


class PermissionOutcome(Enum):
    PROCEED_ONCE = "proceed_once"


@pytest.fixture(autouse=True)
def permission_sdk(monkeypatch):
    # Only the permission enum is needed; never import an optional or authenticated SDK.
    monkeypatch.setitem(sys.modules, "droid_sdk", SimpleNamespace(ToolConfirmationOutcome=PermissionOutcome))


@pytest.fixture(autouse=True)
def no_external_http(monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("External HTTP is forbidden in invocation tests")

    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)


class MemoryEmitter(EventEmitter):
    """Use real event payload construction, without entering a sender or starting its pump."""

    def __init__(self, settings, timeline):
        super().__init__(settings, episode_id="ep", day=5)
        self.events = []
        self.timeline = timeline

    def emit(self, type_, payload):
        self.events.append({"type": type_, "payload": payload})
        self.timeline.append("call" if type_ == "agent.tool_call" else "result")


def suspicious_ledger():
    return FakeLedger(
        vendors=[vendor(bank_account="shared"), vendor("other", bank_account="shared")],
        invoices=[invoice("paid", invoice_number="N", status="paid", received_day=-20), invoice("duplicate", invoice_number="N")],
    )


@asynccontextmanager
async def shared_bridge(monkeypatch, responder=None):
    """Run the actual synchronous shared bridge with mocked HTTP and a turn-scoped registry."""
    settings = AgentSettings(
        AGENT_NAME="blue",
        DRY_RUN=False,
        AGENT_TOKEN="test-agent",
        INTERNAL_TOKEN="test-legacy",
        FACTORY_API_KEY="",
        BATTLEFIELD_URL="http://ledger.invalid",
        _env_file=None,
    )
    agent = AuditAgent(settings)
    timeline, requests = [], []
    emitter = MemoryEmitter(settings, timeline)

    async def send(client, request, **kwargs):
        inv = ctx.invocation()
        requests.append((request, inv, tools.INVOCATION.get()))
        timeline.append("read" if request.method == "GET" else "write")
        if responder is not None:
            response = responder(request)
            return await response if inspect.isawaitable(response) else response
        if request.method == "GET":
            assert request.url.path == "/api/vendors/v"
            body = vendor(bank_account="shared")
        else:
            body = {"ok": True, "status": "frozen"} if request.url.path.endswith("/freeze") else {"id": "receipt_1"}
        return httpx.Response(200, json=body, request=request)

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    async with bound_session(suspicious_ledger(), dry_run=False) as (session, _):
        bindings = ctx.bind(ctx.ledger(), emitter, turn())
        token = tools.INVOCATION.set(PRIVATE)
        outer = Invocation("outer-shared", "outside")
        try:
            with bind_invocation(outer):
                yield agent, session, emitter, requests, timeline
                assert ctx.invocation() is outer
                assert ctx.emitter() is emitter
                assert tools.INVOCATION.get() == PRIVATE
                assert tools.SESSION.get() is session
                assert not session.tool_lock.locked()
        finally:
            tools.INVOCATION.reset(token)
            ctx.unbind(bindings)


async def call_shared(agent, emitter, fn, kwargs, *, tool_id=SDK_ID, source="stream", approved=True):
    registry = agent._new_registry(emitter)
    registry.observe(tool_id, f"blue-ledger___{fn._rl_tool[0]}", kwargs, source)
    assert registry.require_permission and agent.identity_policy() == "strict"
    if approved:
        # Controlled approval for positive identity cases, through the actual OFF handler.
        # A stream sighting alone is insufficient; negative cases explicitly leave it unapproved.
        action = SimpleNamespace(
            confirmation_type="mcp_tool",
            server_name="blue-ledger",
            actual_tool_name=fn._rl_tool[0],
            tool_use=SimpleNamespace(id=tool_id, input=kwargs),
        )
        request = SimpleNamespace(
            actions=[action],
            options=[SimpleNamespace(value=PermissionOutcome.PROCEED_ONCE)],
            respond=lambda value: SimpleNamespace(selected_option=value),
        )
        response = await agent._permission_entry(registry, request)
        assert response.selected_option is PermissionOutcome.PROCEED_ONCE
    result = json.loads(agent._offload(fn, registry=registry)(**kwargs))
    registry.close()
    return result


@pytest.mark.parametrize("name", ["day_activity", "vendor_dedupe", "benford_check", "raise_flag", "freeze_vendor", "post_report"])
async def test_shared_bridge_exact_id_events_write_and_receipt(monkeypatch, name):
    async with shared_bridge(monkeypatch) as (agent, session, emitter, requests, timeline):
        kwargs = {}
        if name == "raise_flag":
            kwargs = {"finding_id": session.snapshot.findings[0].id}
        elif name == "freeze_vendor":
            kwargs = {"vendor_id": "v", "finding_ids": [f.id for f in session.snapshot.findings if f.vendor_id == "v"]}
        fn = getattr(tools, name)
        assert not any("invocation" in p or "tool_use_id" in p for p in inspect.signature(fn).parameters)
        output = await call_shared(agent, emitter, fn, kwargs)
        assert output.get("ok", True)
        assert emitter.events == [
            {"type": "agent.tool_call", "payload": {"tool": name, "args": kwargs, "tool_use_id": SDK_ID}},
            {"type": "agent.tool_result", "payload": {"tool_use_id": SDK_ID, "ok": True, "summary": f"{name}: completed"}},
        ]
        writing = name in {"raise_flag", "freeze_vendor", "post_report"}
        expected = ["call", "write", "result"] if writing else ["call", "result"]
        if name == "freeze_vendor":
            expected.insert(1, "read")
        assert timeline == expected
        writes = [r for r in requests if r[0].method != "GET"]
        assert len(writes) == len(session.effects) == int(writing)
        if writing:
            request, inv, private = writes[0]
            assert request.headers["X-Tool-Use-Id"] == private == inv.tool_use_id == SDK_ID
            assert request.headers["X-Agent"] == "blue"
            assert request.headers["X-Episode"] == "ep" and request.headers["X-Day"] == "5"
            assert inv.verified and inv.keys == [SDK_ID]
            assert not inv.take(name)
            effect = session.effects[0]
            assert effect.tool_use_id == SDK_ID and effect.state == "confirmed"
            assert effect.receipt_id == ("v" if name == "freeze_vendor" else "receipt_1")
    assert ctx.invocation() is None and tools.SESSION.get() is None and tools.INVOCATION.get() is None


@pytest.mark.parametrize("failure,state", [("refused", "failed"), ("server", "unknown"), ("invalid", "unknown"), ("lost", "unknown")])
async def test_shared_bridge_receipt_failure_is_not_success_or_raw_prose(monkeypatch, failure, state):
    def respond(request):
        if failure == "lost":
            raise httpx.ReadTimeout("private-provider-error", request=request)
        status = {"refused": 422, "server": 500}.get(failure, 200)
        return httpx.Response(status, json={"private-provider-prose": "not a receipt"}, request=request)

    async with shared_bridge(monkeypatch, respond) as (agent, session, emitter, requests, timeline):
        kwargs = {"finding_id": session.snapshot.findings[0].id}
        result = await call_shared(agent, emitter, tools.raise_flag, kwargs)
        assert result == {"ok": False, "state": state}
        assert len(session.effects) == len(requests) == 1
        effect = session.effects[0]
        assert effect.tool_use_id == SDK_ID and effect.state == state and effect.receipt_id is None
        assert requests[0][0].headers["X-Tool-Use-Id"] == SDK_ID
        assert emitter.events[-1]["payload"] == {"tool_use_id": SDK_ID, "ok": False, "summary": "raise_flag: not confirmed"}
        assert "private" not in json.dumps(emitter.events) + json.dumps(result) + effect.detail
        replay = await call_shared(agent, emitter, tools.raise_flag, kwargs, tool_id="toolu_second")
        assert replay == {"ok": False, "state": state, "replayed": True}
        assert len(session.effects) == len(requests) == 1
        assert timeline == ["call", "write", "result", "call", "result"]


async def test_shared_bridge_body_error_and_local_fallback_fail_closed(monkeypatch):
    async with shared_bridge(monkeypatch) as (agent, session, emitter, requests, _):
        result = await call_shared(agent, emitter, tools.raise_flag, {"finding_id": "unknown"})
        assert not result["ok"]
        assert emitter.events[-1]["payload"]["ok"] is False
        # No registered SDK sighting: strict identity refuses before the Blue body can run.
        result = json.loads(agent._offload(tools.post_report)())
        assert result == {
            "error": True,
            "identity": "unverified",
            "not_run": True,
            "tool": "post_report",
            "detail": "no verified tool_use_id for this call",
        }
        assert len(emitter.events) == 4
        local = emitter.events[-2]["payload"]["tool_use_id"]
        assert UUID(local).version == 4 and local not in {PRIVATE, SDK_ID}
        assert emitter.events[-1]["payload"] == {"tool_use_id": local, "ok": False, "summary": json.dumps(result)}
        assert "private" not in json.dumps(emitter.events) + json.dumps(result)
        assert not requests and not session.effects


async def test_unapproved_stream_registration_has_only_refusal_pairs_and_no_effects(monkeypatch):
    async with shared_bridge(monkeypatch) as (agent, session, emitter, requests, timeline):
        output = await call_shared(agent, emitter, tools.post_report, {}, approved=False)
        assert output == {
            "error": True,
            "identity": "unverified",
            "not_run": True,
            "tool": "post_report",
            "detail": "no verified tool_use_id for this call",
        }
        assert timeline == ["call", "result", "call", "result"] and len(emitter.events) == 4
        local = emitter.events[0]["payload"]["tool_use_id"]
        assert UUID(local).version == 4 and local != SDK_ID
        # D8: one pair for the refused execution and one for the registered ID that never ran.
        assert emitter.events[0] == {"type": "agent.tool_call", "payload": {"tool": "post_report", "args": {}, "tool_use_id": local}}
        assert emitter.events[1]["payload"] == {"tool_use_id": local, "ok": False, "summary": json.dumps(output)}
        assert emitter.events[2] == {"type": "agent.tool_call", "payload": {"tool": "post_report", "args": {}, "tool_use_id": SDK_ID}}
        registered = emitter.events[3]["payload"]
        assert registered["tool_use_id"] == SDK_ID and registered["ok"] is False
        assert json.loads(registered["summary"]) == {
            "error": True,
            "not_run": True,
            "tool": "post_report",
            "detail": "turn ended before the tool ran",
        }
        assert not requests and not session.effects
        assert "private" not in json.dumps(emitter.events) + json.dumps(output)


async def test_shared_bridge_deadline_keeps_unknown_receipt_and_one_failure_pair(monkeypatch):
    async def interrupted(request):
        await asyncio.Event().wait()

    async with shared_bridge(monkeypatch, interrupted) as (agent, session, emitter, requests, timeline):
        monkeypatch.setattr(agent, "_tool_budget_sec", lambda name: 0.02)
        kwargs = {"finding_id": session.snapshot.findings[0].id}
        result = await call_shared(agent, emitter, tools.raise_flag, kwargs)
        assert result["error"] is True and result["timeout"] is True
        assert len(session.effects) == len(requests) == 1
        effect = session.effects[0]
        assert effect.tool_use_id == requests[0][0].headers["X-Tool-Use-Id"] == SDK_ID
        assert effect.state == "unknown"
        assert requests[0][1].close() == (False, "raise_flag: not confirmed")
        assert timeline == ["call", "write", "result"] and len(emitter.events) == 2
        assert emitter.events[-1]["payload"]["ok"] is False
        assert "private" not in json.dumps(emitter.events)
        replay = await call_shared(agent, emitter, tools.raise_flag, kwargs, tool_id="toolu_retry")
        assert replay == {"ok": False, "state": "unknown", "replayed": True}
        assert len(requests) == len(session.effects) == 1 and len(emitter.events) == 4


@pytest.mark.parametrize("source", ["permission", "stream", "mcp_meta"])
async def test_verified_identity_is_claimed_once_and_private_context_restored(source):
    ledger = FakeLedger()
    async with bound_session(ledger, dry_run=False) as (session, emitter):
        seen = []

        @tools.blue_tool("provider_probe", "Controlled test double, not a real provider.")
        async def probe():
            seen.append((tools.INVOCATION.get(), ctx.invocation(), tools.SESSION.get()))
            return {"ok": True, "source_prose": "private-provider-response"}

        inv = Invocation(SDK_ID, "provider_probe", source=source)
        token = tools.INVOCATION.set(PRIVATE)
        outer = Invocation("outer", "outside")
        try:
            with bind_invocation(outer):
                with bind_invocation(inv):
                    assert json.loads(await probe())["ok"]
                    assert tools.INVOCATION.get() == PRIVATE and ctx.invocation() is inv
                    assert not json.loads(await probe())["ok"]
                assert ctx.invocation() is outer
            assert ctx.invocation() is None and tools.INVOCATION.get() == PRIVATE
        finally:
            tools.INVOCATION.reset(token)
        assert seen == [(SDK_ID, inv, session)]
        assert inv.close() == (True, "provider_probe: completed")
        assert not emitter.calls and not emitter.results


@pytest.mark.parametrize("kind", ["private_only", "local", "explicit", "wrong_tool", "reused"])
async def test_invalid_identity_never_reaches_provider_or_write(kind):
    ledger = FakeLedger()
    async with bound_session(ledger, dry_run=False) as (session, emitter):
        seen = []

        @tools.blue_tool("provider_probe", "Controlled provider/write probe.")
        async def probe():
            seen.append(True)
            await tools._write("report", "5", lambda key: ledger.post_report(5, "safe", tool_use_id=key))
            return {"ok": True}

        token = tools.INVOCATION.set(PRIVATE)
        try:
            if kind == "private_only":
                output = await probe()
            else:
                inv = Invocation(SDK_ID, "different" if kind == "wrong_tool" else "provider_probe", source=kind if kind in {"local", "explicit"} else "stream")
                if kind == "reused":
                    assert inv.take("provider_probe")
                with bind_invocation(inv):
                    output = await probe()
                    assert ctx.invocation() is inv
                assert inv.close() == (False, "provider_probe: not confirmed")
            assert not json.loads(output)["ok"]
            assert tools.INVOCATION.get() == PRIVATE and ctx.invocation() is None
        finally:
            tools.INVOCATION.reset(token)
        assert not seen and not ledger.writes and not session.effects
        assert not emitter.calls and not emitter.results


@pytest.mark.parametrize("extra", ["_tool_use_id", "tool_use_id", "invocation"])
async def test_metadata_is_not_accepted_as_model_arguments(extra):
    async with bound_session(FakeLedger(), dry_run=False) as (session, emitter):
        inv = Invocation(SDK_ID, "post_report", source="stream")
        with bind_invocation(inv):
            output = json.loads(await tools.post_report(**{extra: "model-supplied-id"}))
        assert not output["ok"] and not session.effects
        assert inv.close() == (False, "post_report: not confirmed")
        assert tools.INVOCATION.get() is None and not emitter.calls and not emitter.results


@pytest.mark.parametrize("mode", ["error", "cancel_write", "cancel_lock"])
async def test_shared_failure_and_cancellation_restore_context_and_retain_receipts(mode):
    ledger = FakeLedger(vendors=[vendor(created_day=5)], invoices=[invoice(amount=4920)])
    async with bound_session(ledger, dry_run=False) as (session, emitter):
        token = tools.INVOCATION.set(PRIVATE)
        inv = Invocation(SDK_ID, "raise_flag", source="stream")
        try:
            if mode == "cancel_write":
                ledger.write_failures["flag"] = "hang"
            elif mode == "cancel_lock":
                await session.tool_lock.acquire()
            with bind_invocation(inv):
                if mode == "error":
                    assert not json.loads(await tools.raise_flag("unknown"))["ok"]
                else:
                    with pytest.raises(TimeoutError):
                        async with asyncio.timeout(0.01):
                            await tools.raise_flag(session.snapshot.findings[0].id)
                assert ctx.invocation() is inv and tools.INVOCATION.get() == PRIVATE
            assert ctx.invocation() is None and tools.SESSION.get() is session
        finally:
            tools.INVOCATION.reset(token)
            if mode == "cancel_lock":
                session.tool_lock.release()
        assert not session.tool_lock.locked()
        assert inv.close() == (False, "raise_flag: not confirmed")
        assert not emitter.calls and not emitter.results
        if mode == "cancel_write":
            assert len(session.effects) == len(ledger.writes) == 1
            effect = session.effects[0]
            assert effect.tool_use_id == ledger.writes[0][2] == SDK_ID and effect.state == "unknown"
            with bind_invocation(Invocation("toolu_retry", "raise_flag", source="stream")):
                result = json.loads(await tools.raise_flag(session.snapshot.findings[0].id))
            assert result == {"ok": False, "state": "unknown", "replayed": True}
            assert len(ledger.writes) == 1
        else:
            assert not session.effects and not ledger.writes
    assert tools.INVOCATION.get() is None and tools.SESSION.get() is None


async def test_dry_dispatch_retains_uuid4_narration_receipts_and_context():
    ledger = FakeLedger(vendors=[vendor(created_day=5)], invoices=[invoice(amount=4920)])
    async with bound_session(ledger) as (session, emitter):
        token = tools.INVOCATION.set(PRIVATE)
        try:
            assert (await tools.dispatch("raise_flag", finding_id=session.snapshot.findings[0].id))["ok"]
            assert (await tools.dispatch("post_report"))["ok"]
            assert not (await tools.dispatch("raise_flag", finding_id="unknown"))["ok"]
            assert tools.INVOCATION.get() == PRIVATE and ctx.invocation() is None
        finally:
            tools.INVOCATION.reset(token)
        ids = [call[2] for call in emitter.calls]
        assert len(ids) == len(set(ids)) == 3 and all(UUID(key).version == 4 for key in ids)
        assert [result[0] for result in emitter.results] == ids
        assert [result[1] for result in emitter.results] == [True, True, False]
        assert [effect.tool_use_id for effect in session.effects] == [write[2] for write in ledger.writes] == ids[:2]
        assert all(effect.state == "confirmed" for effect in session.effects)
