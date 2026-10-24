"""AuditAgent: blue's periodic audit as a Droid session. Owner: Dev M.

Runs once per day after green. Latency doesn't matter here; visible reasoning does. It reads the
day's activity and the audit log, raises flags, freezes vendors when warranted, and posts the
end-of-day controller report.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from agentkit import DroidAgent, TurnRequest, collect_tools, ctx, ledger_tool

PROMPT = (Path(__file__).parent.parent / "prompts" / "audit.md").read_text()


# ---- tools ----


@ledger_tool(
    "day_activity",
    "Everything that happened today: invoices received/paid, vendor changes, new vendors/employees, payments, verdicts recorded in the audit log.",
)
async def day_activity() -> str:
    L = ctx.ledger()
    day = ctx.turn().day
    return json.dumps(
        {
            "invoices_received": await L.list_invoices(day=day),
            "payments": await L.list_payments(day=day),
            "vendor_changes": await L.list_vendor_changes(),
            "new_vendors": [v for v in await L.list_vendors() if v["created_day"] == day],
            "employees_new": [e for e in await L.list_employees() if e["start_day"] == day],
            "audit_log": (await L.list_audit_log(day=day))[:200],
            "existing_flags": await L.list_flags(),
        }
    )


@ledger_tool("vendor_dedupe", "Find vendors with near-identical names or shared bank accounts.")
async def vendor_dedupe() -> str:
    vendors = await ctx.ledger().list_vendors()
    by_acct = Counter(v["bank_account"] for v in vendors)
    shared = [v for v in vendors if by_acct[v["bank_account"]] > 1]
    names = {}
    for v in vendors:
        key = "".join(ch for ch in v["name"].lower() if ch.isalnum())[:12]
        names.setdefault(key, []).append({"id": v["id"], "name": v["name"]})
    similar = [grp for grp in names.values() if len(grp) > 1]
    return json.dumps({"shared_bank_account": shared, "similar_names": similar})


@ledger_tool("benford_check", "First-digit distribution of today's invoice amounts vs Benford's law; returns a rough deviation score.")
async def benford_check() -> str:
    invs = await ctx.ledger().list_invoices(day=ctx.turn().day)
    digits = Counter(str(abs(float(i["amount"])))[0] for i in invs if float(i["amount"]) > 0)
    n = sum(digits.values()) or 1
    import math

    expected = {str(d): math.log10(1 + 1 / d) for d in range(1, 10)}
    dev = sum(abs(digits.get(d, 0) / n - p) for d, p in expected.items())
    return json.dumps({"n": n, "observed": dict(digits), "deviation": round(dev, 3), "note": "deviation > 0.6 with n > 15 is worth a look"})


@ledger_tool(
    "raise_flag", "Flag an entity for review: entity_type (vendor|invoice|employee|expense|vendor_change), entity_id, severity (low|medium|high), reason."
)
async def raise_flag(entity_type: str, entity_id: str, severity: str, reason: str) -> str:
    return json.dumps(await ctx.ledger().raise_flag(entity_type, entity_id, severity, reason))


@ledger_tool("freeze_vendor", "Freeze a vendor so no payments can be made to it.")
async def freeze_vendor(vendor_id: str, reason: str) -> str:
    return json.dumps(await ctx.ledger().freeze_vendor(vendor_id, reason))


@ledger_tool("post_report", "Post the end-of-day controller report (markdown).")
async def post_report(markdown: str) -> str:
    return json.dumps(await ctx.ledger().post_report(ctx.turn().day, markdown))


import sys  # noqa: E402

_THIS = sys.modules[__name__]


class AuditAgent(DroidAgent):
    name = "blue"
    autonomy = "low"
    system_prompt = PROMPT

    def tools(self):
        return collect_tools(_THIS)

    async def build_prompt(self, req: TurnRequest) -> str:
        return (
            f"Day {req.day} close. Review today's activity (day_activity), run vendor_dedupe and benford_check, "
            "flag anything suspicious with a specific reason, freeze a vendor only when the evidence is strong, "
            "then post_report with a short markdown report: what you reviewed, what you flagged, what needs a human tomorrow."
        )

    async def _droid_turn(self, req, emitter):
        raise RuntimeError("Blue live audit invocation/context binding is unverified; no stream or write attempted.")

    async def dry_run_turn(self, req: TurnRequest) -> str:
        raise RuntimeError("Blue guarded audit upgrade pending; no write attempted.")
        L = ctx.ledger()
        flags = 0
        for v in await L.list_vendors(status="active"):
            if v["created_day"] == req.day:
                await L.raise_flag("vendor", v["id"], "medium", "Vendor created today; verify before paying.")
                flags += 1
        pending = await L.list_invoices(status="pending")
        await L.post_report(req.day, f"# Day {req.day} controller report\n\n- Vendors flagged: {flags}\n- Invoices still pending: {len(pending)}\n")
        return f"{flags} flags, report posted"
