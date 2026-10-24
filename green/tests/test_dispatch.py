"""Unsupported clerk operations fail before any ledger access, including reads."""

import json
from unittest.mock import Mock

import pytest
from conftest import change, expense, tool_turn
from workflow import ClerkFailure, operation

from agentkit import ctx
from agentkit.tools import ledger_tool


@pytest.mark.parametrize(
    ("action", "kind"),
    [
        ("pay", "vendor_change"),
        ("match", "vendor_change"),
        ("reject", "expense"),
        ("match", "expense"),
        ("private-unknown-action", "vendor_change"),
        ("approve", "private-unknown-kind"),
    ],
)
async def test_unsupported_dispatch_holds_entity_without_ledger_io(book, action, kind):
    row = change("entity")
    row["status"] = "approved" if action == "pay" else "pending"
    book.add("vendor_changes", row)
    book.add("expenses", expense("entity"))
    async with tool_turn() as clerk:
        with pytest.raises(ClerkFailure) as caught:
            await operation(action, kind, "entity")
        assert caught.value.status is None
        assert caught.value.body == "unsupported_operation: no mutation sent"
        assert clerk.failures == {(kind, "entity")}
        assert not clerk.blocked
        assert not clerk.attempted
        assert not clerk.confirmed
        assert "blocked 0, deferred 0, failures 1, unknown 0" in clerk.summary()
        # Neither a duplicate nor a different operation may proceed for this held key.
        for follow_on in (action, "approve"):
            result = json.loads(await operation(follow_on, kind, "entity"))
            assert result["outcome"] == "deferred"
        assert "failures 1" in clerk.summary()
    assert book.calls == []
    assert book.writes == []


async def test_shared_wrapper_returns_sanitized_error_and_paired_failure_events(book, monkeypatch):
    emitter = Mock()
    monkeypatch.setattr(ctx, "emitter", lambda: emitter)

    @ledger_tool("unsupported_dispatch", "Exercise dispatch validation without SDK execution.")
    async def unsupported_dispatch() -> str:
        return await operation("private-unknown-action", "vendor_change", "entity")

    async with tool_turn() as clerk:
        result = await unsupported_dispatch()
        assert json.loads(result) == {
            "error": True,
            "status": None,
            "detail": "unsupported_operation: no mutation sent",
        }
        assert clerk.failures == {("vendor_change", "entity")}
        assert not clerk.blocked
    emitter.tool_call.assert_called_once()
    name, args, event_id = emitter.tool_call.call_args.args
    assert name == "unsupported_dispatch" and args == {} and event_id
    emitter.tool_result.assert_called_once_with(event_id, False, result)
    assert book.calls == []
    assert book.writes == []
