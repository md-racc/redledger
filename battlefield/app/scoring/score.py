"""Scoring + attack outcome resolution. Owner: Dev Ad.

Ground truth comes from provenance (origin / attack_id) that agents never see.
"""

from __future__ import annotations

from typing import Any

from .. import db
from ..config import settings
from ..events import bus


async def resolve_attacks(episode_id: str, day: int) -> list[dict[str, Any]]:
    """Update attacks.outcome / amount_extracted / detected_day from ledger state. Returns changed attacks."""
    changed: list[dict[str, Any]] = []
    attacks = await db.fetch("SELECT * FROM attacks WHERE episode_id=$1", episode_id)
    for a in attacks:
        aid = a["id"]
        rows = await db.fetch(
            "SELECT 'invoice' AS kind, id, vendor_id AS owner_id, amount, status, status_day FROM invoices WHERE attack_id=$1 "
            "UNION ALL SELECT 'expense', id, employee_id, amount, status, NULL FROM expenses WHERE attack_id=$1",
            aid,
        )
        extracted = sum(float(r["amount"]) for r in rows if r["status"] == "paid")
        blocked = [r for r in rows if r["status"] in ("blocked", "rejected")]
        pending = [r for r in rows if r["status"] in ("pending", "matched", "approved")]

        # detection: earliest block verdict or flag touching the attack's entities
        ids = [r["id"] for r in rows] + [r["owner_id"] for r in rows]
        detected_day = None
        if ids:
            detected_day = await db.fetchval(
                "SELECT MIN(d) FROM ("
                "  SELECT day AS d FROM verdicts WHERE episode_id=$1 AND verdict IN ('block','escalate') AND entity_id = ANY($2::text[]) "
                "  UNION ALL SELECT day FROM flags WHERE episode_id=$1 AND entity_id = ANY($2::text[])"
                ") x",
                episode_id,
                ids,
            )
        frozen = await db.fetchval("SELECT COUNT(*) FROM vendors v JOIN invoices i ON i.vendor_id=v.id WHERE i.attack_id=$1 AND v.status='frozen'", aid)

        if rows and not pending:
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
            outcome = "pending" if rows else ("failed" if a["day_launched"] < day else "pending")

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
    legit_blocked_rows = await db.fetch(
        "SELECT amount FROM invoices WHERE episode_id=$1 AND origin='sim' AND status='blocked' "
        "UNION ALL SELECT amount FROM expenses WHERE episode_id=$1 AND origin='sim' AND status='blocked'",
        episode_id,
    )
    legit_escalated = int(
        await db.fetchval(
            "SELECT COUNT(*) FROM verdicts v JOIN invoices i ON i.id=v.entity_id WHERE v.episode_id=$1 AND v.verdict='escalate' AND i.origin='sim'", episode_id
        )
    )
    fp_cost = (
        sum(float(r["amount"]) for r in legit_blocked_rows) * settings.fp_penalty_rate + (len(legit_blocked_rows) + legit_escalated) * settings.fp_flat_penalty
    )
    legit_processed = int(
        await db.fetchval("SELECT COUNT(*) FROM invoices WHERE episode_id=$1 AND origin='sim' AND status='paid' AND status_day >= 0", episode_id)
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
