"""Scoring + attack outcome resolution. Owner: Dev Ad.

Ground truth comes from provenance (origin / attack_id) that agents never see.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .. import db
from ..config import settings
from ..events import bus


def _live(col: str, lo: str, hi: str) -> str:
    """A red bank_account change is live from its resolved_day (lo) until the vendor's next approved
    bank_account change of any origin (hi; NULL = still live)."""
    return f"{col} >= {lo} AND ({hi}::int IS NULL OR {col} < {hi})"


# Payments diverted to the swapped account while it was live. Red-origin invoices are excluded:
# they are already scored through their own attack_id / origin_of_source.
_SWAP_PAYMENTS_SQL = (
    "SELECT p.id, p.invoice_id, p.amount FROM payments p JOIN invoices i ON i.id=p.invoice_id "
    "WHERE p.episode_id=$1 AND i.vendor_id=$2 AND p.to_account=$3 AND p.origin_of_source <> 'red' AND " + _live("p.paid_day", "$4", "$5")
)

# Non-red invoices of the swapped vendor the controller stopped while the swap was live (caught at
# pay time): a block/escalate verdict, or status blocked/rejected, inside the window.
_SWAP_STOPPED_SQL = (
    "SELECT i.id, i.amount, i.status FROM invoices i WHERE i.episode_id=$1 AND i.vendor_id=$2 AND i.origin <> 'red' AND ("
    "  (i.status IN ('blocked','rejected') AND " + _live("i.status_day", "$3", "$4") + ")"
    "  OR EXISTS (SELECT 1 FROM verdicts v WHERE v.episode_id=$1 AND v.entity_id=i.id AND v.verdict IN ('block','escalate') AND "
    + _live("v.day", "$3", "$4")
    + "))"
)


async def _linked_attacks(episode_id: str) -> set[str]:
    """Attacks that have at least one invoice/expense row linked via attack_id."""
    rows = await db.fetch(
        "SELECT attack_id FROM invoices WHERE episode_id=$1 AND attack_id IS NOT NULL UNION SELECT attack_id FROM expenses WHERE episode_id=$1 AND attack_id IS NOT NULL",
        episode_id,
    )
    return {r["attack_id"] for r in rows}


async def _red_changes(episode_id: str) -> list[dict[str, Any]]:
    """Every origin='red' vendor_change, resolved against ledger state.

    Each dict gets:
      payments  {payment_id: amount}  diverted to the swapped account while it was live
      paid_invoices  {invoice_id}     the invoices behind those payments
      stopped   {invoice_id}          the vendor's non-red invoices stopped while the swap was live
      blocked_invoices {invoice_id: amount}  the subset of `stopped` that ended blocked/rejected
      state     blocked | pending | extracted | done
    """
    changes = await db.fetch(
        "SELECT ch.*, v.status AS vendor_status, ("
        "  SELECT MIN(n.resolved_day) FROM vendor_changes n WHERE n.episode_id=ch.episode_id AND n.vendor_id=ch.vendor_id "
        "  AND n.field='bank_account' AND n.status='approved' AND n.resolved_day > ch.resolved_day"
        ") AS next_resolved_day "
        "FROM vendor_changes ch JOIN vendors v ON v.id=ch.vendor_id WHERE ch.episode_id=$1 AND ch.origin='red'",
        episode_id,
    )
    out: list[dict[str, Any]] = []
    for ch in changes:
        d = dict(ch)
        d["payments"], d["paid_invoices"], d["stopped"], d["blocked_invoices"] = {}, set(), set(), {}
        swap = d["status"] == "approved" and d["field"] == "bank_account" and d["resolved_day"] is not None
        if swap:
            # approve_change writes vendors.bank_account=new_value and resolved_day=<approval day>
            lo, hi = d["resolved_day"], d["next_resolved_day"]
            for p in await db.fetch(_SWAP_PAYMENTS_SQL, episode_id, d["vendor_id"], d["new_value"], lo, hi):
                d["payments"][p["id"]] = float(p["amount"])
                d["paid_invoices"].add(p["invoice_id"])
            for i in await db.fetch(_SWAP_STOPPED_SQL, episode_id, d["vendor_id"], lo, hi):
                d["stopped"].add(i["id"])
                if i["status"] in ("blocked", "rejected"):
                    d["blocked_invoices"][i["id"]] = float(i["amount"])
        if d["status"] in ("blocked", "rejected") or d["vendor_status"] == "frozen" or d["blocked_invoices"]:
            d["state"] = "blocked"  # stopped at the change, by a freeze, or at pay time
        elif d["status"] == "pending":
            d["state"] = "pending"
        elif swap:
            d["state"] = "extracted" if d["payments"] else "pending"  # approved, waiting for the next payment run
        else:
            d["state"] = "done"  # approved non-bank change: no money moves through it
        out.append(d)
    return out


def _attribute(changes: list[dict[str, Any]], attacks: list[Any], linked: set[str]) -> dict[str, list[dict[str, Any]]]:
    """Attribute red vendor_changes to attacks.

    A change with `attack_id` set (red_writes links every red change to the latest attack red had
    declared that day when it made the change) belongs to that attack, whatever day it was made or
    resolved and whatever else launched since.

    Fallback, ONLY for rows with NULL `attack_id` (legacy rows from before the column existed, or a
    change red made before declaring any attack that day): a same-day heuristic. Such a change
    belongs to the attacks launched on its `requested_day`; when several launched that day, it
    goes to the ones with no linked invoice/expense rows, and only if every attack that day has
    rows does it go to all of them. Two change-only attacks on one day therefore share each
    other's NULL-linked changes, and a NULL-linked change on a day with no attack is attributed to
    nobody.
    """
    by_day: dict[int, list[str]] = defaultdict(list)
    for a in attacks:
        by_day[a["day_launched"]].append(a["id"])
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ch in changes:
        if ch.get("attack_id"):
            out[ch["attack_id"]].append(ch)
            continue
        day_attacks = by_day.get(ch["requested_day"])
        if not day_attacks:
            continue
        for aid in [aid for aid in day_attacks if aid not in linked] or day_attacks:
            out[aid].append(ch)
    return out


async def resolve_attacks(episode_id: str, day: int) -> list[dict[str, Any]]:
    """Update attacks.outcome / amount_extracted / detected_day from ledger state. Returns changed attacks."""
    changed: list[dict[str, Any]] = []
    attacks = await db.fetch("SELECT * FROM attacks WHERE episode_id=$1", episode_id)
    red_changes = _attribute(await _red_changes(episode_id), attacks, await _linked_attacks(episode_id))
    for a in attacks:
        aid = a["id"]
        rows = await db.fetch(
            "SELECT 'invoice' AS kind, id, vendor_id AS owner_id, amount, status, status_day FROM invoices WHERE attack_id=$1 "
            "UNION ALL SELECT 'expense', id, employee_id, amount, status, NULL FROM expenses WHERE attack_id=$1",
            aid,
        )
        chs = red_changes.get(aid, [])
        entities = bool(rows or chs)
        swap_payments = {pid: amt for ch in chs for pid, amt in ch["payments"].items()}  # each payment once
        extracted = sum(float(r["amount"]) for r in rows if r["status"] == "paid") + sum(swap_payments.values())
        blocked = [r for r in rows if r["status"] in ("blocked", "rejected")] + [ch for ch in chs if ch["state"] == "blocked"]
        pending = [r for r in rows if r["status"] in ("pending", "matched", "approved")] + [ch for ch in chs if ch["state"] == "pending"]

        # detection: earliest block verdict or flag touching the attack's entities, on or after launch
        ids = [r["id"] for r in rows] + [r["owner_id"] for r in rows]
        for ch in chs:
            ids += [ch["id"], ch["vendor_id"], *ch["stopped"]]
        detected_day = None
        if ids:
            detected_day = await db.fetchval(
                "SELECT MIN(d) FROM ("
                "  SELECT day AS d FROM verdicts WHERE episode_id=$1 AND verdict IN ('block','escalate') AND entity_id = ANY($2::text[]) AND day >= $3 "
                "  UNION ALL SELECT day FROM flags WHERE episode_id=$1 AND entity_id = ANY($2::text[]) AND day >= $3"
                ") x",
                episode_id,
                ids,
                a["day_launched"],
            )
        frozen = await db.fetchval("SELECT COUNT(*) FROM vendors v JOIN invoices i ON i.vendor_id=v.id WHERE i.attack_id=$1 AND v.status='frozen'", aid)

        if entities and not pending:
            if extracted > 0 and (blocked or frozen):
                outcome = "partial"
            elif extracted > 0:
                outcome = "extracted"
            elif blocked or frozen:
                outcome = "blocked"
            else:
                outcome = "failed"
        elif extracted > 0:
            outcome = "partial" if (blocked or frozen or pending) else "extracted"
        elif detected_day is not None:
            outcome = "flagged"
        else:
            outcome = "pending" if entities else ("failed" if a["day_launched"] < day else "pending")

        if outcome != a["outcome"] or float(a["amount_extracted"]) != extracted or a["detected_day"] != detected_day:
            await db.execute("UPDATE attacks SET outcome=$2, amount_extracted=$3, detected_day=$4 WHERE id=$1", aid, outcome, extracted, detected_day)
            changed.append({"attack_id": aid, "scheme_id": a["scheme_id"], "outcome": outcome, "amount_extracted": extracted, "detected_day": detected_day})
    return changed


async def compute(episode_id: str) -> dict[str, Any]:
    extracted = float(await db.fetchval("SELECT COALESCE(SUM(amount),0) FROM payments WHERE episode_id=$1 AND origin_of_source='red'", episode_id))
    blocked_amt = float(
        await db.fetchval(
            "SELECT COALESCE(SUM(amount),0) FROM ("
            "  SELECT amount FROM invoices WHERE episode_id=$1 AND origin='red' AND status IN ('blocked','rejected') "
            "  UNION ALL SELECT amount FROM expenses WHERE episode_id=$1 AND origin='red' AND status IN ('blocked','rejected') "
            "  UNION ALL SELECT i.amount FROM invoices i JOIN vendors v ON v.id=i.vendor_id WHERE i.episode_id=$1 AND i.origin='red' AND v.status='frozen' AND i.status NOT IN ('paid','blocked','rejected')"
            ") x",
            episode_id,
        )
    )

    # bank_swap: payments diverted by attributed red bank_account changes and sim invoices stopped at
    # pay time (each once), plus the target of change-only attacks stopped at the change itself.
    attacks = await db.fetch("SELECT id, day_launched, target_amount FROM attacks WHERE episode_id=$1", episode_id)
    linked = await _linked_attacks(episode_id)
    all_changes = await _red_changes(episode_id)
    red_changes = _attribute(all_changes, attacks, linked)
    swap_payments: dict[str, float] = {}
    swap_blocked: dict[str, float] = {}
    for chs in red_changes.values():
        for ch in chs:
            swap_payments.update(ch["payments"])
            swap_blocked.update(ch["blocked_invoices"])
    extracted += sum(swap_payments.values())
    blocked_amt += sum(swap_blocked.values())
    for a in attacks:
        chs = red_changes.get(a["id"], [])
        if chs and a["id"] not in linked and all(ch["state"] == "blocked" and not ch["payments"] and not ch["blocked_invoices"] for ch in chs):
            blocked_amt += float(a["target_amount"])

    # Sim invoices stopped while a red swap was live were the controller being right, not false
    # positives; sim invoices paid into a red swap were not legit processing. Ground truth, so this
    # uses every red change, attributed to an attack or not.
    not_fp = sorted({i for ch in all_changes for i in ch["stopped"]})
    diverted = sorted({i for ch in all_changes for i in ch["paid_invoices"]})

    legit_blocked_rows = await db.fetch(
        "SELECT amount FROM invoices WHERE episode_id=$1 AND origin='sim' AND status='blocked' AND NOT (id = ANY($2::text[])) "
        "UNION ALL SELECT amount FROM expenses WHERE episode_id=$1 AND origin='sim' AND status='blocked' "
        "UNION ALL SELECT 0::numeric FROM vendor_changes WHERE episode_id=$1 AND origin='sim' AND status='blocked'",
        episode_id,
        not_fp,
    )
    legit_escalated = int(
        await db.fetchval(
            "SELECT COUNT(*) FROM verdicts v WHERE v.episode_id=$1 AND v.verdict='escalate' AND NOT (v.entity_id = ANY($2::text[])) AND ("
            "  EXISTS (SELECT 1 FROM invoices i WHERE i.id=v.entity_id AND i.origin='sim') "
            "  OR EXISTS (SELECT 1 FROM expenses e WHERE e.id=v.entity_id AND e.origin='sim') "
            "  OR EXISTS (SELECT 1 FROM vendor_changes ch WHERE ch.id=v.entity_id AND ch.origin='sim'))",
            episode_id,
            not_fp,
        )
    )
    fp_cost = (
        sum(float(r["amount"]) for r in legit_blocked_rows) * settings.fp_penalty_rate + (len(legit_blocked_rows) + legit_escalated) * settings.fp_flat_penalty
    )
    legit_processed = int(
        await db.fetchval(
            "SELECT COUNT(*) FROM invoices WHERE episode_id=$1 AND origin='sim' AND status='paid' AND status_day >= 0 AND NOT (id = ANY($2::text[]))",
            episode_id,
            diverted,
        )
    )
    launched = int(await db.fetchval("SELECT COUNT(*) FROM attacks WHERE episode_id=$1", episode_id))
    caught = int(await db.fetchval("SELECT COUNT(*) FROM attacks WHERE episode_id=$1 AND outcome IN ('blocked','flagged','partial')", episode_id))
    latency = await db.fetchval("SELECT AVG(detected_day - day_launched) FROM attacks WHERE episode_id=$1 AND detected_day IS NOT NULL", episode_id)
    return {
        "dollars_extracted": round(extracted, 2),
        "dollars_blocked": round(blocked_amt, 2),
        "false_positive_cost": round(fp_cost, 2),
        "detection_latency_days": float(latency) if latency is not None else None,
        "attacks_launched": launched,
        "attacks_caught": caught,
        "legit_blocked": len(legit_blocked_rows),
        "legit_processed": legit_processed,
    }


async def end_of_day(episode_id: str, day: int) -> dict[str, Any]:
    for ch in await resolve_attacks(episode_id, day):
        await bus.emit(episode_id, day, "attack.outcome", ch)
    score = await compute(episode_id)
    await bus.emit(episode_id, day, "score.updated", score)
    return score
