"""Dormant preparation decisions; no SDK, execution, retries, or live-handler wiring."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from agentkit import LedgerClient, LedgerError
from agentkit.invocation import VERIFIED_SOURCES, ToolUse, UnverifiedInvocation
from agentkit.models import CancelCause, ControllerMode, GatedAction, Preparation, PreparationCreate, VerdictCause

# Exact current AP surface, not the full set of actions Battlefield can gate.
MUTATIONS: dict[str, tuple[GatedAction, str, tuple[str, ...]]] = {
    "match_invoice": ("invoices.match", "invoice_id", ("po_id",)),
    "approve_invoice": ("invoices.approve", "invoice_id", ()),
    "reject_invoice": ("invoices.reject", "invoice_id", ("reason",)),
    "pay_invoice": ("invoices.pay", "invoice_id", ()),
    "approve_vendor_change": ("vendor_changes.approve", "change_id", ()),
    "reject_vendor_change": ("vendor_changes.reject", "change_id", ("reason",)),
    "approve_expense": ("expenses.approve", "expense_id", ()),
    "pay_expense": ("expenses.pay", "expense_id", ()),
}


def preparation_for(tool: str, args: dict[str, Any]) -> PreparationCreate | None:
    """Validate canonical tool arguments without coercion or changing the caller's input."""
    if not isinstance(args, dict) or not isinstance(tool, str):
        raise ValueError("invalid tool arguments")
    if tool == "ap_queue" and not args:
        return None
    spec = MUTATIONS.get(tool)
    if spec is None:
        raise ValueError("unsupported tool")
    action, identity, fields = spec
    if set(args) != {identity, *fields}:
        raise ValueError("invalid tool arguments")
    if any(not isinstance(value, str) or not value.strip() for value in args.values()):
        raise ValueError("invalid tool arguments")
    return PreparationCreate(action=action, entity_id=args[identity], args={key: args[key] for key in fields})


@dataclass(frozen=True)
class PreparationDecision:
    proceed: bool
    cause: CancelCause | None = None
    reason: str = ""
    verdict_cause: VerdictCause | None = None

    @property
    def comment(self) -> str:
        """JSON cancellation comment also suitable for a tool-result summary."""
        return json.dumps({"cause": self.cause, "reason": self.reason, "verdict_cause": self.verdict_cause})


def _refuse(cause: CancelCause, reason: str) -> PreparationDecision:
    return PreparationDecision(False, cause, reason)


def _unavailable(mode: ControllerMode) -> PreparationDecision:
    if mode in ("off", "shadow"):
        return PreparationDecision(True)
    return _refuse("integration_failure", "Preparation unavailable or unusable.")


async def decide_preparation(ledger: LedgerClient, use: ToolUse, controller_mode: ControllerMode) -> PreparationDecision:
    """Prepare once, leaving all execution and enforcement to the existing Ledger routes.

    This is intentionally not installed as Green's permission handler. Shared consumption
    plumbing and authorized SDK acceptance are separate prerequisites for live execution.
    """
    if controller_mode not in ("off", "shadow", "enforce"):
        return _refuse("integration_failure", "Invalid turn mode.")
    if use.source not in VERIFIED_SOURCES or not isinstance(use.tool_use_id, str) or not use.tool_use_id.strip():
        return _refuse("integration_failure", "Verified SDK identity required.")
    try:
        request = preparation_for(use.tool, use.args)
    except ValueError:
        return _refuse("invalid_state", "Unsupported tool or invalid arguments.")
    if request is None:
        return PreparationDecision(True)
    try:
        prepared = await ledger.prepare(use, request.action, request.entity_id, request.args)
    except UnverifiedInvocation:
        return _refuse("integration_failure", "Verified SDK identity required.")
    except LedgerError as exc:
        error = exc.body.get("error") if isinstance(exc.body, dict) else None
        if exc.status in (404, 422) or (exc.status == 409 and error == "invalid_state"):
            return _refuse("invalid_state", "Preparation rejected invalid state.")
        if exc.status == 409:
            return _refuse("integration_failure", "Preparation conflict or inactive turn.")
        if exc.status in (401, 403) or (isinstance(exc.status, int) and exc.status >= 500):
            return _unavailable(controller_mode)
        return _refuse("integration_failure", "Unexpected preparation failure.")
    except (httpx.HTTPError, TimeoutError, ValueError, TypeError):
        # Never echo an HTTP body, exception, credentials, or request arguments.
        return _unavailable(controller_mode)
    if (
        not isinstance(prepared, Preparation)
        or prepared.idempotency_key != use.tool_use_id
        or prepared.action != request.action
        or prepared.entity_id != request.entity_id
        or prepared.day != ledger.day
        or prepared.controller_mode != controller_mode
        or prepared.consumed
        or prepared.effective == "pending"
        or prepared.decided_by is None
    ):
        return _unavailable(controller_mode)
    if prepared.effective == "allow":
        return PreparationDecision(True)
    cause: CancelCause = "escalation_timeout" if prepared.decided_by == "timeout" else "control_hold"
    return PreparationDecision(False, cause, prepared.reason, prepared.cause)
