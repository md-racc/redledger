"""Trusting AP clerk; live execution is enabled following Green SDK acceptance (issue #78)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog
from playbook import playbook_prompt_section, reflect_playbook
from preparation import PreparationDecision, decide_preparation, preparation_for
from workflow import Key, clerk_scope, run_clerk, state

import tools as green_tools
from agentkit import AgentSettings, DroidAgent, EventEmitter, TurnRequest, TurnResponse, collect_tools, ctx
from agentkit.invocation import VERIFIED_SOURCES, ToolUse, current_registry
from agentkit.models import ReflectRequest, ReflectResponse, Usage
from agentkit.tools import ToolFn

# Observed on canonical #94 with SDK 0.5.0 / MCP 1.30.0; contracts Finding #96.
log = structlog.get_logger(__name__)

AP_TOOL_IDS = (
    "green-ledger___ap_queue",
    "green-ledger___approve_expense",
    "green-ledger___approve_invoice",
    "green-ledger___approve_vendor_change",
    "green-ledger___match_invoice",
    "green-ledger___pay_expense",
    "green-ledger___pay_invoice",
    "green-ledger___reject_invoice",
    "green-ledger___reject_vendor_change",
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
    identity = "strict"
    turn_loop_dry_run = True
    system_prompt = (Path(__file__).parent / "prompts" / "system.md").read_text()

    def __init__(self, settings: AgentSettings):
        super().__init__(settings)
        self._tool_ids = list(AP_TOOL_IDS)  # Restrict the first Session, before list_tools.

    def _expected_tool_ids(self) -> list[str]:
        return list(AP_TOOL_IDS)

    async def health(self) -> dict[str, Any]:
        if self.s.dry_run:
            # SDK availability is neither probed nor required by the keyless clerk.
            return {"ok": True, "agent": self.name, "model": self.s.droid_model, "droid_ok": False, "dry_run": True}
        return await super().health()

    def tools(self) -> list[tuple[str, str, ToolFn]]:
        return collect_tools(green_tools)

    async def build_prompt(self, req: TurnRequest) -> str:
        prompt = f"Day {req.day}. Follow the AP procedure in your system prompt. Start with ap_queue."
        lineage = req.options.get("lineage")
        if not isinstance(lineage, dict):
            return prompt  # Plain episode: no playbook read, no behavior change.
        playbook: dict[str, Any] | None = None
        try:
            playbook = await ctx.ledger().get_playbook()
        except Exception as e:  # A playbook read must never cost green its turn.
            log.warning("playbook_read_failed", agent=self.name, episode_id=req.episode_id, day=req.day, status=getattr(e, "status", None))
        section = playbook_prompt_section(playbook, lineage)
        return prompt if not section else f"{prompt}\n\n{section}"

    async def reflect(self, req: ReflectRequest) -> ReflectResponse:
        return reflect_playbook(req)

    async def dry_run_reflect(self, req: ReflectRequest) -> ReflectResponse:
        return reflect_playbook(req)

    async def run_turn(self, req: TurnRequest) -> TurnResponse:
        with clerk_scope():
            return await super().run_turn(req)

    async def _droid_turn(self, req: TurnRequest, emitter: EventEmitter) -> tuple[str, Usage | None]:
        # Live execution enabled after Green SDK acceptance (issue #78).
        return await super()._droid_turn(req, emitter)

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
