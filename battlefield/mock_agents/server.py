"""Stub red/green/blue for backend + frontend development. Owner: Dev Ad.

One FastAPI app; AGENT_NAME selects behavior. No LLMs. Produces a believable episode so the
orchestrator, gate, scoring, events and frontend can be exercised with zero Factory credits.

    AGENT_NAME=red  uvicorn mock_agents.server:app --port 8001
"""

from __future__ import annotations

import os
import time

from fastapi import FastAPI, Header, HTTPException

from agentkit import AgentSettings, AttackCreate, EventEmitter, GateBlocked, LedgerClient, LedgerError
from agentkit.models import AuditRequest, AuditResponse, GateRequest, GateResponse, TurnRequest, TurnResponse

s = AgentSettings(AGENT_NAME=os.environ.get("AGENT_NAME", "red"))
app = FastAPI(title=f"mock-{s.agent_name}")
THRESHOLD = float(os.environ.get("APPROVAL_THRESHOLD", "5000"))


def _auth(authorization: str | None) -> None:
    if authorization != f"Bearer {s.internal_token}":
        raise HTTPException(401)


@app.get("/health")
async def health():
    return {"ok": True, "agent": s.agent_name, "model": "mock", "droid_ok": False, "dry_run": True}


# ---------------- RED ----------------
SCHEMES = [
    {
        "id": "ghost_vendor",
        "display_name": "Ghost Vendor",
        "story": "A brand-new vendor appears and immediately invoices for services never delivered.",
        "params_schema": {"type": "object", "properties": {"amount": {"type": "number"}}},
        "expected_impact": {"min": 1000, "max": 4999},
    },
    {
        "id": "duplicate_invoice",
        "display_name": "Duplicate Invoice",
        "story": "A paid invoice is resubmitted with a new number and the amount off by a few cents.",
        "params_schema": {"type": "object"},
        "expected_impact": {"min": 300, "max": 9000},
    },
    {
        "id": "bank_swap",
        "display_name": "Bank Account Swap",
        "story": "A real vendor's bank details are 'updated' right before a large invoice is paid.",
        "params_schema": {"type": "object"},
        "expected_impact": {"min": 2000, "max": 12000},
    },
    {
        "id": "threshold_split",
        "display_name": "Threshold Splitting",
        "story": "One large job is billed as several invoices just under the auto-approval line.",
        "params_schema": {"type": "object", "properties": {"parts": {"type": "integer"}}},
        "expected_impact": {"min": 9000, "max": 15000},
    },
]


@app.get("/schemes")
async def schemes(authorization: str | None = Header(default=None)):
    _auth(authorization)
    return SCHEMES


async def red_turn(req: TurnRequest, ledger: LedgerClient, em: EventEmitter) -> str:
    scheme_id = req.options.get("scheme_id") or SCHEMES[req.day % len(SCHEMES)]["id"]
    scheme = next(x for x in SCHEMES if x["id"] == scheme_id)
    em.thinking(f"Day {req.day}. Reviewing the books for an opening. Going with: {scheme['display_name']}.")
    if scheme_id == "ghost_vendor":
        amount = float(req.options.get("params", {}).get("amount", 4920.0))
        atk = await ledger.declare_attack(AttackCreate(scheme_id=scheme_id, display_name=scheme["display_name"], story=scheme["story"], target_amount=amount))
        v = await ledger.create_vendor(
            {"name": "Acme Office Supply LLC", "ein": "47-1234567", "bank_account": "9988776655", "bank_routing": "021000021", "category": "office"}
        )
        await ledger.submit_invoice(
            {
                "vendor_id": v["id"],
                "amount": amount,
                "invoice_number": f"AOS-{1000 + req.day}",
                "line_items": [{"desc": "Office consumables", "amount": amount}],
            }
        )
        return f"ghost vendor {v['name']} invoiced ${amount:,.2f} (attack {atk['id']})"
    if scheme_id == "duplicate_invoice":
        paid = await ledger.list_invoices(status="paid")
        if not paid:
            return "no paid invoices to duplicate"
        src = paid[-1]
        amount = round(float(src["amount"]) + 0.03, 2)
        atk = await ledger.declare_attack(AttackCreate(scheme_id=scheme_id, display_name=scheme["display_name"], story=scheme["story"], target_amount=amount))
        await ledger.submit_invoice({"vendor_id": src["vendor_id"], "amount": amount, "invoice_number": src["invoice_number"] + "A", "po_id": src.get("po_id")})
        return f"duplicated {src['invoice_number']} for ${amount:,.2f} (attack {atk['id']})"
    if scheme_id == "bank_swap":
        pending = await ledger.list_invoices(status="pending")
        pending = [i for i in pending if float(i["amount"]) > 2000]
        if not pending:
            return "no large pending invoice to hijack"
        target = pending[0]
        atk = await ledger.declare_attack(
            AttackCreate(scheme_id=scheme_id, display_name=scheme["display_name"], story=scheme["story"], target_amount=float(target["amount"]))
        )
        await ledger.request_vendor_change(
            {
                "vendor_id": target["vendor_id"],
                "field": "bank_account",
                "new_value": "1122334455",
                "justification": "We have moved banks. Please update remittance details.",
            }
        )
        return f"requested bank change on vendor {target['vendor_id']} ahead of ${float(target['amount']):,.2f} invoice (attack {atk['id']})"
    if scheme_id == "threshold_split":
        parts = int(req.options.get("params", {}).get("parts", 3))
        total = 14400.0
        atk = await ledger.declare_attack(AttackCreate(scheme_id=scheme_id, display_name=scheme["display_name"], story=scheme["story"], target_amount=total))
        v = await ledger.create_vendor(
            {"name": "Bayline Facilities Group", "bank_account": "5566778899", "bank_routing": "021000021", "category": "facilities"}
        )
        each = round(total / parts, 2)
        for k in range(parts):
            await ledger.submit_invoice({"vendor_id": v["id"], "amount": each, "invoice_number": f"BFG-{req.day}{k}"})
        return f"split ${total:,.0f} into {parts} invoices of ${each:,.2f} (attack {atk['id']})"
    return "unknown scheme"


