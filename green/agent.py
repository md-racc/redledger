"""Trusting AP clerk; live execution awaits the shared invocation/gate protocol."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from preparation import PreparationDecision, decide_preparation, preparation_for
from workflow import Key, clerk_scope, run_clerk, state

import tools as green_tools
from agentkit import DroidAgent, EventEmitter, TurnRequest, TurnResponse, collect_tools, ctx
from agentkit.invocation import VERIFIED_SOURCES, ToolUse, current_registry
from agentkit.models import Usage
from agentkit.tools import ToolFn

PREREQUISITE = (
    "Green live integration prerequisite: merged shared preflight protocol, verified "
    "invocation identity and exact tool restrictions are required before Droid execution."
)


def permission_key(use: ToolUse) -> Key | None:
    try:
        mapped = preparation_for(use.tool, use.args)
    except ValueError:
        return None
    if mapped is None or mapped.entity_id is None:
        return None
    kind = {"invoices": "invoice", "expenses": "expense", "vendor_changes": "vendor_change"}[mapped.action.split(".")[0]]
    return kind, mapped.entity_id


class GreenAgent(DroidAgent):
    name = "green"
    autonomy = "off"  # Do not change without an SDK experiment and shared integration.
    system_prompt = (Path(__file__).parent / "prompts" / "system.md").read_text()

    async def health(self) -> dict[str, Any]:
        if self.s.dry_run:
            # SDK availability is neither probed nor required by the keyless clerk.
            return {"ok": True, "agent": self.name, "model": self.s.droid_model, "droid_ok": False, "dry_run": True}
        return await super().health()

    def tools(self) -> list[tuple[str, str, ToolFn]]:
        return collect_tools(green_tools)

    async def build_prompt(self, req: TurnRequest) -> str:
        return f"Day {req.day}. Follow the AP procedure in your system prompt. Start with ap_queue."

    async def run_turn(self, req: TurnRequest) -> TurnResponse:
        with clerk_scope():
            return await super().run_turn(req)

    async def _droid_turn(self, req: TurnRequest, emitter: EventEmitter) -> tuple[str, Usage | None]:
        # Guard before the base class imports the SDK, constructs a server or opens a Session.
        raise RuntimeError(PREREQUISITE)

    async def on_permission(self, request: Any) -> Any:
        from droid_sdk import ToolConfirmationOutcome

        decision = PreparationDecision(False, "integration_failure", "Permission context unavailable or invalid.")
        clerk, keys = None, []
        try:
            if current_registry() is None:
                return request.respond(ToolConfirmationOutcome.CANCEL, comment=decision.comment)
            uses = self.tool_uses(request)
            keys = [key for use in uses if (key := permission_key(use)) is not None]
            clerk = state()
            if len(uses) > 1 or len(getattr(request, "actions", ()) or ()) > 1:
                # One SDK response selects the whole batch; never prepare a partial batch.
                decision = PreparationDecision(False, "integration_failure", "Submit separate tool requests; batched permissions are unsupported.")
            elif len(uses) == 1:
                use = uses[0]
                if use.source not in VERIFIED_SOURCES or not isinstance(use.tool_use_id, str) or not use.tool_use_id.strip():
                    decision = PreparationDecision(False, "integration_failure", "Verified SDK identity required.")
                else:
                    held = clerk.held_decision(keys[0]) if keys else None
                    decision = held or await decide_preparation(ctx.ledger(), use, ctx.turn().controller_mode)
        except Exception:
            # Cancellation (BaseException) propagates. Never expose exception/body/argument text.
            decision = PreparationDecision(False, "integration_failure", "Permission context unavailable or invalid.")
        if not decision.proceed and clerk is not None:
            for key in keys:
                clerk.cancel(key, decision)
        outcome = ToolConfirmationOutcome.PROCEED_ONCE if decision.proceed else ToolConfirmationOutcome.CANCEL
        return request.respond(outcome, comment=decision.comment if not decision.proceed else "")

    async def dry_run_turn(self, req: TurnRequest) -> str:
        with clerk_scope(reuse=True):
            return await run_clerk(green_tools)
