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
  controls      — the controls assessment report: per control, per scheme, gaps, false positives
  agents        — activity stats per agent per day, credits burned
  compare       — two episodes (same seed, different controller mode) side by side
  lineages      — evolution report and playbook timeline of a lineage (app/evolution/report.py)
  feed          — events pre-digested into UI cards
  search        — free-text across vendors / invoices / employees / reasons

Replay episodes (`replay_*`, see control.py) have events but no ledger rows. For them snapshot's
score, timeline, attacks and compare are derived from events; feed, thinking and the `turns` half
of agents/activity are event-derived anyway. Everything else here is table-derived and is empty
(or zero, or 404 for entity trails) for a replay.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import db
from ..auth import bearer
from ..config import settings
from ..evolution import report as evo_report
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
          (SELECT COALESCE(SUM(amount),0) FROM payments p WHERE p.episode_id=$1 AND p.paid_day<=d.day AND p.origin_of_source='red' AND NOT (p.id = ANY($3::text[]))) AS extracted_cumulative,
          (SELECT COALESCE(SUM(i.amount),0) FROM invoices i WHERE i.episode_id=$1 AND i.origin='red' AND i.status IN ('blocked','rejected') AND i.status_day<=d.day) AS blocked_cumulative,
          (SELECT COUNT(*) FROM attacks a WHERE a.episode_id=$1 AND a.day_launched=d.day) AS attacks_launched,
          (SELECT COUNT(*) FROM flags f WHERE f.episode_id=$1 AND f.day=d.day) AS flags_raised
        FROM days d ORDER BY d.day
        """,
        episode_id,
        ep["current_day"],
        sorted(await score.misdirected_payments(episode_id)),  # bank_swap invoices paid to the real vendor: not extracted
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
    rows = await db.fetch("SELECT day, type, payload FROM events WHERE episode_id=$1 AND type IN ('attack.launched','attack.outcome') ORDER BY id", episode_id)
    return _attacks_from_events(episode_id, rows)


def _attacks_from_events(episode_id: str, rows: Any) -> list[dict[str, Any]]:
    """The attack rows `attack.launched`/`attack.outcome` events describe, in launch order. Other event types are ignored."""
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        if r["type"] not in ("attack.launched", "attack.outcome"):
            continue
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
    """Every escalation of the episode (any status) with what a judge needs to decide: the verdict
    (action, amount, reason, rules) and the entity behind it (vendor, invoice number, or the vendor
    change's field and new value)."""
    rows = await db.fetch(
        "SELECT e.*, v.action, v.amount, v.reason, v.entity_type, v.entity_id, v.rules_fired, "
        "  COALESCE(i.vendor_id, ch.vendor_id) AS vendor_id, COALESCE(vi.name, vc.name) AS vendor_name, "
        "  i.invoice_number, ch.field AS change_field, ch.old_value AS change_old_value, ch.new_value AS change_new_value, "
        "  ex.employee_id, ex.category AS expense_category "
        "FROM escalations e JOIN verdicts v ON v.id=e.verdict_id "
        "LEFT JOIN invoices i ON v.entity_type='invoice' AND i.id=v.entity_id LEFT JOIN vendors vi ON vi.id=i.vendor_id "
        "LEFT JOIN vendor_changes ch ON v.entity_type='vendor_change' AND ch.id=v.entity_id LEFT JOIN vendors vc ON vc.id=ch.vendor_id "
        "LEFT JOIN expenses ex ON v.entity_type='expense' AND ex.id=v.entity_id "
        "WHERE e.episode_id=$1 ORDER BY e.opened_at",
        episode_id,
    )
    return db.rows_to_list(rows)


# ---------------- lineages (docs/ARCHITECTURE.md, Evolution: Export and report) ----------------


@router.get("/lineages/{lineage_id}/timeline")
async def lineage_timeline(lineage_id: str):
    """Playbook versions (with structural diffs vs. their parent), generation scores and debrief counts,
    in logical time order. Partial while the lineage runs."""
    out = await evo_report.timeline(lineage_id)
    if out is None:
        raise HTTPException(404, "lineage not found")
    return out


@router.get("/lineages/{lineage_id}/report")
async def lineage_report(lineage_id: str):
    """The evolution report (`make evolution-report` writes this same document to report.json)."""
    out = await evo_report.report(lineage_id)
    if out is None:
        raise HTTPException(404, "lineage not found")
    return out


# ---------------- controls assessment (the report a finance team reads after a run) ----------------
#
# One document per episode: what each gate control did against the attacker and against legit work, what each red scheme
# got away with and why, what the false positives cost, and the ids to trace every number back to rows. Ground truth
# (which rows are red's) is behind every number, but the answer carries it only as words (`fraud` / `legit`, `on_fraud`,
# `on_legit`), never as an `origin`-named key: the frontend proxy hands it to a site viewer once the run has ended.
#
# Two gatherers feed one pure builder: `_control_facts` reads the ledger tables (live episodes), `_facts_from_events`
# reads the event stream (replays, and the frontend's mock fixture). In the event version a fraud entity is one red's
# `ledger.mutation` created, linked to the latest attack red launched that day (red_writes' own rule).

_FINAL_STATUSES = ("finished", "failed")
_ATTACK_OUTCOMES = ("extracted", "partial", "blocked", "flagged", "failed", "pending")
_ESC_DECISION = {"approve": "approved", "block": "blocked", "timeout": "timeout"}
_EVIDENCE_CAP = 200


def _r2(x: float) -> float:
    return round(float(x), 2) + 0.0  # + 0.0: never -0.0


def _amount(x: Any) -> float:
    return float(x) if isinstance(x, int | float) and not isinstance(x, bool) else 0.0


def _rules(x: Any) -> list[str]:
    return [r for r in x if isinstance(r, str) and r] if isinstance(x, list) else []


async def _control_facts(episode_id: str, day: int) -> dict[str, Any]:
    """Ledger-table facts for build_controls_report. Attack outcomes and amounts are the live evaluation
    (score.live_attacks), not the stored columns: those are only as fresh as the run's last end_of_day, and a scoring
    change since (e.g. #207's bank_swap decoys) would leave them disagreeing with score.compute."""
    attack_rows = await db.fetch("SELECT * FROM attacks WHERE episode_id=$1 ORDER BY day_launched, created_at, id", episode_id)
    live = await score.live_attacks(episode_id, day)
    attacks = [
        {
            "id": a["id"],
            "scheme_id": a["scheme_id"],
            "display_name": a["display_name"],
            "day_launched": a["day_launched"],
            "target_amount": float(a["target_amount"]),
            "outcome": live[a["id"]]["outcome"],
            "amount_extracted": float(live[a["id"]]["amount_extracted"]),
            "detected_day": live[a["id"]]["detected_day"],
        }
        for a in attack_rows
    ]
    # as_of_reveal: the same attribution score.compute uses, so the money split below adds up to dollars_extracted
    all_changes, changes_by_attack = await score.attributed_changes(episode_id, attack_rows, as_of_reveal=True)
    fraud: dict[str, str | None] = {}
    paid: dict[str, set[str]] = defaultdict(set)

    def mark(entity_id: str, attack_id: str | None) -> None:
        if fraud.get(entity_id) is None:
            fraud[entity_id] = attack_id

    red_items = await db.fetch(
        "SELECT id, attack_id, status, vendor_id AS owner FROM invoices WHERE episode_id=$1 AND origin='red' "
        "UNION ALL SELECT id, attack_id, status, employee_id FROM expenses WHERE episode_id=$1 AND origin='red' ORDER BY id",
        episode_id,
    )
    for r in red_items:
        mark(r["id"], r["attack_id"])
        if r["status"] == "paid" and r["attack_id"]:
            paid[r["attack_id"]].add(r["id"])
    owners = {r["owner"]: r["attack_id"] for r in red_items if r["attack_id"]}
    for r in await db.fetch(
        "SELECT id FROM vendors WHERE episode_id=$1 AND origin='red' UNION ALL SELECT id FROM employees WHERE episode_id=$1 AND origin='red'", episode_id
    ):
        mark(r["id"], owners.get(r["id"]))
    # red vendor changes, the sim invoices stopped while a red bank swap was live (scored as caught, never as a false
    # positive) and the sim invoices whose payment the swap diverted (scored as extracted)
    for aid, chs in changes_by_attack.items():
        for ch in chs:
            mark(ch["id"], aid)
            for i in ch["stopped"]:
                mark(i, aid)
            for i in ch["paid_invoices"]:
                mark(i, aid)
                paid[aid].add(i)
    for ch in all_changes:
        mark(ch["id"], None)
        for i in ch["stopped"] | ch["paid_invoices"]:
            mark(i, None)

    sim_items = {
        r["id"]: {"entity_type": r["t"], "amount": float(r["amount"]), "ended_blocked": r["status"] == "blocked"}
        for r in await db.fetch(
            "SELECT 'invoice' AS t, id, amount, status FROM invoices WHERE episode_id=$1 AND origin='sim' "
            "UNION ALL SELECT 'expense', id, amount, status FROM expenses WHERE episode_id=$1 AND origin='sim' "
            "UNION ALL SELECT 'vendor_change', id, 0::numeric, status FROM vendor_changes WHERE episode_id=$1 AND origin='sim'",
            episode_id,
        )
    }
    # legit = sim items that are no part of an attack (for the control matrix's fraud/legit split). The false-positive
    # pool is score.compute's own: every sim item except invoices stopped while a red swap was live (a diverted invoice
    # stays in it), so false_positives agrees with the score's false_positive_cost and legit_blocked in every mode.
    legit = {k: v for k, v in sim_items.items() if k not in fraud}
    not_fp = {i for ch in all_changes for i in ch["stopped"]}
    fp_pool = {k: v for k, v in sim_items.items() if not (v["entity_type"] == "invoice" and k in not_fp)}
    verdict_rows = await db.fetch(
        "SELECT id, day, action, entity_type, entity_id, amount, verdict, reason, rules_fired, enforced FROM verdicts WHERE episode_id=$1 ORDER BY created_at, id",
        episode_id,
    )
    verdicts = [
        {
            "id": v["id"],
            "day": v["day"],
            "action": v["action"],
            "entity_type": v["entity_type"],
            "entity_id": v["entity_id"],
            "amount": float(v["amount"]) if v["amount"] is not None else None,
            "verdict": v["verdict"],
            "reason": v["reason"],
            "rules": _rules(v["rules_fired"]),
            "enforced": bool(v["enforced"]),
        }
        for v in verdict_rows
    ]
    escalations = {
        r["verdict_id"]: {"id": r["id"], "status": r["status"]}
        for r in await db.fetch("SELECT id, verdict_id, status FROM escalations WHERE episode_id=$1", episode_id)
    }
    flags = db.rows_to_list(await db.fetch("SELECT id, day, entity_type, entity_id, severity FROM flags WHERE episode_id=$1 ORDER BY day, id", episode_id))
    frozen = {
        r["vid"]
        for r in await db.fetch(
            "SELECT payload->>'vendor_id' AS vid FROM events WHERE episode_id=$1 AND type='vendor.frozen' AND payload ? 'vendor_id' "
            "UNION SELECT id FROM vendors WHERE episode_id=$1 AND status='frozen'",
            episode_id,
        )
        if r["vid"]
    }
    reports = int(await db.fetchval("SELECT COUNT(*) FROM reports WHERE episode_id=$1", episode_id))

    # Where the lost money landed. score.compute's dollars_extracted = payments of red-origin documents + payments a red
    # bank swap diverted (attributed, as of reveal). Attacker-controlled accounts: a red vendor's or red employee's
    # bank_account, or the new_value of an approved red bank_account change. Everything else is a real party's account.
    attacker_accounts = {
        r["acct"]
        for r in await db.fetch(
            "SELECT bank_account AS acct FROM vendors WHERE episode_id=$1 AND origin='red' "
            "UNION SELECT bank_account FROM employees WHERE episode_id=$1 AND origin='red' "
            "UNION SELECT new_value FROM vendor_changes WHERE episode_id=$1 AND origin='red' AND field='bank_account' AND status='approved'",
            episode_id,
        )
    }
    # score.compute's own exclusion: a bank_swap decoy paid to the hijacked vendor's real account is not extracted
    misdirected: set[str] = set()
    for aid, chs in changes_by_attack.items():
        misdirected |= set(await score._misdirected(episode_id, aid, chs))
    money = [
        {"amount": float(p["amount"]), "attack_id": p["attack_id"], "to_attacker": p["to_account"] in attacker_accounts}
        for p in await db.fetch(
            "SELECT p.id, p.amount, p.to_account, COALESCE(i.attack_id, e.attack_id) AS attack_id FROM payments p "
            "LEFT JOIN invoices i ON i.id=p.invoice_id LEFT JOIN expenses e ON e.id=p.expense_id "
            "WHERE p.episode_id=$1 AND p.origin_of_source='red' ORDER BY p.id",
            episode_id,
        )
        if p["id"] not in misdirected
    ]
    swap_paid: dict[str, str] = {}  # payment id -> attack, each payment once (score.compute's swap_payments)
    for aid, chs in changes_by_attack.items():
        for ch in chs:
            for pid, amt in ch["payments"].items():
                if pid not in swap_paid:
                    swap_paid[pid] = aid
                    money.append({"amount": amt, "attack_id": aid, "to_attacker": True})  # paid to the swapped-in account
    return {
        "source": "ledger",
        "attacks": attacks,
        "fraud": fraud,
        "paid": paid,
        "legit": legit,
        "verdicts": verdicts,
        "escalations": escalations,
        "flags": flags,
        "frozen": frozen,
        "reports": reports,
        "money": money,
        "fp_pool": fp_pool,
    }


_CONTROL_EVENT_TYPES = [
    "attack.launched",
    "attack.outcome",
    "ledger.mutation",
    "gate.verdict",
    "escalation.opened",
    "escalation.resolved",
    "flag.raised",
    "vendor.frozen",
    "report.posted",
]


def _facts_from_events(episode_id: str, rows: Any) -> dict[str, Any]:
    """Event-stream facts for build_controls_report (`rows`: {day, type, payload} in id order). Without ledger rows a
    fraud entity is one red's ledger.mutation created; legit = every other entity a verdict touched."""
    rows = list(rows)
    attacks = [
        {
            "id": a["id"],
            "scheme_id": _s(a["scheme_id"]) or "unknown",
            "display_name": _s(a["display_name"]) or _s(a["scheme_id"]) or "unknown",
            "day_launched": a["day_launched"],
            "target_amount": _amount(a["target_amount"]),
            "outcome": a["outcome"] if a["outcome"] in _ATTACK_OUTCOMES else "pending",
            "amount_extracted": _amount(a["amount_extracted"]),
            "detected_day": a["detected_day"] if isinstance(a["detected_day"], int) else None,
        }
        for a in _attacks_from_events(episode_id, rows)
    ]
    fraud: dict[str, str | None] = {}
    paid: dict[str, set[str]] = defaultdict(set)
    latest_attack: dict[int, str] = {}
    verdicts: list[dict[str, Any]] = []
    escalations: dict[str, dict[str, Any]] = {}
    esc_verdict: dict[str, str] = {}
    flags: list[dict[str, Any]] = []
    frozen: set[str] = set()
    reports = 0
    for r in rows:
        t, p, day = r["type"], _d(r["payload"]), r["day"]
        if t == "attack.launched" and _s(p.get("attack_id")):
            latest_attack[day] = p["attack_id"]
        elif t == "ledger.mutation" and _s(p.get("entity_id")):
            eid = p["entity_id"]
            if p.get("agent") == "red":
                fraud.setdefault(eid, latest_attack.get(day))
            elif p.get("action") in ("invoices.pay", "expenses.pay") and fraud.get(eid):
                paid[fraud[eid]].add(eid)  # type: ignore[index]
        elif t == "gate.verdict" and _s(p.get("verdict_id")) and p.get("verdict") in ("allow", "block", "escalate"):
            verdicts.append(
                {
                    "id": p["verdict_id"],
                    "day": day,
                    "action": _s(p.get("action")),
                    "entity_type": _s(p.get("entity_type")) or None,
                    "entity_id": _s(p.get("entity_id")) or None,
                    "amount": _amount(p.get("amount")) if p.get("amount") is not None else None,
                    "verdict": p["verdict"],
                    "reason": _s(p.get("reason")),
                    "rules": _rules(p.get("rules_fired")),
                    "enforced": p.get("enforced") is not False,
                }
            )
        elif t == "escalation.opened" and _s(p.get("verdict_id")) and _s(p.get("escalation_id")):
            escalations[p["verdict_id"]] = {"id": p["escalation_id"], "status": "open"}
            esc_verdict[p["escalation_id"]] = p["verdict_id"]
        elif t == "escalation.resolved" and p.get("escalation_id") in esc_verdict:
            escalations[esc_verdict[p["escalation_id"]]]["status"] = _ESC_DECISION.get(_s(p.get("decision")), "open")
        elif t == "flag.raised" and _s(p.get("entity_id")):
            flags.append(
                {
                    "id": _s(p.get("flag_id")),
                    "day": day,
                    "entity_type": _s(p.get("entity_type")),
                    "entity_id": p["entity_id"],
                    "severity": _s(p.get("severity")),
                }
            )
        elif t == "vendor.frozen" and _s(p.get("vendor_id")):
            frozen.add(p["vendor_id"])
        elif t == "report.posted":
            reports += 1
    legit: dict[str, dict[str, Any]] = {}
    for v in verdicts:
        eid = v["entity_id"]
        if eid and eid not in fraud:
            item = legit.setdefault(eid, {"entity_type": v["entity_type"] or "", "amount": 0.0, "ended_blocked": False})
            item["amount"] = max(item["amount"], v["amount"] or 0.0)
    return {
        "source": "events",
        "attacks": attacks,
        "fraud": fraud,
        "paid": paid,
        "legit": legit,
        "verdicts": verdicts,
        "escalations": escalations,
        "flags": flags,
        "frozen": frozen,
        "reports": reports,
        "money": None,  # payee accounts are not in the event stream: the split is unknown for a replay
    }


def _effect(blocks: int, escalations: int, notes: int) -> str:
    """The control's typical policy: what it did most often (ties go to the stronger action)."""
    return max((blocks, 2, "block"), (escalations, 1, "escalate"), (notes, 0, "note"))[2]


def build_controls_report(ep: dict[str, Any], sc: dict[str, Any], f: dict[str, Any], *, fp_rate: float, fp_flat: float) -> dict[str, Any]:
    """The controls assessment document (pure: everything comes in through `f`, see _control_facts)."""
    attacks: list[dict[str, Any]] = f["attacks"]
    fraud: dict[str, str | None] = f["fraud"]
    legit: dict[str, dict[str, Any]] = f["legit"]
    escalations: dict[str, dict[str, Any]] = f["escalations"]
    by_id = {a["id"]: a for a in attacks}
    money: list[dict[str, Any]] | None = f.get("money")

    def split(attack_ids: set[str] | None) -> tuple[float | None, float | None]:
        """(to attacker-controlled accounts, to real parties) for these attacks' payments (None = every payment)."""
        if money is None:
            return None, None
        rows = [m for m in money if attack_ids is None or m["attack_id"] in attack_ids]
        return _r2(sum(m["amount"] for m in rows if m["to_attacker"])), _r2(sum(m["amount"] for m in rows if not m["to_attacker"]))

    def parts(lost: float, attack_ids: set[str] | None) -> tuple[float | None, float | None]:
        """(to attacker accounts, to real parties) of `lost`: the real-party part is the rest, so the two always add up."""
        to_attacker = split(attack_ids)[0]
        return (None, None) if to_attacker is None else (to_attacker, _r2(lost - to_attacker))

    side = {**{e: "legit" for e in legit}, **{e: "fraud" for e in fraud}}

    verdicts_on: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for v in f["verdicts"]:
        if v["entity_id"]:
            verdicts_on[v["entity_id"]].append(v)
    flags_on: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fl in f["flags"]:
        flags_on[fl["entity_id"]].append(fl)

    # ---- controls: one row per rule id the gate fired ----
    rows: dict[str, dict[str, Any]] = {}
    for v in f["verdicts"]:
        eid, kind = v["entity_id"], side.get(v["entity_id"] or "", "other")
        aid = fraud.get(eid) if eid else None
        for rule in dict.fromkeys(v["rules"]):
            c = rows.setdefault(
                rule,
                {
                    "control_id": rule,
                    "fired": 0,
                    "blocks": 0,
                    "escalations": 0,
                    "notes": 0,
                    "_fraud": {},
                    "_legit": {},
                    "_fraud_stop": set(),
                    "_legit_stop": set(),
                    "_schemes": {},
                    "_ids": [],
                },
            )
            c["fired"] += 1
            c[{"block": "blocks", "escalate": "escalations"}.get(v["verdict"], "notes")] += 1
            if len(c["_ids"]) < _EVIDENCE_CAP:
                c["_ids"].append(v["id"])
            if kind in ("fraud", "legit") and eid:
                c[f"_{kind}"][eid] = max(c[f"_{kind}"].get(eid, 0.0), v["amount"] or 0.0)
                if v["verdict"] != "allow":
                    c[f"_{kind}_stop"].add(eid)
            if aid in by_id:
                c["_schemes"][by_id[aid]["scheme_id"]] = None
    controls = []
    for c in rows.values():
        out = {k: v for k, v in c.items() if not k.startswith("_")}
        for kind in ("fraud", "legit"):
            out[f"on_{kind}"] = {"n": len(c[f"_{kind}"]), "dollars": _r2(sum(c[f"_{kind}"].values())), "stopped": len(c[f"_{kind}_stop"])}
        out["schemes"] = list(c["_schemes"])
        out["effect"] = _effect(c["blocks"], c["escalations"], c["notes"])
        out["learned"] = c["control_id"].startswith("learned:")
        out["verdict_ids"] = c["_ids"]
        controls.append(out)
    controls.sort(key=lambda c: (-c["on_fraud"]["stopped"], -c["on_fraud"]["n"], -c["fired"], c["control_id"]))

    # ---- schemes: one row per red scheme attempted, in first-launch order ----
    entities: dict[str, set[str]] = defaultdict(set)
    for eid, aid in fraud.items():
        if aid:
            entities[aid].add(eid)
    groups: dict[str, list[dict[str, Any]]] = {}
    for a in attacks:
        groups.setdefault(a["scheme_id"], []).append(a)
    schemes, gaps, evidence = [], [], []
    for scheme_id, atks in groups.items():
        ents = set().union(*(entities[a["id"]] for a in atks))
        vs = sorted((v for e in ents for v in verdicts_on.get(e, [])), key=lambda v: (v["day"], v["id"]))
        fls = sorted((fl for e in ents for fl in flags_on.get(e, [])), key=lambda fl: (fl["day"], fl["id"]))
        esc = [escalations[v["id"]] for v in vs if v["id"] in escalations]
        caught_by = list(dict.fromkeys(r for v in vs if v["verdict"] != "allow" for r in v["rules"]))
        noted_by = list(dict.fromkeys(r for v in vs if v["verdict"] == "allow" for r in v["rules"]))
        lat = [a["detected_day"] - a["day_launched"] for a in atks if a["detected_day"] is not None]
        outcomes = dict.fromkeys(_ATTACK_OUTCOMES, 0)
        for a in atks:
            outcomes[a["outcome"]] = outcomes.get(a["outcome"], 0) + 1
        # lost per scheme: with ledger facts, the scheme's payments on score.compute's basis (so the rows reconcile with
        # the top-level lost); for a replay, the attacks' recorded amounts
        ids_here = {a["id"] for a in atks}
        extracted = _r2(sum(m["amount"] for m in money if m["attack_id"] in ids_here) if money is not None else sum(a["amount_extracted"] for a in atks))
        to_attacker, to_real = parts(extracted, {a["id"] for a in atks})
        frozen_here = sorted(ents & f["frozen"])
        row = {
            "scheme_id": scheme_id,
            "display_name": atks[0]["display_name"],
            "attempts": len(atks),
            "first_day": min(a["day_launched"] for a in atks),
            "targeted": _r2(sum(a["target_amount"] for a in atks)),
            "extracted": extracted,
            "lost": extracted,
            "to_attacker_accounts": to_attacker,
            "to_real_parties": to_real,
            "outcomes": outcomes,
            "caught_by": caught_by,
            "noted_by": noted_by,
            "flags": len(fls),
            "vendors_frozen": len(frozen_here),
            "escalations": {s: sum(1 for e in esc if e["status"] == s) for s in ("approved", "blocked", "timeout", "open")},
            "detection_latency_days": round(sum(lat) / len(lat), 2) if lat else None,
        }
        schemes.append(row)
        evidence.append(
            {
                "scheme_id": scheme_id,
                "attack_ids": [a["id"] for a in atks],
                "entity_ids": sorted(ents)[:_EVIDENCE_CAP],
                "verdict_ids": [v["id"] for v in vs][:_EVIDENCE_CAP],
                "escalation_ids": [e["id"] for e in esc],
                "flag_ids": [fl["id"] for fl in fls if fl["id"]],
            }
        )
        if extracted > 0:
            paid_ents = set().union(*(f["paid"].get(a["id"], set()) for a in atks)) or ents
            pv = [v for e in paid_ents for v in verdicts_on.get(e, [])]
            if any(escalations.get(v["id"], {}).get("status") == "approved" for v in pv):
                why = "escalation approved"
            elif any(v["verdict"] != "allow" and not v["enforced"] for v in pv):
                why = "not enforced"
            elif any(v["verdict"] == "allow" and v["rules"] for v in pv):
                why = "note only"
            elif fls or frozen_here:
                why = "audit only"
            else:
                why = "no control fired"
            gaps.append(
                {
                    "scheme_id": scheme_id,
                    "display_name": row["display_name"],
                    "extracted": extracted,
                    "why": why,
                    "controls_on_paid": list(dict.fromkeys(r for v in pv for r in v["rules"])),
                    "caught_elsewhere": caught_by,
                    "audit_detected": bool(fls or frozen_here),
                    "paid_entity_ids": sorted(paid_ents)[:_EVIDENCE_CAP],
                }
            )
    gaps.sort(key=lambda g: -g["extracted"])

    # ---- false positives: each legit item once, by its worst outcome (score.compute's rule) ----
    fp_items = []
    for eid, item in f.get("fp_pool", legit).items():
        vs = verdicts_on.get(eid, [])
        stops = [v for v in vs if v["verdict"] != "allow"]
        blocked = (
            item["ended_blocked"]
            or any(v["verdict"] == "block" for v in vs)
            or any(escalations.get(v["id"], {}).get("status") in ("blocked", "timeout") for v in vs)
        )
        escalated = any(v["verdict"] == "escalate" for v in vs)
        if not (blocked or escalated):
            continue
        fp_items.append(
            {
                "entity_type": item["entity_type"],
                "entity_id": eid,
                "amount": _r2(item["amount"]),
                "verdict": "block" if blocked else "escalate",
                "rules": list(dict.fromkeys(r for v in stops for r in v["rules"])),
                "reason": stops[-1]["reason"] if stops else "ended blocked",
                "day": min((v["day"] for v in stops), default=None),
                "enforced": any(v["enforced"] for v in stops) if stops else True,
                "cost": _r2(item["amount"] * fp_rate + fp_flat if blocked else fp_flat),
                "verdict_ids": [v["id"] for v in stops],
            }
        )
    fp_items.sort(key=lambda i: (-i["cost"], i["entity_id"]))

    status = ep.get("status")
    lost = _r2(_amount(sc.get("dollars_extracted")))
    lost_parts = parts(lost, None)
    gate = {k: sum(1 for v in f["verdicts"] if v["verdict"] == k) for k in ("allow", "block", "escalate")}
    gate["total"] = len(f["verdicts"])
    gate["escalations"] = {s: sum(1 for e in escalations.values() if e["status"] == s) for s in ("approved", "blocked", "timeout", "open")}
    return {
        "episode": {
            k: ep.get(k)
            for k in ("id", "seed", "controller_mode", "days", "status", "current_day", "lineage_id", "generation", "created_at", "started_at", "finished_at")
        },
        "final": status in _FINAL_STATUSES,
        "source": f["source"],
        "score": sc,
        # money lost to fraud (= score.dollars_extracted) by where it landed; None for a replay (no payee accounts)
        "lost": lost,
        "to_attacker_accounts": lost_parts[0],
        "to_real_parties": lost_parts[1],
        # lost money no scheme row accounts for (a red payment with no attack_id: red paid before declaring an attack),
        # so the scheme table reconciles: sum(schemes[].lost) + unattributed == lost
        "unattributed": _r2(max(0.0, lost - sum(s["lost"] for s in schemes))),
        "totals": {
            "attempted": _r2(sum(a["target_amount"] for a in attacks)),
            "extracted": _r2(_amount(sc.get("dollars_extracted"))),
            "blocked": _r2(_amount(sc.get("dollars_blocked"))),
            "attacks": len(attacks),
            "schemes": len(schemes),
            "schemes_with_loss": len(gaps),
            "controls_seen": len(controls),
        },
        "gate": gate,
        "controls": controls,
        "schemes": schemes,
        "gaps": gaps,
        "false_positives": {
            "cost": _r2(_amount(sc.get("false_positive_cost"))),
            "legit_blocked": sum(1 for i in fp_items if i["verdict"] == "block"),
            "legit_escalated": sum(1 for i in fp_items if i["verdict"] == "escalate"),
            "total_items": len(fp_items),
            "items": fp_items[:50],
            "penalty": {"rate": fp_rate, "flat": fp_flat},
        },
        "audit": {
            "flags_raised": len(f["flags"]),
            "flags_on_fraud": sum(1 for fl in f["flags"] if fl["entity_id"] in fraud),
            "flags_on_legit": sum(1 for fl in f["flags"] if fl["entity_id"] in legit),
            "vendors_frozen": len(f["frozen"]),
            "fraud_vendors_frozen": len(f["frozen"] & set(fraud)),
            "reports": f["reports"],
        },
        "evidence": evidence,
    }


@router.get("/episodes/{episode_id}/controls")
async def controls_report(episode_id: str):
    """Controls assessment for an episode: per gate control (what it fired on, fraud vs legit, its effect), per red
    scheme (attempts, outcomes, which controls caught it, detection latency), gaps (schemes that extracted money and
    why), false positives (cost, items), blue's audit activity and evidence ids. Money in dollars. Money lost to fraud
    (`lost` = score.dollars_extracted, and per scheme) is split by where it landed: `to_attacker_accounts` (a red
    vendor's/employee's account or an approved red bank change's new account) vs `to_real_parties` (an overpayment to a
    real vendor or employee on a fraudulent document); both null for a replay. `final` = the run has
    ended (status finished/failed); the frontend serves it to site viewers only then. A replay is derived from its events."""
    ep = await _ep(episode_id)
    if is_replay(episode_id):
        rows = await db.fetch(
            "SELECT day, type, payload FROM events WHERE episode_id=$1 AND type = ANY($2::text[]) ORDER BY id", episode_id, _CONTROL_EVENT_TYPES
        )
        facts = _facts_from_events(episode_id, rows)
    else:
        facts = await _control_facts(episode_id, ep["current_day"])
    return build_controls_report(ep, await _score(episode_id), facts, fp_rate=settings.fp_penalty_rate, fp_flat=settings.fp_flat_penalty)
