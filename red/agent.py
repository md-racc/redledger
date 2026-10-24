"""RedAgent. Owner: Dev Al."""

from __future__ import annotations

import json
from pathlib import Path

import tools as red_tools
from agentkit import DroidAgent, TurnRequest, collect_tools, ctx
from schemes import SCHEMES

PROMPT = (Path(__file__).parent / "prompts" / "system.md").read_text()


class RedAgent(DroidAgent):
    name = "red"
    autonomy = "high"
    system_prompt = PROMPT

    def tools(self):
        return collect_tools(red_tools)

    async def build_prompt(self, req: TurnRequest) -> str:
        forced = req.options.get("scheme_id")
        if forced:
            return (
                f"Day {req.day}. You MUST run scheme `{forced}` with params {json.dumps(req.options.get('params', {}))}. "
                "Call inspect_books first if you need ids, then run_scheme. Finish with one sentence describing what you did."
            )
        catalog = "; ".join(f"{s.id}: {s.story}" for s in SCHEMES.values())
        # The catalog is inlined so the model can decide after one read; live turns that wandered
        # (re-listing schemes, second-guessing) ran past the turn timeout after attacking.
        return (
            f"Day {req.day}. Schemes available: {catalog}\n"
            "Do exactly this, with no other tool calls: 1) call inspect_books once; 2) pick the one scheme that best "
            "blends in with what you see (vendors with history, invoices tied to POs, amounts like recent payments); "
            '3) call run_scheme once with that scheme_id and params_json "{}" unless you have a specific reason to set params; '
            "4) reply with one sentence: which scheme, which vendor, how much. Then stop."
        )

    async def dry_run_turn(self, req: TurnRequest) -> str:
        """No LLM: rotate through viable schemes deterministically."""
        L = ctx.ledger()
        order = list(SCHEMES.values())
        scheme = SCHEMES.get(req.options.get("scheme_id", "")) or order[req.day % len(order)]
        if not await scheme.viable(L):
            return f"{scheme.id} not viable today"
        params = req.options.get("params", {})
        plan = await scheme.plan(L, params)
        await L.declare_attack(scheme.attack_decl(plan, params))
        return await scheme.execute(L, plan)
