"""Frontend read API — deliberately over-featured. Owner: Dev Ad (routes) / Dev R (consumer).

Mounted at /api/fe. Operator-only (bearer). Everything here is derived from ledger tables and
events; nothing here mutates. These exist so Dev R can build whatever view the sandbox suggests
without asking backend for another endpoint. Interactive docs: http://battlefield:8000/docs.

Endpoint families:
  snapshot      — the company at a glance for an episode (cash, AP, headcount, exposure)
  timeline      — per-day series for charts (cash flow, verdict counts, $ at risk)
  entities      — any entity + its full trail (verdicts, audit log, events, payments, flags)
  vendors       — profiles with risk signals, leaderboards
  attacks       — every declared attack with its trail and outcome
  verdicts      — filterable list, rule frequency, confusion matrix (verdict × origin)
  agents        — activity stats per agent per day, credits burned
  compare       — two episodes (same seed, different controller mode) side by side
  feed          — events pre-digested into UI cards
  search        — free-text across vendors / invoices / employees / reasons

Replay episodes (`replay_*`, see control.py) have events but no ledger rows. For them snapshot's
score, timeline, attacks and compare are derived from events; feed, thinking and the `turns` half
of agents/activity are event-derived anyway. Everything else here is table-derived and is empty
(or zero, or 404 for entity trails) for a replay.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import db
from ..auth import bearer
from ..scoring import score
from .control import is_replay, replay_score

router = APIRouter(prefix="/fe", dependencies=[Depends(bearer)])


# Event payloads are rendered defensively: a fixture or a buggy emitter can put any JSON in a
# payload field, and a read view must not 500 on it.
def _d(x: Any) -> dict[str, Any]:
    return x if isinstance(x, dict) else {}


def _n(x: Any, default: float = 0.0) -> float:
    return float(x) if isinstance(x, int | float) and not isinstance(x, bool) else default


def _s(x: Any) -> str:
    return x if isinstance(x, str) else ""


async def _ep(episode_id: str) -> dict[str, Any]:
    row = await db.fetchrow("SELECT * FROM episodes WHERE id=$1", episode_id)
    if not row:
        raise HTTPException(404, "episode not found")
    return db.row_to_dict(row)  # type: ignore[return-value]


# ---------------- snapshot ----------------


@router.get("/episodes/{episode_id}/snapshot")
async def snapshot(episode_id: str):
    """Company-at-a-glance. Safe to poll; cheap."""
    ep = await _ep(episode_id)
    day = ep["current_day"]
    cash = float(await db.fetchval("SELECT COALESCE(SUM(amount),0) FROM bank_transactions WHERE episode_id=$1", episode_id))
    ap_open = await db.fetchrow(
        "SELECT COUNT(*) AS n, COALESCE(SUM(amount),0) AS total FROM invoices WHERE episode_id=$1 AND status IN ('pending','matched','approved')", episode_id
    )
    ap_overdue = await db.fetchrow(
        "SELECT COUNT(*) AS n, COALESCE(SUM(amount),0) AS total FROM invoices WHERE episode_id=$1 AND status IN ('pending','matched','approved') AND due_day < $2",
        episode_id,
        day,
    )
    vendors = await db.fetchrow(
        "SELECT COUNT(*) FILTER (WHERE status='active') AS active, COUNT(*) FILTER (WHERE status='frozen') AS frozen, COUNT(*) FILTER (WHERE created_day>=0) AS new_this_episode FROM vendors WHERE episode_id=$1",
        episode_id,
    )
    employees = await db.fetchval("SELECT COUNT(*) FROM employees WHERE episode_id=$1 AND status='active'", episode_id)
    paid_today = float(await db.fetchval("SELECT COALESCE(SUM(amount),0) FROM payments WHERE episode_id=$1 AND paid_day=$2", episode_id, max(day - 1, 0)))
    open_esc = await db.fetchval("SELECT COUNT(*) FROM escalations WHERE episode_id=$1 AND status='open'", episode_id)
    # exposure: red-origin money still in flight (hidden from agents, fine for the operator UI)
    at_risk = float(
        await db.fetchval(
            "SELECT COALESCE(SUM(amount),0) FROM invoices WHERE episode_id=$1 AND origin='red' AND status IN ('pending','matched','approved')", episode_id
        )
    )
    return {
        "episode": ep,
        "company": {
            "name": "Coastal Supply Co.",
            "cash_position": round(cash, 2),
            "employees_active": employees,
            "vendors": db.row_to_dict(vendors),
            "paid_last_day": round(paid_today, 2),
        },
        "ap": {"open": db.row_to_dict(ap_open), "overdue": db.row_to_dict(ap_overdue)},
        "controls": {"mode": ep["controller_mode"], "open_escalations": open_esc},
        "exposure": {"red_dollars_in_flight": round(at_risk, 2)},
        "score": await _score(episode_id),
    }


async def _score(episode_id: str) -> dict[str, Any]:
    return await replay_score(episode_id) if is_replay(episode_id) else await score.compute(episode_id)


# ---------------- timeline / series ----------------


@router.get("/episodes/{episode_id}/timeline")
async def timeline(episode_id: str):
    """Per-day rows for charts: cash in/out, invoices received/paid/blocked, verdicts by kind, $ extracted/blocked cumulative."""
    ep = await _ep(episode_id)
    if is_replay(episode_id):
        return await _replay_timeline(episode_id, ep["current_day"])
    rows = await db.fetch(
        """
        WITH days AS (SELECT generate_series(0, GREATEST($2-1,0)) AS day)
        SELECT d.day,
          (SELECT COALESCE(SUM(amount),0) FROM bank_transactions b WHERE b.episode_id=$1 AND b.day=d.day AND amount>0) AS cash_in,
          (SELECT COALESCE(-SUM(amount),0) FROM bank_transactions b WHERE b.episode_id=$1 AND b.day=d.day AND amount<0) AS cash_out,
          (SELECT COUNT(*) FROM invoices i WHERE i.episode_id=$1 AND i.received_day=d.day) AS invoices_received,
          (SELECT COUNT(*) FROM payments p WHERE p.episode_id=$1 AND p.paid_day=d.day) AS payments_made,
          (SELECT COUNT(*) FROM verdicts v WHERE v.episode_id=$1 AND v.day=d.day AND v.verdict='allow') AS verdict_allow,
          (SELECT COUNT(*) FROM verdicts v WHERE v.episode_id=$1 AND v.day=d.day AND v.verdict='block') AS verdict_block,
          (SELECT COUNT(*) FROM verdicts v WHERE v.episode_id=$1 AND v.day=d.day AND v.verdict='escalate') AS verdict_escalate,
          (SELECT COALESCE(SUM(amount),0) FROM payments p WHERE p.episode_id=$1 AND p.paid_day<=d.day AND p.origin_of_source='red') AS extracted_cumulative,
          (SELECT COALESCE(SUM(i.amount),0) FROM invoices i WHERE i.episode_id=$1 AND i.origin='red' AND i.status IN ('blocked','rejected') AND i.status_day<=d.day) AS blocked_cumulative,
          (SELECT COUNT(*) FROM attacks a WHERE a.episode_id=$1 AND a.day_launched=d.day) AS attacks_launched,
          (SELECT COUNT(*) FROM flags f WHERE f.episode_id=$1 AND f.day=d.day) AS flags_raised
        FROM days d ORDER BY d.day
        """,
        episode_id,
        ep["current_day"],
    )
    return db.rows_to_list(rows)


_TIMELINE_EVENT_TYPES = ["day.started", "gate.verdict", "ledger.mutation", "attack.launched", "flag.raised", "score.updated"]


async def _replay_timeline(episode_id: str, current_day: int) -> list[dict[str, Any]]:
    """Same columns as the live timeline, from events. cash_in/cash_out are not in the event stream (None).
    invoices_received = day.started legit invoices + invoices.submit mutations; payments_made = *.pay
    mutations; extracted/blocked_cumulative = that day's last score.updated (the Score definition,
    which is broader than the live table query: it includes bank_swap diversions and blocks)."""
    days = {
        d: {
            "day": d,
            "cash_in": None,
            "cash_out": None,
            "invoices_received": 0,
            "payments_made": 0,
            "verdict_allow": 0,
            "verdict_block": 0,
            "verdict_escalate": 0,
            "extracted_cumulative": 0.0,
            "blocked_cumulative": 0.0,
            "attacks_launched": 0,
            "flags_raised": 0,
        }
        for d in range(max(current_day, 1))
    }
    scores: dict[int, dict[str, Any]] = {}
    for r in await db.fetch(
        "SELECT day, type, payload FROM events WHERE episode_id=$1 AND type = ANY($2::text[]) ORDER BY id", episode_id, _TIMELINE_EVENT_TYPES
    ):
        row, t, p = days.get(r["day"]), r["type"], _d(r["payload"])
        if row is None:
            continue
        if t == "day.started":
            row["invoices_received"] += int(_n(_d(p.get("legit_injected")).get("invoices")))
        elif t == "gate.verdict" and p.get("verdict") in ("allow", "block", "escalate"):
            row[f"verdict_{p['verdict']}"] += 1
        elif t == "ledger.mutation" and p.get("action") in ("invoices.pay", "expenses.pay"):
            row["payments_made"] += 1
        elif t == "ledger.mutation" and p.get("action") == "invoices.submit":
            row["invoices_received"] += 1
        elif t == "attack.launched":
            row["attacks_launched"] += 1
        elif t == "flag.raised":
            row["flags_raised"] += 1
        elif t == "score.updated":
            scores[r["day"]] = p
    last: dict[str, Any] = {}
    for d, row in sorted(days.items()):
        last = scores.get(d, last)
        row["extracted_cumulative"] = _n(last.get("dollars_extracted"))
        row["blocked_cumulative"] = _n(last.get("dollars_blocked"))
    return [days[d] for d in sorted(days)]


async def _replay_attacks(episode_id: str) -> list[dict[str, Any]]:
    """attacks rows rebuilt from attack.launched/attack.outcome events (no linked ledger rows)."""
    out: dict[str, dict[str, Any]] = {}
    for r in await db.fetch(
        "SELECT day, type, payload FROM events WHERE episode_id=$1 AND type IN ('attack.launched','attack.outcome') ORDER BY id", episode_id
    ):
        p = _d(r["payload"])
        aid = p.get("attack_id")
        if not isinstance(aid, str) or not aid:
            continue
        if r["type"] == "attack.launched":
            out[aid] = {
                "id": aid,
                "episode_id": episode_id,
                "scheme_id": p.get("scheme_id"),
                "display_name": p.get("display_name"),
                "story": p.get("story"),
                "day_launched": r["day"],
                "target_amount": p.get("target_amount"),
                "outcome": "pending",
                "amount_extracted": 0.0,
                "detected_day": None,
            }
        elif aid in out:
            out[aid].update(outcome=p.get("outcome"), amount_extracted=_n(p.get("amount_extracted")), detected_day=p.get("detected_day"))
    return list(out.values())


@router.get("/episodes/{episode_id}/ap_aging")
async def ap_aging(episode_id: str):
    ep = await _ep(episode_id)
    day = ep["current_day"]
    rows = await db.fetch(
        """
        SELECT CASE WHEN due_day >= $2 THEN 'current'
                    WHEN $2 - due_day <= 30 THEN '1-30'
                    WHEN $2 - due_day <= 60 THEN '31-60' ELSE '60+' END AS bucket,
               COUNT(*) AS n, COALESCE(SUM(amount),0) AS total
        FROM invoices WHERE episode_id=$1 AND status IN ('pending','matched','approved') GROUP BY 1
        """,
        episode_id,
        day,
    )
    return db.rows_to_list(rows)


# ---------------- entities + trails ----------------

ENTITY_TABLES = {
    "invoice": "invoices",
    "vendor": "vendors",
    "employee": "employees",
    "expense": "expenses",
    "vendor_change": "vendor_changes",
    "purchase_order": "purchase_orders",
    "payment": "payments",
    "attack": "attacks",
}


@router.get("/episodes/{episode_id}/entities/{entity_type}/{entity_id}")
async def entity_trail(episode_id: str, entity_type: str, entity_id: str):
    """The entity plus everything that ever touched it: verdicts, escalations, audit log, events, flags, payments, related rows."""
    if entity_type not in ENTITY_TABLES:
        raise HTTPException(404, f"unknown entity type; one of {sorted(ENTITY_TABLES)}")
    row = await db.fetchrow(f"SELECT * FROM {ENTITY_TABLES[entity_type]} WHERE id=$1 AND episode_id=$2", entity_id, episode_id)
    if not row:
        raise HTTPException(404)
    out: dict[str, Any] = {"entity_type": entity_type, "entity": db.row_to_dict(row)}
    out["verdicts"] = db.rows_to_list(await db.fetch("SELECT * FROM verdicts WHERE episode_id=$1 AND entity_id=$2 ORDER BY created_at", episode_id, entity_id))
    out["escalations"] = db.rows_to_list(
        await db.fetch("SELECT e.* FROM escalations e JOIN verdicts v ON v.id=e.verdict_id WHERE v.episode_id=$1 AND v.entity_id=$2", episode_id, entity_id)
    )
    out["flags"] = db.rows_to_list(await db.fetch("SELECT * FROM flags WHERE episode_id=$1 AND entity_id=$2", episode_id, entity_id))
    out["audit_log"] = db.rows_to_list(
        await db.fetch("SELECT * FROM audit_log WHERE episode_id=$1 AND (args->>'id'=$2 OR result->>'id'=$2) ORDER BY id", episode_id, entity_id)
    )
    out["events"] = db.rows_to_list(
        await db.fetch(
            "SELECT * FROM events WHERE episode_id=$1 AND (payload->>'entity_id'=$2 OR payload->>'vendor_id'=$2 OR payload->>'attack_id'=$2) ORDER BY id",
            episode_id,
            entity_id,
        )
    )
    if entity_type == "invoice":
        out["vendor"] = db.row_to_dict(await db.fetchrow("SELECT * FROM vendors WHERE id=$1", row["vendor_id"]))
        out["po"] = db.row_to_dict(await db.fetchrow("SELECT * FROM purchase_orders WHERE id=$1", row["po_id"])) if row["po_id"] else None
        out["payment"] = db.row_to_dict(await db.fetchrow("SELECT * FROM payments WHERE invoice_id=$1", entity_id))
        out["attack"] = db.row_to_dict(await db.fetchrow("SELECT * FROM attacks WHERE id=$1", row["attack_id"])) if row["attack_id"] else None
    if entity_type == "vendor":
        out["invoices"] = db.rows_to_list(await db.fetch("SELECT * FROM invoices WHERE vendor_id=$1 ORDER BY received_day", entity_id))
        out["changes"] = db.rows_to_list(await db.fetch("SELECT * FROM vendor_changes WHERE vendor_id=$1 ORDER BY requested_day", entity_id))
        out["purchase_orders"] = db.rows_to_list(await db.fetch("SELECT * FROM purchase_orders WHERE vendor_id=$1 ORDER BY created_day", entity_id))
    if entity_type == "attack":
        out["invoices"] = db.rows_to_list(await db.fetch("SELECT * FROM invoices WHERE attack_id=$1", entity_id))
        out["expenses"] = db.rows_to_list(await db.fetch("SELECT * FROM expenses WHERE attack_id=$1", entity_id))
    return out


# ---------------- vendors ----------------


@router.get("/episodes/{episode_id}/vendors")
async def vendor_profiles(episode_id: str, sort: str = Query("risk", pattern="^(risk|spend|name|newest)$"), limit: int = Query(100, le=500)):
    """Vendor list with derived risk signals. `origin` is included: this is the operator view."""
    ep = await _ep(episode_id)
    day = ep["current_day"]
    rows = await db.fetch(
        """
        SELECT v.*,
          (SELECT COALESCE(SUM(amount),0) FROM invoices i WHERE i.vendor_id=v.id AND i.status='paid') AS lifetime_paid,
          (SELECT COUNT(*) FROM invoices i WHERE i.vendor_id=v.id) AS invoice_count,
          (SELECT COUNT(*) FROM invoices i WHERE i.vendor_id=v.id AND i.status IN ('blocked','rejected')) AS blocked_count,
          (SELECT COUNT(*) FROM vendor_changes c WHERE c.vendor_id=v.id AND c.field='bank_account' AND c.requested_day >= $2-14) AS recent_bank_changes,
          (SELECT COUNT(*) FROM flags f WHERE f.entity_type='vendor' AND f.entity_id=v.id) AS flag_count,
          (SELECT COUNT(*) FROM invoices i WHERE i.vendor_id=v.id AND i.po_id IS NULL) AS no_po_invoices,
          GREATEST(0, 7 - ($2 - v.created_day)) AS newness
        FROM vendors v WHERE v.episode_id=$1
        """,
        episode_id,
        day,
    )
    out = db.rows_to_list(rows)
    for v in out:
        v["risk_score"] = min(
            100, int(v["newness"] * 8 + v["recent_bank_changes"] * 30 + v["flag_count"] * 20 + v["blocked_count"] * 15 + (10 if v["status"] == "frozen" else 0))
        )
    key = {"risk": lambda x: -x["risk_score"], "spend": lambda x: -x["lifetime_paid"], "name": lambda x: x["name"], "newest": lambda x: -x["created_day"]}[sort]
    return sorted(out, key=key)[:limit]


# ---------------- attacks ----------------


@router.get("/episodes/{episode_id}/attacks")
async def attacks(episode_id: str):
    """Every declared attack with its entities and detection trail."""
    if is_replay(episode_id):
        return [{**a, "invoices": [], "expenses": [], "verdicts": [], "flags": []} for a in await _replay_attacks(episode_id)]
    rows = db.rows_to_list(await db.fetch("SELECT * FROM attacks WHERE episode_id=$1 ORDER BY day_launched, created_at, id", episode_id))
    for a in rows:
        a["invoices"] = db.rows_to_list(
            await db.fetch("SELECT id, vendor_id, amount, invoice_number, status, status_day FROM invoices WHERE attack_id=$1", a["id"])
        )
        a["expenses"] = db.rows_to_list(await db.fetch("SELECT id, employee_id, amount, status FROM expenses WHERE attack_id=$1", a["id"]))
        ids = [i["id"] for i in a["invoices"]] + [e["id"] for e in a["expenses"]] + [i["vendor_id"] for i in a["invoices"]]
        a["verdicts"] = (
            db.rows_to_list(await db.fetch("SELECT * FROM verdicts WHERE episode_id=$1 AND entity_id = ANY($2::text[]) ORDER BY created_at", episode_id, ids))
            if ids
            else []
        )
        a["flags"] = db.rows_to_list(await db.fetch("SELECT * FROM flags WHERE episode_id=$1 AND entity_id = ANY($2::text[])", episode_id, ids)) if ids else []
    return rows


@router.get("/episodes/{episode_id}/attacks/leaderboard")
async def attack_leaderboard(episode_id: str):
    rows = await db.fetch(
        "SELECT scheme_id, display_name, COUNT(*) AS attempts, SUM(amount_extracted) AS extracted, SUM(target_amount) AS targeted, "
        "COUNT(*) FILTER (WHERE outcome IN ('blocked','flagged')) AS caught, AVG(detected_day - day_launched) AS avg_latency "
        "FROM attacks WHERE episode_id=$1 GROUP BY 1,2 ORDER BY extracted DESC, MIN(day_launched), MIN(created_at), scheme_id, display_name",
        episode_id,
    )
    return db.rows_to_list(rows)


# ---------------- verdicts ----------------


@router.get("/episodes/{episode_id}/verdicts")
async def verdicts(
    episode_id: str, verdict: str | None = None, action: str | None = None, day: int | None = None, rule: str | None = None, limit: int = Query(200, le=2000)
):
    rows = await db.fetch(
        "SELECT v.*, i.origin AS entity_origin FROM verdicts v LEFT JOIN invoices i ON i.id=v.entity_id "
        "WHERE v.episode_id=$1 AND ($2::text IS NULL OR v.verdict=$2) AND ($3::text IS NULL OR v.action=$3) AND ($4::int IS NULL OR v.day=$4) "
        "AND ($5::text IS NULL OR v.rules_fired ? $5) ORDER BY v.created_at DESC LIMIT $6",
        episode_id,
        verdict,
        action,
        day,
        rule,
        limit,
    )
    return db.rows_to_list(rows)


@router.get("/episodes/{episode_id}/verdicts/rules")
async def rule_frequency(episode_id: str):
    """How often each blue rule fired, split by verdict and by whether the target was actually red."""
    rows = await db.fetch(
        "SELECT r AS rule, v.verdict, COALESCE(i.origin, e.origin, 'other') AS origin, COUNT(*) AS n "
        "FROM verdicts v CROSS JOIN LATERAL jsonb_array_elements_text(v.rules_fired) AS r "
        "LEFT JOIN invoices i ON i.id=v.entity_id LEFT JOIN expenses e ON e.id=v.entity_id "
        "WHERE v.episode_id=$1 GROUP BY 1,2,3 ORDER BY n DESC",
        episode_id,
    )
    return db.rows_to_list(rows)


@router.get("/episodes/{episode_id}/verdicts/confusion")
async def confusion(episode_id: str):
    """verdict × actual-origin matrix on money-moving actions. The honest measure of blue."""
    rows = await db.fetch(
        "SELECT v.verdict, COALESCE(i.origin, e.origin) AS origin, COUNT(*) AS n, COALESCE(SUM(v.amount),0) AS dollars "
        "FROM verdicts v LEFT JOIN invoices i ON i.id=v.entity_id LEFT JOIN expenses e ON e.id=v.entity_id "
        "WHERE v.episode_id=$1 AND v.action IN ('invoices.pay','expenses.pay','invoices.approve','vendor_changes.approve') GROUP BY 1,2",
        episode_id,
    )
    return db.rows_to_list(rows)


# ---------------- agents ----------------


@router.get("/episodes/{episode_id}/agents/activity")
async def agent_activity(episode_id: str):
    """Tool calls, mutations, blocks and credits per agent per day."""
    rows = await db.fetch(
        """
        SELECT a.agent, a.day,
          COUNT(*) AS calls,
          COUNT(*) FILTER (WHERE http_status < 300) AS ok,
          COUNT(*) FILTER (WHERE http_status = 403) AS blocked,
          COUNT(DISTINCT action) AS distinct_actions
        FROM audit_log a WHERE a.episode_id=$1 GROUP BY 1,2 ORDER BY 2,1
        """,
        episode_id,
    )
    credits = await db.fetch(
        "SELECT payload->>'agent' AS agent, day, "
        "SUM(CASE WHEN jsonb_typeof(payload->'factory_credits')='number' THEN (payload->>'factory_credits')::float END) AS credits, "
        "SUM(CASE WHEN jsonb_typeof(payload->'duration_sec')='number' THEN (payload->>'duration_sec')::float END) AS seconds "
        "FROM events WHERE episode_id=$1 AND type='turn.ended' GROUP BY 1,2",
        episode_id,
    )
    return {"activity": db.rows_to_list(rows), "turns": db.rows_to_list(credits)}


@router.get("/episodes/{episode_id}/agents/{agent}/thinking")
async def agent_thinking(episode_id: str, agent: str, day: int | None = None):
    """Concatenated thinking text per day for an agent — the 'what was it reasoning' panel."""
    rows = await db.fetch(
        "SELECT day, string_agg(payload->>'text', '' ORDER BY id) AS text FROM events WHERE episode_id=$1 AND agent=$2 AND type='agent.thinking' AND ($3::int IS NULL OR day=$3) GROUP BY day ORDER BY day",
        episode_id,
        agent,
        day,
    )
    return db.rows_to_list(rows)


# ---------------- compare ----------------


@router.get("/compare")
async def compare(a: str, b: str):
    """Two episodes side by side (intended: same seed, controller off vs enforce)."""
    ea, eb = await _ep(a), await _ep(b)
    sa, sb = await _score(a), await _score(b)
    ta, tb = await timeline(a), await timeline(b)
    aa, ab = await _compare_attacks(a), await _compare_attacks(b)
    return {
        "a": {"episode": ea, "score": sa, "timeline": ta, "attacks": aa},
        "b": {"episode": eb, "score": sb, "timeline": tb, "attacks": ab},
        "delta": {k: round(_n(sb.get(k)) - _n(sa.get(k)), 2) for k in ("dollars_extracted", "dollars_blocked", "false_positive_cost")},
    }


async def _compare_attacks(episode_id: str) -> list[dict[str, Any]]:
    keys = ("scheme_id", "outcome", "amount_extracted", "day_launched", "detected_day")
    if is_replay(episode_id):
        return [{k: a[k] for k in keys} for a in await _replay_attacks(episode_id)]
    return db.rows_to_list(
        await db.fetch(
            "SELECT scheme_id, outcome, amount_extracted, day_launched, detected_day FROM attacks WHERE episode_id=$1 ORDER BY day_launched, created_at, id",
            episode_id,
        )
    )


# ---------------- feed ----------------

CARD_TYPES = {
    "attack.launched",
    "attack.outcome",
    "gate.verdict",
    "escalation.opened",
    "escalation.resolved",
    "flag.raised",
    "vendor.frozen",
    "report.posted",
    "controller.changed",
    "day.started",
    "day.ended",
    "episode.ended",
    "score.updated",
}


@router.get("/episodes/{episode_id}/feed")
async def feed(episode_id: str, after_id: int = 0, limit: int = Query(200, le=2000), include_verdict_allows: bool = False):
    """Events pre-filtered to the ones that make UI cards, with headline/subline text already composed.
    Dev R: treat `headline`/`subline` as defaults you can override; raw payload is included."""
    rows = await db.fetch(
        "SELECT * FROM events WHERE episode_id=$1 AND id>$2 AND type = ANY($3::text[]) ORDER BY id LIMIT $4", episode_id, after_id, list(CARD_TYPES), limit
    )
    out = []
    for r in db.rows_to_list(rows):
        p = _d(r["payload"])
        t = r["type"]
        if t == "gate.verdict" and p.get("verdict") == "allow" and not include_verdict_allows:
            continue
        head, sub = t, ""
        if t == "attack.launched":
            head, sub = f"Attack: {p.get('display_name')}", f"{_s(p.get('story'))} Target ${_n(p.get('target_amount')):,.0f}."
        elif t == "attack.outcome":
            head, sub = (
                f"Attack {p.get('outcome')}",
                f"${_n(p.get('amount_extracted')):,.2f} extracted" + (f"; detected day {p['detected_day']}" if p.get("detected_day") is not None else ""),
            )
        elif t == "gate.verdict":
            head, sub = (
                f"{_s(p.get('verdict')).upper()} — {p.get('action')}",
                _s(p.get("reason")) + (f" (${_n(p.get('amount')):,.2f})" if _n(p.get("amount")) else ""),
            )
        elif t == "escalation.opened":
            head, sub = "Needs a human decision", f"{p.get('action')} ${_n(p.get('amount')):,.2f}: {_s(p.get('reason'))}"
        elif t == "escalation.resolved":
            head, sub = f"Human decided: {p.get('decision')}", f"by {p.get('by')}"
        elif t == "flag.raised":
            head, sub = f"Flag ({p.get('severity')}) on {p.get('entity_type')}", _s(p.get("reason"))
        elif t == "vendor.frozen":
            head, sub = "Vendor frozen", _s(p.get("reason"))
        elif t == "report.posted":
            head, sub = f"Controller report, day {p.get('day')}", "Open to read."
        elif t == "controller.changed":
            head, sub = f"Controller: {p.get('from')} → {p.get('to')}", ""
        elif t == "day.started":
            li = _d(p.get("legit_injected"))
            head, sub = (
                f"Day {p.get('day')} begins",
                f"{int(_n(li.get('invoices')))} invoices, {int(_n(li.get('purchase_orders')))} POs, {int(_n(li.get('expenses')))} expenses arrived.",
            )
        elif t == "day.ended":
            head = f"Day {p.get('day')} closed"
        elif t == "score.updated":
            head, sub = (
                "Score",
                f"${_n(p.get('dollars_extracted')):,.0f} stolen · ${_n(p.get('dollars_blocked')):,.0f} blocked · ${_n(p.get('false_positive_cost')):,.0f} FP cost",
            )
        elif t == "episode.ended":
            head = "Episode finished"
        out.append({**r, "headline": head, "subline": sub})
    return out


# ---------------- search ----------------


@router.get("/episodes/{episode_id}/search")
async def search(episode_id: str, q: str = Query(..., min_length=2), limit: int = Query(25, le=100)):
    like = f"%{q}%"
    vendors = db.rows_to_list(
        await db.fetch(
            "SELECT 'vendor' AS kind, id, name AS label, status FROM vendors WHERE episode_id=$1 AND (name ILIKE $2 OR id ILIKE $2) LIMIT $3",
            episode_id,
            like,
            limit,
        )
    )
    invoices = db.rows_to_list(
        await db.fetch(
            "SELECT 'invoice' AS kind, id, invoice_number AS label, status FROM invoices WHERE episode_id=$1 AND (invoice_number ILIKE $2 OR id ILIKE $2) LIMIT $3",
            episode_id,
            like,
            limit,
        )
    )
    employees = db.rows_to_list(
        await db.fetch(
            "SELECT 'employee' AS kind, id, name AS label, status FROM employees WHERE episode_id=$1 AND (name ILIKE $2 OR id ILIKE $2) LIMIT $3",
            episode_id,
            like,
            limit,
        )
    )
    verdicts_ = db.rows_to_list(
        await db.fetch(
            "SELECT 'verdict' AS kind, id, reason AS label, verdict AS status FROM verdicts WHERE episode_id=$1 AND reason ILIKE $2 LIMIT $3",
            episode_id,
            like,
            limit,
        )
    )
    return vendors + invoices + employees + verdicts_


@router.get("/episodes/{episode_id}/reports")
async def reports(episode_id: str):
    return db.rows_to_list(
        await db.fetch("SELECT id, day, posted_by, created_at, left(markdown, 200) AS preview FROM reports WHERE episode_id=$1 ORDER BY day", episode_id)
    )


@router.get("/episodes/{episode_id}/escalations")
async def escalations(episode_id: str):
    rows = await db.fetch(
        "SELECT e.*, v.action, v.amount, v.reason, v.entity_type, v.entity_id, v.rules_fired FROM escalations e JOIN verdicts v ON v.id=e.verdict_id WHERE e.episode_id=$1 ORDER BY e.opened_at",
        episode_id,
    )
    return db.rows_to_list(rows)
