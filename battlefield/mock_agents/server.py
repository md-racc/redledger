"""Stub red/green/blue for backend + frontend development. Owner: Dev Ad.

One FastAPI app; AGENT_NAME selects behavior. No LLMs. Produces a believable episode so the
orchestrator, gate, scoring, events and frontend can be exercised with zero Factory credits.

    AGENT_NAME=red  uvicorn mock_agents.server:app --port 8001
"""

from __future__ import annotations

import hmac
import os
import time

import httpx
from fastapi import FastAPI, Header, HTTPException

from agentkit import AgentSettings, AttackCreate, EventEmitter, GateBlocked, LedgerClient, LedgerError
from agentkit.models import AuditRequest, AuditResponse, GateRequest, GateResponse, ReflectRequest, ReflectResponse, TurnRequest, TurnResponse

s = AgentSettings(AGENT_NAME=os.environ.get("AGENT_NAME", "red"))
app = FastAPI(title=f"mock-{s.agent_name}")
THRESHOLD = float(os.environ.get("APPROVAL_THRESHOLD", "5000"))
# Opt-in, deterministic escalations from the mock gate (unset = default behavior). Comma-separated
# triggers; a gated call matching any of them gets `escalate` whatever the default verdict was:
#   all | *               every gated call
#   amount>N              amount strictly above N (e.g. amount>4000)
#   action:<action>       that gated action (e.g. action:invoices.pay)
#   <rule id>             that mock rule fired (e.g. near_threshold, vendor_age_lt_7d)
# Battlefield only holds escalations in `enforce`; in `shadow` they are recorded, nothing waits.
MOCK_BLUE_ESCALATE = os.environ.get("MOCK_BLUE_ESCALATE", "")


def escalate_trigger(spec: str, action: str, amount: float | None, rules: list[str]) -> str | None:
    """The first MOCK_BLUE_ESCALATE trigger this call matches, or None."""
    for raw in spec.split(","):
        t = raw.strip()
        if not t:
            continue
        if t in ("all", "*"):
            return t
        if t.startswith("amount>"):
            try:
                if amount is not None and amount > float(t[len("amount>") :]):
                    return t
            except ValueError:
                continue
        elif t.startswith("action:"):
            if action == t[len("action:") :]:
                return t
        elif t in rules:
            return t
    return None


def _auth(authorization: str | None) -> None:
    if not hmac.compare_digest((authorization or "").encode(), f"Bearer {s.internal_token}".encode()):
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


# ---------------- evolution (lineage episodes) ----------------
# Deterministic stand-ins for what real agents learn. They read only what contracts/agent-service.md
# hands an agent: `attack` items from the daily debrief or the /reflect review, plus their own playbook
# (GET/PUT /api/playbook). Never origin, never battlefield internals. Each attack counts once (`seen`):
# daily items reappear while in the window, and the review repeats them.
SCHEME_IDS = [x["id"] for x in SCHEMES]
CAUGHT, WON = ("blocked", "flagged"), ("extracted", "partial")
# blue's answer to a scheme that got past it
LEARNED_FOR = {
    "ghost_vendor": "learned:young_vendor_any_amount",
    "duplicate_invoice": "learned:duplicate_amount_loose",
    "bank_swap": "learned:bank_change_any_amount",
    "threshold_split": "learned:near_threshold_wide",
}
NEAR_BAND, NEAR_BAND_MIN = 0.95, 0.80


def _new_attacks(pb: dict, items: list[dict]) -> tuple[list[str], list[dict]]:
    seen = list(pb.get("seen", []))
    fresh = [it for it in items if it.get("kind") == "attack" and it.get("attack_id") not in seen]
    return (seen + [it["attack_id"] for it in fresh])[-200:], fresh


def red_adapt(pb: dict, items: list[dict]) -> tuple[dict, str]:
    """Drop schemes caught twice that never paid; favour schemes that extracted. Returns (content, rationale)."""
    seen, fresh = _new_attacks(pb, items)
    caught, won = dict(pb.get("caught", {})), dict(pb.get("won", {}))
    for it in fresh:
        sid, out = it.get("scheme_id", ""), it.get("outcome")
        if out in CAUGHT:
            caught[sid] = caught.get(sid, 0) + 1
        elif out in WON:
            won[sid] = won.get(sid, 0) + 1
    dropped = sorted(sid for sid in SCHEME_IDS if caught.get(sid, 0) >= 2 and not won.get(sid))
    if len(dropped) == len(SCHEME_IDS):  # never give up entirely: keep the least-caught scheme
        dropped.remove(min(SCHEME_IDS, key=lambda sid: (caught.get(sid, 0), SCHEME_IDS.index(sid))))
    content = {**pb, "seen": seen, "caught": caught, "won": won, "dropped": dropped}
    favoured = [sid for sid in SCHEME_IDS if won.get(sid)]
    return content, f"dropped {dropped or 'none'}; favouring {favoured or 'none'} ({len(fresh)} new attack results)"


def red_choose(pb: dict, day: int) -> str:
    """Deterministic: each live scheme weighted 1 + times it extracted. An empty playbook is the plain rotation."""
    won = pb.get("won", {})
    weighted = [sid for sid in SCHEME_IDS if sid not in pb.get("dropped", []) for _ in range(1 + won.get(sid, 0))]
    return weighted[day % len(weighted)]