# ---------------- GREEN ----------------
async def green_turn(req: TurnRequest, ledger: LedgerClient, em: EventEmitter) -> str:
    em.thinking("Working the AP queue: match, approve, pay anything under the auto-approval line.")
    done, blocked = 0, 0
    for ch in await ledger.list_vendor_changes(status="pending"):
        try:
            await ledger.approve_vendor_change(ch["id"])
            done += 1
        except GateBlocked:
            blocked += 1
    pos = {p["id"]: p for p in await ledger.list_purchase_orders(status="open")}
    for inv in await ledger.list_invoices(status="pending"):
        try:
            if inv.get("po_id") and inv["po_id"] in pos:
                await ledger.match_invoice(inv["id"], inv["po_id"])
            else:
                await ledger.approve_invoice(inv["id"])
        except (GateBlocked, LedgerError):
            blocked += 1
    for inv in await ledger.list_invoices(status="matched") + await ledger.list_invoices(status="approved"):
        if float(inv["amount"]) <= THRESHOLD:
            try:
                await ledger.pay_invoice(inv["id"])
                done += 1
            except (GateBlocked, LedgerError):
                blocked += 1
    for ex in await ledger.list_expenses(status="pending"):
        try:
            await ledger.approve_expense(ex["id"])
            await ledger.pay_expense(ex["id"])
            done += 1
        except (GateBlocked, LedgerError):
            blocked += 1
    return f"processed {done} items, {blocked} blocked/failed"


# ---------------- BLUE ----------------
@app.post("/gate", response_model=GateResponse)
async def gate(req: GateRequest, authorization: str | None = Header(default=None)):
    _auth(authorization)
    t0 = time.monotonic()
    rules: list[str] = []
    ctx = req.context
    vendor = ctx.get("vendor") or {}
    inv = ctx.get("invoice") or {}
    if req.action in ("invoices.approve", "invoices.pay", "invoices.match"):
        age = req.day - int(vendor.get("created_day", -999))
        if age < 7 and (req.amount or 0) > 1000:
            rules.append("vendor_age_lt_7d")
        if req.amount and THRESHOLD * 0.95 <= req.amount < THRESHOLD:
            rules.append("near_threshold")
        for p in ctx.get("vendor_paid_invoices", []):
            if abs(float(p["amount"]) - (req.amount or 0)) <= 0.05 and p["invoice_number"] != inv.get("invoice_number"):
                rules.append("duplicate_amount_match")
                break
        for ch in ctx.get("vendor_recent_changes", []):
            if (
                ch["field"] == "bank_account"
                and ch["status"] == "approved"
                and req.day - int(ch.get("resolved_day") or ch["requested_day"]) <= 14
                and (req.amount or 0) > 2500
            ):
                rules.append("recent_bank_change")
    if req.action == "vendor_changes.approve":
        if (ctx.get("vendor_change") or {}).get("field") == "bank_account":
            rules.append("bank_change_requested")
            if ctx.get("vendor_open_invoices"):
                rules.append("bank_change_with_open_invoices")
    verdict = "allow"
    if "recent_bank_change" in rules or "bank_change_with_open_invoices" in rules or len(rules) >= 2:
        verdict = "block"
    elif rules:
        verdict = "escalate" if req.controller_mode == "enforce" and "near_threshold" in rules else "block"
    reason = {"allow": "No control exceptions.", "block": f"Blocked: {', '.join(rules)}.", "escalate": f"Needs human review: {', '.join(rules)}."}[verdict]
    return GateResponse(verdict=verdict, reason=reason, confidence=0.9 if rules else 0.99, rules_fired=rules, latency_ms=int((time.monotonic() - t0) * 1000))


@app.post("/audit", response_model=AuditResponse)
async def audit(req: AuditRequest, authorization: str | None = Header(default=None)):
    _auth(authorization)
    flags = 0
    async with LedgerClient(s, episode_id=req.episode_id, day=req.day) as ledger:
        for v in await ledger.list_vendors(status="active"):
            if v["created_day"] == req.day:
                await ledger.raise_flag("vendor", v["id"], "medium", "Vendor created today; verify before paying.")
                flags += 1
        pending = await ledger.list_invoices(status="pending")
        md = f"# Day {req.day} controller report\n\n- Vendors flagged: {flags}\n- Invoices still pending: {len(pending)}\n"
        await ledger.post_report(req.day, md)
    return AuditResponse(ok=True, flags_raised=flags, report_posted=True, summary=f"{flags} flags")


# ---------------- /turn ----------------
@app.post("/turn", response_model=TurnResponse)
async def turn(req: TurnRequest, authorization: str | None = Header(default=None)):
    _auth(authorization)
    t0 = time.monotonic()
    async with LedgerClient(s, episode_id=req.episode_id, day=req.day) as ledger, EventEmitter(s, episode_id=req.episode_id, day=req.day) as em:
        try:
            if s.agent_name == "red":
                summary = await red_turn(req, ledger, em)
            elif s.agent_name == "green":
                summary = await green_turn(req, ledger, em)
            else:
                summary = "blue has no /turn; use /audit"
            return TurnResponse(ok=True, summary=f"[mock] {summary}", duration_sec=time.monotonic() - t0)
        except Exception as e:
            return TurnResponse(ok=False, summary=f"[mock] failed: {e}", duration_sec=time.monotonic() - t0)
