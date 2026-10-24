"""Trusting AP clerk; live execution awaits the shared invocation/gate protocol."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from playbook import reflect_playbook
from workflow import clerk_scope, run_clerk

import tools as green_tools
from agentkit import DroidAgent, EventEmitter, TurnRequest, TurnResponse, collect_tools
from agentkit.models import ReflectRequest, ReflectResponse, Usage
from agentkit.tools import ToolFn

PREREQUISITE = (
    "Green live integration prerequisite: merged shared preflight protocol, verified "
    "invocation identity and exact tool restrictions are required before Droid execution."
)


class GreenAgent(DroidAgent):
    name = "green"
    autonomy = "off"  # Do not change without an SDK experiment and shared integration.
    turn_loop_dry_run = True
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

    async def reflect(self, req: ReflectRequest) -> ReflectResponse:
        return reflect_playbook(req)

    async def dry_run_reflect(self, req: ReflectRequest) -> ReflectResponse:
        return reflect_playbook(req)

    async def run_turn(self, req: TurnRequest) -> TurnResponse:
        with clerk_scope():
            return await super().run_turn(req)

    async def _droid_turn(self, req: TurnRequest, emitter: EventEmitter) -> tuple[str, Usage | None]:
        # Guard before the base class imports the SDK, constructs a server or opens a Session.
        raise RuntimeError(PREREQUISITE)

    async def on_permission(self, request: Any) -> Any:
        from droid_sdk import ToolConfirmationOutcome

        # Never submit incomplete context or a fabricated key to Blue's verdict cache.
        return request.respond(ToolConfirmationOutcome.CANCEL, comment=PREREQUISITE)

    async def dry_run_turn(self, req: TurnRequest) -> str:
        with clerk_scope(reuse=True):
            return await run_clerk(green_tools)