def blue_adapt(pb: dict, items: list[dict]) -> tuple[dict, str]:
    """For each attack that got past blue (caught_by empty), learn that scheme's rule; a missed split widens the band."""
    seen, fresh = _new_attacks(pb, items)
    learned, band = set(pb.get("learned", [])), float(pb.get("near_band", NEAR_BAND))
    missed = [it.get("scheme_id", "") for it in fresh if not it.get("caught_by")]
    for sid in missed:
        if sid in LEARNED_FOR:
            learned.add(LEARNED_FOR[sid])
        if sid == "threshold_split":
            band = round(max(NEAR_BAND_MIN, band - 0.05), 2)
    content = {**pb, "seen": seen, "learned": sorted(learned), "near_band": band}
    return content, f"missed {missed or 'none'}; rules {sorted(learned) or 'none'}; near band {band}"


async def adapt_playbook(ledger: LedgerClient, debrief: dict | None, adapt) -> dict:
    """Read the playbook; fold in today's debrief inside the turn; {} outside lineages (404)."""
    pb = await ledger.get_playbook()
    if pb is None:
        return {}
    content, rationale = adapt(pb.get("content") or {}, (debrief or {}).get("items", []))
    if content != (pb.get("content") or {}):
        await ledger.put_playbook(content, rationale, pb["version"])
    return content


@app.post("/reflect", response_model=ReflectResponse)
async def reflect(req: ReflectRequest, authorization: str | None = Header(default=None)):
    _auth(authorization)
    adapt = {"red": red_adapt, "blue": blue_adapt}.get(s.agent_name)
    if adapt is None:  # mock green has nothing to learn
        return ReflectResponse(ok=True, rationale="dry run")
    content, rationale = adapt(req.playbook.content, req.review.get("items", []))
    return ReflectResponse(ok=True, playbook=content if content != req.playbook.content else None, rationale=rationale)


async def red_turn(req: TurnRequest, ledger: LedgerClient, em: EventEmitter) -> str:
    pb = await adapt_playbook(ledger, req.options.get("debrief"), red_adapt)
    scheme_id = req.options.get("scheme_id") or red_choose(pb, req.day)
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
_learned: dict[str, tuple[int, dict]] = {}  # episode_id -> (playbook version, content), refreshed when the version moves


async def blue_playbook(req: GateRequest) -> dict:
    if req.playbook_version is None:  # plain episode
        return {}
    cached = _learned.get(req.episode_id)
    if cached is None or cached[0] != req.playbook_version:
        try:
            async with LedgerClient(s, episode_id=req.episode_id, day=req.day) as ledger:  # a read: allowed outside turns
                pb = await ledger.get_playbook() or {}
        except (LedgerError, httpx.HTTPError):  # never fail the gate over a playbook read: keep what we had
            return cached[1] if cached else {}
        cached = _learned[req.episode_id] = (req.playbook_version, pb.get("content") or {})
    return cached[1]


def learned_rules(pb: dict, req: GateRequest, age: int, inv: dict) -> list[str]:
    """The learned rules in blue's playbook that fire on an invoice action."""
    learned, amount, ctx, fired = set(pb.get("learned", [])), req.amount or 0, req.context, []
    if "learned:young_vendor_any_amount" in learned and age < 7:
        fired.append("learned:young_vendor_any_amount")
    band = float(pb.get("near_band", NEAR_BAND))
    if "learned:near_threshold_wide" in learned and THRESHOLD * band <= amount < THRESHOLD * NEAR_BAND:
        fired.append("learned:near_threshold_wide")
    if "learned:duplicate_amount_loose" in learned:
        if any(abs(float(p["amount"]) - amount) <= 1.0 and p["invoice_number"] != inv.get("invoice_number") for p in ctx.get("vendor_paid_invoices", [])):
            fired.append("learned:duplicate_amount_loose")
    if "learned:bank_change_any_amount" in learned:
        recent = [ch for ch in ctx.get("vendor_recent_changes", []) if ch["field"] == "bank_account" and ch["status"] == "approved"]
        if any(req.day - int(ch.get("resolved_day") or ch["requested_day"]) <= 14 for ch in recent):
            fired.append("learned:bank_change_any_amount")
    return fired


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
        if req.amount and THRESHOLD * NEAR_BAND <= req.amount < THRESHOLD:
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
        rules += [r for r in learned_rules(await blue_playbook(req), req, age, inv) if r not in rules]
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
    trigger = escalate_trigger(MOCK_BLUE_ESCALATE, req.action, req.amount, rules)
    if trigger is not None:
        verdict = "escalate"
        rules.append(f"mock_escalate:{trigger}")
    reason = {"allow": "No control exceptions.", "block": f"Blocked: {', '.join(rules)}.", "escalate": f"Needs human review: {', '.join(rules)}."}[verdict]
    return GateResponse(verdict=verdict, reason=reason, confidence=0.9 if rules else 0.99, rules_fired=rules, latency_ms=int((time.monotonic() - t0) * 1000))


@app.post("/audit", response_model=AuditResponse)
async def audit(req: AuditRequest, authorization: str | None = Header(default=None)):
    _auth(authorization)
    flags = 0
    async with LedgerClient(s, episode_id=req.episode_id, day=req.day) as ledger:
        await adapt_playbook(ledger, req.debrief.model_dump() if req.debrief else None, blue_adapt)
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
