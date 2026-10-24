"""Invocation identity: one tool_use_id across permission request, tool events and ledger writes.

The SDK-shaped fakes mirror droid_sdk 0.5.0's dataclasses (droid_sdk/_high_level/interactions.py:
McpToolAction, PermissionOption, PermissionRequest.respond; messages.py: ToolUseBlock) so these run
without the SDK installed (CI syncs only --extra dev). test_real_sdk_permission_request_* repeats the
core case with the real classes when droid_sdk is importable.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import sys
import time
import types
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import httpx
import pytest
import respx

from agentkit import AgentSettings, DroidAgent, LedgerClient, TurnRequest, ctx, ledger_tool
from agentkit.invocation import (
    SOURCE_PERMISSION,
    SOURCE_STREAM,
    InvocationRegistry,
    bind_registry,
    current_invocation,
    write_key,
)

S = AgentSettings(AGENT_NAME="green", BATTLEFIELD_URL="http://bf", INTERNAL_TOKEN="t")
TURN = TurnRequest(episode_id="ep_1", day=3, controller_mode="enforce")


# ---------- SDK-shaped fakes ----------
class Outcome(str, Enum):  # noqa: UP042  (same base as droid_sdk.ToolConfirmationOutcome)
    PROCEED_ONCE = "proceed_once"
    PROCEED_ALWAYS = "proceed_always"
    CANCEL = "cancel"


@dataclass(frozen=True)
class FakeToolUseBlock:
    id: str
    name: str
    input: Mapping[str, object]
    thought_signature: str | None = None


@dataclass(frozen=True)
class FakeMcpToolAction:
    tool_use: FakeToolUseBlock
    tool_name: str
    impact_level: str = "medium"
    server_name: str | None = None
    actual_tool_name: str | None = None
    confirmation_type: str = "mcp_tool"


@dataclass(frozen=True)
class FakeOption:
    label: str
    value: Outcome


@dataclass(frozen=True)
class FakeResponse:
    selected_option: Outcome
    comment: str | None = None
    edited_spec_content: str | None = None


@dataclass(frozen=True)
class FakeRequest:
    actions: tuple[Any, ...]
    options: tuple[FakeOption, ...] = (FakeOption("Proceed once", Outcome.PROCEED_ONCE), FakeOption("Cancel", Outcome.CANCEL))
    associated_session_ids: tuple[str, ...] = field(default=())

    def respond(self, selected_option: Outcome, *, comment: str | None = None, edited_spec_content: str | None = None) -> FakeResponse:
        if selected_option not in {o.value for o in self.options}:
            raise ValueError("selected_option was not offered by Droid")
        return FakeResponse(selected_option, comment, edited_spec_content)


def mcp_action(tool_use_id: str, tool: str, args: dict[str, Any], server: str = "green-ledger") -> FakeMcpToolAction:
    full = f"{server}___{tool}"
    return FakeMcpToolAction(tool_use=FakeToolUseBlock(id=tool_use_id, name=full, input=args), tool_name=full, server_name=server, actual_tool_name=tool)


# ---------- tools / agent ----------
@ledger_tool("pay_invoice", "Pay an invoice.")
async def pay_invoice(invoice_id: str, memo: str = "", amount: float = 0.0) -> str:
    return json.dumps(await ctx.ledger().pay_invoice(invoice_id))


@ledger_tool("three_writes", "Three ledger writes in one call.")
async def three_writes(vendor_id: str) -> str:
    L = ctx.ledger()
    await L.put_state("k", {"v": 1})
    await L.create_vendor({"name": vendor_id})
    await L.submit_invoice({"vendor_id": vendor_id, "amount": 1})
    return "ok"


@ledger_tool("boom", "Raises a non-ledger error.")
async def boom() -> str:
    raise RuntimeError("kaboom")


@ledger_tool("own_timeout", "The tool's own asyncio timeout fires.")
async def own_timeout() -> str:
    await asyncio.wait_for(asyncio.sleep(10), 0.01)
    return "unreachable"


@ledger_tool("narrate_then_hang", "Narrates, then hangs past the deadline.")
async def narrate_then_hang() -> str:
    ctx.emitter().custom("progress", {"step": 1})
    await asyncio.sleep(3600)
    return "unreachable"


@ledger_tool("wedge", "Blocks its thread without yielding.")
async def wedge() -> str:
    time.sleep(0.5)
    return "late"


TOOLS = [pay_invoice, three_writes, boom, own_timeout, narrate_then_hang, wedge]


class _Agent(DroidAgent):
    name = "green"
    autonomy = "off"
    verdict = "allow"
    raise_in_handler = False

    def tools(self):
        return [(f._rl_tool[0], f._rl_tool[1], f) for f in TOOLS]

    async def build_prompt(self, req):
        return ""

    async def dry_run_turn(self, req):
        return ""

    async def on_permission(self, request):
        if self.raise_in_handler:
            raise RuntimeError("blue unreachable")
        if self.verdict == "block":
            return request.respond(Outcome.CANCEL, comment="controller blocked this action")
        return request.respond(Outcome.PROCEED_ONCE)


class _Fast(_Agent):
    def _tool_timeout_sec(self) -> float:
        return 0.2


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def tool_call(self, tool, args, tool_use_id):
        self.events.append(("tool_call", tool_use_id, tool, args))

    def tool_result(self, tool_use_id, ok, summary):
        self.events.append(("tool_result", tool_use_id, ok, summary))

    def custom(self, name, payload):
        self.events.append(("custom", name, payload))

    def kinds(self) -> list[str]:
        return [e[0] for e in self.events]


def ledger_routes() -> respx.Route:
    return respx.route(host="bf").mock(return_value=httpx.Response(200, json={"id": "x"}))


def keys(route: respx.Route) -> list[str]:
    return [c.request.headers["X-Tool-Use-Id"] for c in route.calls if c.request.method != "GET"]


async def offloaded(agent: DroidAgent, fn, rec, registry=None, **kwargs) -> str:
    """Call a tool the way the SDK does: sync, on the loop, inside the turn context."""
    async with LedgerClient(agent.s, episode_id=TURN.episode_id, day=TURN.day) as ledger:
        tokens = ctx.bind(ledger, rec, TURN)  # type: ignore[arg-type]
        try:
            out = agent._offload(fn, registry=registry)(**kwargs)
        finally:
            ctx.unbind(tokens)
        await asyncio.sleep(0)
    return out


# ---------- 1. ledger writes carry the invocation id ----------
@respx.mock
async def test_direct_call_events_and_every_write_share_the_invocation_id():
    route = ledger_routes()
    rec = Recorder()
    async with LedgerClient(S, episode_id="ep_1", day=3) as ledger:
        tokens = ctx.bind(ledger, rec, TURN)  # type: ignore[arg-type]
        try:
            await three_writes(vendor_id="v1", _tool_use_id="toolu_1")
            await ledger.post_input("red", {"x": 1})  # outside any tool: a fresh UUID4
            await ledger.post_input("red", {"x": 2})
        finally:
            ctx.unbind(tokens)
    ks = keys(route)
    assert ks[:3] == ["toolu_1", "toolu_1:2", "toolu_1:3"]  # first write exact, then <id>:<n>
    assert len(set(ks)) == 5 and not any(k.startswith("toolu_1") for k in ks[3:])
    assert rec.kinds() == ["tool_call", "tool_result"]
    assert rec.events[0][1] == rec.events[1][1] == "toolu_1"


@respx.mock
async def test_explicit_tool_use_id_is_used_verbatim_and_never_reissued():
    route = ledger_routes()

    @ledger_tool("explicit_then_implicit", "x")
    async def explicit_then_implicit() -> str:
        await ctx.ledger().pay_invoice("i1", tool_use_id="toolu_9")
        await ctx.ledger().pay_invoice("i2")
        return "ok"

    async with LedgerClient(S, episode_id="ep_1", day=3) as ledger:
        tokens = ctx.bind(ledger, None, TURN)  # type: ignore[arg-type]
        try:
            await explicit_then_implicit(_tool_use_id="toolu_9")
        finally:
            ctx.unbind(tokens)
    assert keys(route) == ["toolu_9", "toolu_9:2"]
    assert write_key("toolu_9", 1) == "toolu_9" and write_key("toolu_9", 3) == "toolu_9:3"


# ---------- 2. permission -> execution -> events -> header, one id ----------
@respx.mock
async def test_permission_id_reaches_events_and_ledger_header_through_offload():
    route = ledger_routes()
    agent, rec = _Agent(S), Recorder()
    reg = agent._new_registry(rec)
    req = FakeRequest(actions=(mcp_action("toolu_A", "pay_invoice", {"invoice_id": "inv_1", "amount": 100}),))
    seen: list[str] = []

    async def mirror(request):
        seen.extend(u.tool_use_id for u in agent.tool_uses(request))  # what green's mirror keys on
        return request.respond(Outcome.PROCEED_ONCE)

    agent.on_permission = mirror  # type: ignore[method-assign]
    with bind_registry(reg):
        resp = await agent._permission_entry(reg, req)
        assert resp.selected_option is Outcome.PROCEED_ONCE
        # the SDK hands the handler validated kwargs with defaults filled and 100 coerced to 100.0
        await offloaded(agent, pay_invoice, rec, invoice_id="inv_1", memo="", amount=100.0)
    assert seen == ["toolu_A"]
    assert keys(route) == ["toolu_A"]
    assert [(e[0], e[1]) for e in rec.events] == [("tool_call", "toolu_A"), ("tool_result", "toolu_A")]
    assert rec.events[1][2] is True


@respx.mock
async def test_stream_tool_call_links_execution_when_there_is_no_permission_request():
    route = ledger_routes()
    agent, rec = _Agent(S), Recorder()
    reg = agent._new_registry(rec)
    reg.observe("toolu_S", "green-ledger___pay_invoice", {"invoice_id": "inv_2"}, SOURCE_STREAM)
    await offloaded(agent, pay_invoice, rec, registry=reg, invoice_id="inv_2", memo="", amount=0.0)
    reg.resolved("toolu_S", False, "ok")  # the stream's ToolResult afterwards
    reg.close()
    assert keys(route) == ["toolu_S"]
    assert [(e[0], e[1]) for e in rec.events] == [("tool_call", "toolu_S"), ("tool_result", "toolu_S")]


@respx.mock
async def test_unregistered_execution_gets_a_uuid_and_a_late_tool_call_is_not_left_claimable():
    route = ledger_routes()
    agent, rec = _Agent(S), Recorder()
    reg = agent._new_registry(rec)
    await offloaded(agent, pay_invoice, rec, registry=reg, invoice_id="inv_3", memo="", amount=0.0)
    (local,) = keys(route)
    assert len(local) == 32  # UUID4 hex: never a guessed id
    reg.observe("toolu_late", "green-ledger___pay_invoice", {"invoice_id": "inv_3"}, SOURCE_STREAM)
    assert reg.claim("pay_invoice", {"invoice_id": "inv_3"}) is None
    reg.resolved("toolu_late", False, "ok")
    reg.close()
    assert rec.kinds() == ["tool_call", "tool_result"]  # no phantom "never ran" pair


def test_identical_calls_are_fifo_and_a_meta_hint_wins_when_it_names_a_registered_id():
    reg = InvocationRegistry("green-ledger", [("pay_invoice", pay_invoice)])
    reg.observe("toolu_1", "green-ledger___pay_invoice", {"invoice_id": "i"}, SOURCE_PERMISSION)
    reg.observe("toolu_2", "green-ledger___pay_invoice", {"invoice_id": "i"}, SOURCE_PERMISSION)
    reg.observe("toolu_3", "pay_invoice", {"invoice_id": "j"}, SOURCE_PERMISSION)
    assert reg.claim("pay_invoice", {"invoice_id": "i"}, hints=["toolu_2", "unrelated"]).tool_use_id == "toolu_2"
    assert reg.claim("pay_invoice", {"invoice_id": "i"}, hints=["not-an-sdk-id"]).tool_use_id == "toolu_1"
    assert reg.claim("pay_invoice", {"invoice_id": "i"}) is None  # both consumed
    assert reg.claim("pay_invoice", {"invoice_id": "j", "amount": 1}) is None  # different action
    # exact names only: a suffix or another server's tool is not ours
    assert reg.observe("toolu_4", "evil___green-ledger___pay_invoice", {"invoice_id": "i"}, SOURCE_STREAM) is None
    assert reg.observe("toolu_5", "red-ledger___pay_invoice", {"invoice_id": "i"}, SOURCE_STREAM) is None


def test_mcp_request_meta_values_are_read_as_hints():
    pytest.importorskip("mcp")
    from mcp.server.lowlevel.server import request_ctx
    from mcp.shared.context import RequestContext
    from mcp.types import RequestParams

    from agentkit.droid_agent import _mcp_request_hints

    meta = RequestParams.Meta.model_validate({"progressToken": 7, "factory/toolUseId": "toolu_M", "nested": {"id": "x"}})
    token = request_ctx.set(RequestContext(request_id=1, meta=meta, session=None, lifespan_context=None))  # type: ignore[arg-type]
    try:
        hints = _mcp_request_hints("green")
    finally:
        request_ctx.reset(token)
    assert "toolu_M" in hints and "x" in hints
    assert _mcp_request_hints("green") == []  # outside an MCP request


# ---------- 3. cancellation pairs ----------
async def test_cancel_emits_exactly_one_pair_with_the_reason():
    agent, rec = _Agent(S), Recorder()
    agent.verdict = "block"
    reg = agent._new_registry(rec)
    req = FakeRequest(actions=(mcp_action("toolu_C", "pay_invoice", {"invoice_id": "inv_9"}),))
    resp = await agent._permission_entry(reg, req)
    assert resp.selected_option is Outcome.CANCEL
    await agent._permission_entry(reg, req)  # a repeated request for the same tool use
    reg.resolved("toolu_C", True, "cancelled by user")  # the stream's ToolResult
    reg.close()
    assert rec.kinds() == ["tool_call", "tool_result"]
    call, result = rec.events
    assert call[1] == result[1] == "toolu_C" and call[2] == "pay_invoice" and call[3] == {"invoice_id": "inv_9"}
    assert result[2] is False
    body = json.loads(result[3])
    assert body["cancelled"] is True and body["reason"] == "controller blocked this action"
    assert reg.claim("pay_invoice", {"invoice_id": "inv_9"}) is None  # a cancelled id is never reused


async def test_handler_exception_fails_closed_with_the_reason_and_a_pair():
    agent, rec = _Agent(S), Recorder()
    agent.raise_in_handler = True
    reg = agent._new_registry(rec)
    req = FakeRequest(actions=(mcp_action("toolu_E", "pay_invoice", {"invoice_id": "inv_1"}),))
    resp = await agent._permission_entry(reg, req)
    assert resp.selected_option is Outcome.CANCEL and "RuntimeError" in resp.comment
    assert rec.kinds() == ["tool_call", "tool_result"] and "RuntimeError" in json.loads(rec.events[1][3])["reason"]


async def test_unoffered_response_counts_as_cancel_because_the_sdk_will_cancel_it():
    agent, rec = _Agent(S), Recorder()
    reg = agent._new_registry(rec)

    async def bad(request):
        return FakeResponse(Outcome.PROCEED_ALWAYS)  # not offered: the SDK falls back to cancel

    agent.on_permission = bad  # type: ignore[method-assign]
    await agent._permission_entry(reg, FakeRequest(actions=(mcp_action("toolu_U", "pay_invoice", {"invoice_id": "i"}),)))
    assert rec.kinds() == ["tool_call", "tool_result"]


async def test_calls_that_never_run_are_closed_by_error_result_or_turn_end_but_ran_ones_are_not():
    agent, rec = _Agent(S), Recorder()
    reg = agent._new_registry(rec)
    for tid, inv in (("toolu_X", "a"), ("toolu_Y", "b"), ("toolu_Z", "c")):
        reg.observe(tid, "green-ledger___pay_invoice", {"invoice_id": inv}, SOURCE_STREAM)
    assert reg.claim("pay_invoice", {"invoice_id": "c"}).tool_use_id == "toolu_Z"
    reg.finished("toolu_Z")
    reg.resolved("toolu_X", True, "input validation error")
    reg.close()
    reg.close()
    results = {e[1]: e for e in rec.events if e[0] == "tool_result"}
    assert set(results) == {"toolu_X", "toolu_Y"}  # Z ran: _offload narrated it, not the registry
    assert all(r[2] is False and json.loads(r[3])["not_run"] for r in results.values())
    assert rec.kinds() == ["tool_call", "tool_result", "tool_call", "tool_result"]


async def test_default_on_permission_still_proceeds_once():
    pytest.importorskip("droid_sdk")
    from droid_sdk import ToolConfirmationOutcome

    class Plain(_Agent):
        on_permission = DroidAgent.on_permission

    agent, rec = Plain(S), Recorder()
    reg = agent._new_registry(rec)
    req = FakeRequest(
        actions=(mcp_action("toolu_D", "pay_invoice", {"invoice_id": "i"}),),
        options=(FakeOption("Proceed once", ToolConfirmationOutcome.PROCEED_ONCE), FakeOption("Cancel", ToolConfirmationOutcome.CANCEL)),  # type: ignore[arg-type]
    )
    resp = await agent._permission_entry(reg, req)
    assert resp.selected_option is ToolConfirmationOutcome.PROCEED_ONCE
    assert rec.events == []


async def test_real_sdk_permission_request_cancel_and_ids():
    pytest.importorskip("droid_sdk")
    from droid_sdk import ToolConfirmationOutcome
    from droid_sdk._high_level.interactions import PermissionOption, PermissionRequest
    from droid_sdk._high_level.messages import ToolUseBlock
    from droid_sdk.permissions import McpToolAction

    action = McpToolAction(
        tool_use=ToolUseBlock(id="toolu_R", name="green-ledger___pay_invoice", input={"invoice_id": "inv_1"}),
        tool_name="green-ledger___pay_invoice",
        impact_level="medium",
        server_name="green-ledger",
        actual_tool_name="pay_invoice",
    )
    req = PermissionRequest(
        actions=[action],
        options=[PermissionOption("Proceed once", ToolConfirmationOutcome.PROCEED_ONCE), PermissionOption("Cancel", ToolConfirmationOutcome.CANCEL)],
    )

    class Blocking(_Agent):
        async def on_permission(self, request):
            assert [u.tool_use_id for u in self.tool_uses(request)] == ["toolu_R"]
            return request.respond(ToolConfirmationOutcome.CANCEL, comment="controller blocked this action")

    agent, rec = Blocking(S), Recorder()
    reg = agent._new_registry(rec)
    resp = await agent._permission_entry(reg, req)
    assert resp.selected_option is ToolConfirmationOutcome.CANCEL
    assert [(e[0], e[1]) for e in rec.events] == [("tool_call", "toolu_R"), ("tool_result", "toolu_R")]
    assert rec.events[0][3] == {"invoice_id": "inv_1"}  # frozen SDK input thawed for the event


# ---------- 4. turn context reaches the worker ----------
_turn_scoped: contextvars.ContextVar[dict | None] = contextvars.ContextVar("test_turn_scoped", default=None)


@ledger_tool("read_scope", "Reads a subclass's turn-scoped ContextVar.")
async def read_scope() -> str:
    state = _turn_scoped.get()
    assert state is not None, "turn ContextVar not propagated into the worker"
    state["seen_by_tool"] = True
    return json.dumps({"label": state["label"], "invocation": current_invocation().tool_use_id})


async def test_offload_propagates_turn_contextvars_into_the_worker():
    agent, rec = _Agent(S), Recorder()
    state = {"label": "clerk-scope"}
    token = _turn_scoped.set(state)
    try:
        out = await offloaded(agent, read_scope, rec, _tool_use_id="toolu_ctx")
    finally:
        _turn_scoped.reset(token)
    assert json.loads(out) == {"label": "clerk-scope", "invocation": "toolu_ctx"}
    assert state["seen_by_tool"] is True  # same object: tool-side mutations are visible to the turn
    assert rec.events[1][2] is True


# ---------- 5. offload narration: order, exactly once, every failure closes the pair ----------
async def test_timeout_result_follows_the_call_and_the_tools_own_narration():
    agent, rec = _Fast(S), Recorder()
    out = await offloaded(agent, narrate_then_hang, rec, _tool_use_id="toolu_T")
    assert json.loads(out)["timeout"] is True
    assert rec.kinds() == ["tool_call", "custom", "tool_result"]  # ORDER, not just counts
    assert rec.events[0][1] == rec.events[2][1] == "toolu_T" and rec.events[2][2] is False


async def test_non_ledger_exception_becomes_an_error_string_and_closes_the_pair():
    agent, rec = _Agent(S), Recorder()
    out = await offloaded(agent, boom, rec)
    body = json.loads(out)
    assert body == {"error": True, "tool": "boom", "detail": "RuntimeError: kaboom"}
    assert rec.kinds() == ["tool_call", "tool_result"] and rec.events[1][2] is False
    assert rec.events[0][1] == rec.events[1][1]


async def test_direct_call_exception_still_propagates_but_closes_the_pair():
    rec = Recorder()
    async with LedgerClient(S, episode_id="ep_1", day=3) as ledger:
        tokens = ctx.bind(ledger, rec, TURN)  # type: ignore[arg-type]
        try:
            with pytest.raises(RuntimeError, match="kaboom"):
                await boom()
        finally:
            ctx.unbind(tokens)
    assert rec.kinds() == ["tool_call", "tool_result"] and rec.events[1][2] is False


async def test_a_tools_own_timeout_is_not_reported_as_the_tool_deadline():
    agent, rec = _Agent(S), Recorder()
    body = json.loads(await offloaded(agent, own_timeout, rec))
    assert "timeout" not in body and body["detail"] == "TimeoutError"
    assert rec.kinds() == ["tool_call", "tool_result"]


async def test_wedged_thread_gets_exactly_one_result_even_after_it_finishes(monkeypatch):
    import agentkit.droid_agent as da

    monkeypatch.setattr(da, "_TOOL_GRACE_SEC", 0.05)
    agent, rec = _Fast(S), Recorder()
    out = await offloaded(agent, wedge, rec)
    assert json.loads(out)["timeout"] is True
    await asyncio.sleep(0.6)  # the thread finishes and its wrapper tries to record "late"
    assert rec.kinds() == ["tool_call", "tool_result"] and rec.events[1][2] is False


# ---------- 6. startup warning, DRY_RUN unchanged ----------
def test_startup_warns_when_the_tool_cap_cannot_cover_an_escalation_hold(monkeypatch):
    import agentkit.droid_agent as da

    seen: list[tuple[str, dict]] = []
    monkeypatch.setattr(da.log, "warning", lambda ev, **kw: seen.append((ev, kw)))
    _Agent(AgentSettings(AGENT_NAME="green", TURN_TIMEOUT_SEC=100))  # cap 80 < 90 + 15
    _Agent(S)  # defaults: cap 160
    assert [ev for ev, _ in seen] == ["tool_timeout_below_escalation_hold"]
    assert seen[0][1]["tool_timeout_sec"] == 80


class _DryAgent(_Agent):
    async def dry_run_turn(self, req):
        out = await three_writes(vendor_id="v1")
        await ctx.ledger().pay_invoice("inv_direct")
        return out


@respx.mock
async def test_dry_run_turn_needs_no_sdk_and_keeps_events_paired_with_write_keys(monkeypatch):
    monkeypatch.setitem(sys.modules, "droid_sdk", None)  # any droid_sdk import now fails
    events = respx.post("http://bf/api/events").mock(return_value=httpx.Response(202, json={}))  # before the catch-all
    route = ledger_routes()
    s = AgentSettings(AGENT_NAME="green", BATTLEFIELD_URL="http://bf", INTERNAL_TOKEN="t", DRY_RUN=True)
    resp = await _DryAgent(s).run_turn(TURN)
    assert resp.ok and resp.summary == "[dry-run] ok"
    sent = [e for c in events.calls for e in json.loads(c.request.content)]
    (call,) = [e for e in sent if e["type"] == "agent.tool_call"]
    (result,) = [e for e in sent if e["type"] == "agent.tool_result"]
    tid = call["payload"]["tool_use_id"]
    assert result["payload"]["tool_use_id"] == tid and result["payload"]["ok"] is True
    ks = keys(route)
    assert ks[:3] == [tid, f"{tid}:2", f"{tid}:3"]
    assert ks[3] not in ks[:3] and not ks[3].startswith(tid)  # outside a tool: its own UUID4


# ---------- 7. the whole live path, with a scripted stand-in for droid_sdk ----------
def _install_fake_sdk(monkeypatch, script):
    """A droid_sdk stand-in that drives _droid_turn the way the real SDK does: stream ToolCall, then a
    permission request through InteractionHandlers.on_permission, then (if approved) the sync MCP
    handler with validated kwargs, then the stream ToolResult."""
    sdk, mcp = types.ModuleType("droid_sdk"), types.ModuleType("droid_sdk.mcp")

    @dataclass
    class ToolCall:
        name: str
        tool_use_id: str
        input: dict

    @dataclass
    class ToolResult:
        tool_use_id: str
        tool_name: str
        content: str
        is_error: bool

    @dataclass
    class ToolCallDelta:
        tool_use: FakeToolUseBlock

    @dataclass
    class TextDelta:
        text: str

    class ThinkingDelta(TextDelta):
        pass

    class SessionConfig:
        def __init__(self, **kw):
            self.kw = kw

    class InteractionHandlers:
        def __init__(self, on_permission=None):
            self.on_permission = on_permission

    class Session:
        def __init__(self, *, model, reasoning_effort, config, interactions, api_key):
            self.handlers = interactions
            self.tools = dict(config.kw["mcp_servers"][0]["tools"])

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def list_tools(self):
            return []

        def stream(self, prompt, *, include_partial_messages, timeout):
            return _Stream(self)

    class _Stream:
        def __init__(self, session):
            self.session = session
            self.result = types.SimpleNamespace(usage=None, success=True, text="done", subtype="success")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def __aiter__(self):
            for tool_use_id, tool, raw, validated, ask in script:
                full = f"green-ledger___{tool}"
                yield ToolCallDelta(FakeToolUseBlock(tool_use_id, full, raw))
                yield ToolCall(full, tool_use_id, raw)
                if not ask:
                    continue  # the turn ends before this one runs
                req = FakeRequest(actions=(mcp_action(tool_use_id, tool, raw),))
                resp = await self.session.handlers.on_permission(req)
                if resp.selected_option is Outcome.CANCEL:
                    yield ToolResult(tool_use_id, full, resp.comment or "cancelled", True)
                    continue
                out = self.session.tools[tool](**validated)  # sync handler, on the loop, like the SDK
                yield ToolResult(tool_use_id, full, out, False)

    sdk.ToolCall, sdk.ToolCallDelta, sdk.ToolResult, sdk.TextDelta, sdk.ThinkingDelta = ToolCall, ToolCallDelta, ToolResult, TextDelta, ThinkingDelta
    sdk.SessionConfig, sdk.InteractionHandlers, sdk.Session = SessionConfig, InteractionHandlers, Session
    sdk.ReasoningEffort = str
    sdk.Autonomy = types.SimpleNamespace(OFF="off", LOW="low", MEDIUM="medium", HIGH="high")
    mcp.tool = lambda name, description, fn: (name, fn)
    mcp.create_sdk_mcp_server = lambda name, tools, version: {"name": name, "tools": tools}
    sdk.mcp = mcp
    monkeypatch.setitem(sys.modules, "droid_sdk", sdk)
    monkeypatch.setitem(sys.modules, "droid_sdk.mcp", mcp)


class _Mirror(_Agent):
    mirrored: list[str]

    async def on_permission(self, request):
        (use,) = self.tool_uses(request)
        self.mirrored.append(use.tool_use_id)  # green: POST blue/gate with idempotency_key=use.tool_use_id
        if use.args["invoice_id"] == "inv_bad":
            return request.respond(Outcome.CANCEL, comment="controller blocked this action")
        return request.respond(Outcome.PROCEED_ONCE)


@respx.mock
async def test_live_path_one_id_from_permission_to_events_and_ledger_header(monkeypatch):
    script = [
        ("toolu_ok", "pay_invoice", {"invoice_id": "inv_ok"}, {"invoice_id": "inv_ok", "memo": "", "amount": 0.0}, True),
        ("toolu_bad", "pay_invoice", {"invoice_id": "inv_bad"}, None, True),
        ("toolu_never", "pay_invoice", {"invoice_id": "inv_never"}, None, False),
    ]
    _install_fake_sdk(monkeypatch, script)
    events = respx.post("http://bf/api/events").mock(return_value=httpx.Response(202, json={}))
    route = ledger_routes()
    agent = _Mirror(S)
    agent.mirrored = []
    resp = await agent.run_turn(TURN)
    assert resp.ok, resp.summary
    assert agent.mirrored == ["toolu_ok", "toolu_bad"]
    assert [(c.request.url.path, c.request.headers["X-Tool-Use-Id"]) for c in route.calls] == [("/api/invoices/inv_ok/pay", "toolu_ok")]
    sent = [e for c in events.calls for e in json.loads(c.request.content) if e["type"].startswith("agent.tool")]
    assert [(e["type"], e["payload"]["tool_use_id"]) for e in sent] == [
        ("agent.tool_call", "toolu_ok"),
        ("agent.tool_result", "toolu_ok"),
        ("agent.tool_call", "toolu_bad"),
        ("agent.tool_result", "toolu_bad"),
        ("agent.tool_call", "toolu_never"),
        ("agent.tool_result", "toolu_never"),
    ]
    oks = [e["payload"]["ok"] for e in sent if e["type"] == "agent.tool_result"]
    assert oks == [True, False, False]
    assert json.loads(sent[3]["payload"]["summary"])["reason"] == "controller blocked this action"


@respx.mock
async def test_real_sdk_tool_handler_links_to_the_permission_id_after_sdk_validation():
    pytest.importorskip("droid_sdk.mcp")
    route = ledger_routes()
    agent, rec = _Agent(S), Recorder()
    reg = agent._new_registry(rec)
    raw = {"invoice_id": "inv_1", "amount": 100}  # what the model sent; the SDK coerces and fills defaults
    await agent._permission_entry(reg, FakeRequest(actions=(mcp_action("toolu_V", "pay_invoice", raw),)))
    server = agent._mcp_server(reg)
    handler = next(t.handler for t in server.tools if t.name == "pay_invoice")  # droid_sdk.mcp.tool's invoke
    async with LedgerClient(S, episode_id=TURN.episode_id, day=TURN.day) as ledger:
        tokens = ctx.bind(ledger, rec, TURN)  # type: ignore[arg-type]
        try:
            await handler(raw)
        finally:
            ctx.unbind(tokens)
    assert keys(route) == ["toolu_V"]
    assert [(e[0], e[1]) for e in rec.events] == [("tool_call", "toolu_V"), ("tool_result", "toolu_V")]
