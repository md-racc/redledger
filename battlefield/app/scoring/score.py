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


# Red invoices of a hijacked (non-red) vendor paid to an account red does not control. bank_swap files
# a red invoice against the vendor's real PO alongside the bank change; if the swap was not in effect
# when green paid it (change blocked, rejected, still pending, or approved only later), the money went
# to the vendor's own account on file: the business overpaid a real vendor (recoverable), red got
# nothing. $3 = the vendors with an attributed red bank_account change, $4 = their approved new_value.
_MISDIRECTED_SQL = (
    "SELECT p.id, p.invoice_id, p.amount FROM payments p JOIN invoices i ON i.id=p.invoice_id JOIN vendors v ON v.id=i.vendor_id "
    "WHERE p.episode_id=$1 AND i.attack_id=$2 AND p.origin_of_source='red' AND v.origin <> 'red' "
    "AND i.vendor_id = ANY($3::text[]) AND NOT (p.to_account = ANY($4::text[]))"
)


async def _misdirected(episode_id: str, attack_id: str, chs: list[dict[str, Any]]) -> dict[str, tuple[str, float]]:
    """{payment_id: (invoice_id, amount)} of `attack_id`'s red-invoice payments that went to the
    hijacked vendor's real account (see _MISDIRECTED_SQL). Not extracted. Empty for attacks with no
    attributed red bank_account change: ghost_vendor / threshold_split / duplicate_invoice payments
    are scored as before."""
    bank = [ch for ch in chs if ch["field"] == "bank_account"]
    if not bank:
        return {}
    vendors = sorted({ch["vendor_id"] for ch in bank})
    red_accounts = sorted({ch["new_value"] for ch in bank if ch["status"] == "approved"})
    rows = await db.fetch(_MISDIRECTED_SQL, episode_id, attack_id, vendors, red_accounts)
    return {r["id"]: (r["invoice_id"], float(r["amount"])) for r in rows}


async def misdirected_payments(episode_id: str) -> dict[str, float]:
    """{payment_id: amount} of every red-invoice payment that is not extracted because it went to the
    hijacked vendor's real account (score.compute subtracts these from dollars_extracted)."""
    attacks = await db.fetch("SELECT id, day_launched, revealed_day FROM attacks WHERE episode_id=$1", episode_id)
    _, by = await attributed_changes(episode_id, attacks)
    out: dict[str, float] = {}
    for aid, chs in by.items():
        out.update({pid: amt for pid, (_, amt) in (await _misdirected(episode_id, aid, chs)).items()})
    return out


async def _linked_attacks(episode_id: str) -> set[str]:
    """Attacks that have at least one invoice/expense row linked via attack_id."""
    rows = await db.fetch(
        "SELECT attack_id FROM invoices WHERE episode_id=$1 AND attack_id IS NOT NULL UNION SELECT attack_id FROM expenses WHERE episode_id=$1 AND attack_id IS NOT NULL",
        episode_id,
    )
    return {r["attack_id"] for r in rows}


async def _frozen_as_of(episode_id: str, vendor_id: str, day: int) -> bool:
    """Was the vendor frozen at the end of `day`? From vendor.frozen/unfrozen events, not current status."""
    t = await db.fetchval(
        "SELECT type FROM events WHERE episode_id=$1 AND type IN ('vendor.frozen','vendor.unfrozen') AND payload->>'vendor_id'=$2 AND day <= $3 "
        "ORDER BY id DESC LIMIT 1",
        episode_id,
        vendor_id,
        day,
    )
    return t == "vendor.frozen"


async def _red_changes(episode_id: str, as_of: dict[str, int] | None = None) -> list[dict[str, Any]]:
    """Every origin='red' vendor_change, resolved against ledger state.

    `as_of` {change_id: day} evaluates those changes as of the end of that day (a revealed attack's
    `revealed_day`): the swap window is capped there and the vendor's frozen status comes from events.

    Each dict gets:
      live      an approved bank_account swap with no later approved bank_account change (uncapped):
                money can still move through it, so its attack is not resolved
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
        d["live"] = swap and d["next_resolved_day"] is None
        cap = (as_of or {}).get(d["id"])
        if cap is not None:
            d["vendor_status"] = "frozen" if await _frozen_as_of(episode_id, d["vendor_id"], cap) else "active"
        if swap:
            # approve_change writes vendors.bank_account=new_value and resolved_day=<approval day>
            lo, hi = d["resolved_day"], d["next_resolved_day"]
            if cap is not None and (hi is None or hi > cap + 1):
                hi = cap + 1
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


async def attributed_changes(
    episode_id: str, attacks: list[Any], *, as_of_reveal: bool = False
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    """(every red change, changes per attack). Always attributed over ALL the episode's attacks: the
    NULL-attack_id fallback depends on which attacks exist, so a subset would misattribute.

    as_of_reveal: a revealed attack's changes are evaluated as of its revealed_day (score.compute),
    so blocks or freezes made with hindsight never add to its score. Unrevealed attacks keep the
    live evaluation even when they share a change with a revealed one.
    """
    linked = await _linked_attacks(episode_id)
    changes = await _red_changes(episode_id)
    by = _attribute(changes, attacks, linked)
    as_of: dict[str, int] = {}
    for a in attacks:
        if as_of_reveal and a["revealed_day"] is not None:
            for ch in by.get(a["id"], []):
                as_of[ch["id"]] = min(a["revealed_day"], as_of.get(ch["id"], a["revealed_day"]))
    if as_of:
        capped = _attribute(await _red_changes(episode_id, as_of), attacks, linked)
        by = {a["id"]: (capped if a["revealed_day"] is not None else by).get(a["id"], []) for a in attacks}
    return changes, by


async def attack_parts(episode_id: str, only: set[str] | None = None) -> dict[str, tuple[Any, list[Any], list[dict[str, Any]], list[str]]]:
    """Per attack in `only` (default all): (attack row, invoice/expense rows, attributed red
    vendor_changes, entity ids its detection looks at)."""
    attacks = await db.fetch("SELECT * FROM attacks WHERE episode_id=$1 ORDER BY created_at, id", episode_id)
    _, red_changes = await attributed_changes(episode_id, attacks)
    out: dict[str, tuple[Any, list[Any], list[dict[str, Any]], list[str]]] = {}
    for a in attacks:
        if only is not None and a["id"] not in only:
            continue
        rows = await db.fetch(
            "SELECT 'invoice' AS kind, id, vendor_id AS owner_id, amount, status, status_day FROM invoices WHERE attack_id=$1 "
            "UNION ALL SELECT 'expense', id, employee_id, amount, status, NULL FROM expenses WHERE attack_id=$1",
            a["id"],
        )
        chs = red_changes.get(a["id"], [])
        ids = [r["id"] for r in rows] + [r["owner_id"] for r in rows]
        for ch in chs:
            ids += [ch["id"], ch["vendor_id"], *ch["stopped"]]
        out[a["id"]] = (a, list(rows), chs, ids)
    return out


async def resolve_attacks(episode_id: str, day: int) -> list[dict[str, Any]]:
    """Update attacks.outcome / amount_extracted / detected_day from ledger state. Returns changed attacks.

    `resolved_day` is set once, the first day an attack is resolved (failed, or entities and none
    pending). An attack a lineage debrief has revealed (`revealed_day`) is frozen: never re-resolved,
    so blocks, flags or freezes made with hindsight don't count as detection.
    """
    changed: list[dict[str, Any]] = []
    unrevealed = {r["id"] for r in await db.fetch("SELECT id FROM attacks WHERE episode_id=$1 AND revealed_day IS NULL", episode_id)}
    for aid, (a, rows, chs, ids) in (await attack_parts(episode_id, unrevealed)).items():
        entities = bool(rows or chs)
        swap_payments = {pid: amt for ch in chs for pid, amt in ch["payments"].items()}  # each payment once
        misdirected = {inv for inv, _ in (await _misdirected(episode_id, aid, chs)).values()}  # paid to the real vendor
        extracted = sum(float(r["amount"]) for r in rows if r["status"] == "paid" and r["id"] not in misdirected) + sum(swap_payments.values())
        blocked = [r for r in rows if r["status"] in ("blocked", "rejected")] + [ch for ch in chs if ch["state"] == "blocked"]
        pending = [r for r in rows if r["status"] in ("pending", "matched", "approved")] + [ch for ch in chs if ch["state"] == "pending"]

        # detection: earliest block verdict or flag touching the attack's entities, on or after launch
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

        resolved = False
        if entities and not pending:
            resolved = True
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
        # an approved bank swap still live can divert the next payment: not resolved, so never revealed mid-episode
        resolved = (resolved or outcome == "failed") and not any(ch["live"] for ch in chs)
        resolved_day = a["resolved_day"] if a["resolved_day"] is not None else (day if resolved else None)

        if outcome != a["outcome"] or float(a["amount_extracted"]) != extracted or a["detected_day"] != detected_day or resolved_day != a["resolved_day"]:
            await db.execute(
                "UPDATE attacks SET outcome=$2, amount_extracted=$3, detected_day=$4, resolved_day=$5 WHERE id=$1",
                aid,
                outcome,
                extracted,
                detected_day,
                resolved_day,
            )
        if outcome != a["outcome"] or float(a["amount_extracted"]) != extracted or a["detected_day"] != detected_day:
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
    attacks = await db.fetch("SELECT id, day_launched, target_amount, revealed_day FROM attacks WHERE episode_id=$1", episode_id)
    linked = await _linked_attacks(episode_id)
    all_changes, red_changes = await attributed_changes(episode_id, attacks, as_of_reveal=True)
    swap_payments: dict[str, float] = {}
    swap_blocked: dict[str, float] = {}
    misdirected: dict[str, float] = {}
    for aid, chs in red_changes.items():
        for ch in chs:
            swap_payments.update(ch["payments"])
            swap_blocked.update(ch["blocked_invoices"])
        misdirected.update({pid: amt for pid, (_, amt) in (await _misdirected(episode_id, aid, chs)).items()})
    extracted += sum(swap_payments.values()) - sum(misdirected.values())
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

    # False positives: each legit (sim) item is charged once, by its worst controller outcome.
    #   blocked:   amount x FP_PENALTY_RATE + FP_FLAT_PENALTY. The item ended blocked, any block verdict
    #              touched it (enforced, or a shadow "would-have" block), or an escalation of it ended
    #              block/timeout. A block verdict followed by green's own reject still counts.
    #   escalated: FP_FLAT_PENALTY only. Escalated (enforced and approved or still open, or a shadow
    #              "would-have" escalation) but never blocked: human time spent, money moved.
    # Verdicts carry `enforced`, so shadow scores the same way as enforce ("would-have" costs) and off
    # (no verdicts) scores 0: the three modes compare cleanly. In shadow, legit_blocked therefore counts
    # would-have blocks. Invoices stopped while a red swap was live (not_fp) are never charged.
    fp_items = await db.fetch(
        "WITH items AS ("
        "  SELECT id, amount, status FROM invoices WHERE episode_id=$1 AND origin='sim' AND NOT (id = ANY($2::text[])) "
        "  UNION ALL SELECT id, amount, status FROM expenses WHERE episode_id=$1 AND origin='sim' "
        "  UNION ALL SELECT id, 0::numeric, status FROM vendor_changes WHERE episode_id=$1 AND origin='sim'"
        ") SELECT it.id, it.amount, ("
        "  it.status = 'blocked' "
        "  OR EXISTS (SELECT 1 FROM verdicts v WHERE v.episode_id=$1 AND v.entity_id=it.id AND v.verdict='block') "
        "  OR EXISTS (SELECT 1 FROM escalations e JOIN verdicts v ON v.id=e.verdict_id "
        "             WHERE v.episode_id=$1 AND v.entity_id=it.id AND e.status IN ('blocked','timeout'))"
        ") AS blocked, EXISTS (SELECT 1 FROM verdicts v WHERE v.episode_id=$1 AND v.entity_id=it.id AND v.verdict='escalate') AS escalated "
        "FROM items it",
        episode_id,
        not_fp,
    )
    legit_blocked_rows = [r for r in fp_items if r["blocked"]]
    legit_escalated = sum(1 for r in fp_items if r["escalated"] and not r["blocked"])
    fp_cost = (
        sum(float(r["amount"]) for r in legit_blocked_rows) * settings.fp_penalty_rate + (len(legit_blocked_rows) + legit_escalated) * settings.fp_flat_penalty
    )
    # Seed history's paid status_day/paid_day can land on days 0..10 (company.seed_episode draws them
    # independently of the episode clock): those were paid by the seed, not processed by green.
    legit_processed = int(
        await db.fetchval(
            "SELECT COUNT(*) FROM invoices i WHERE i.episode_id=$1 AND i.origin='sim' AND i.status='paid' AND i.status_day >= 0 AND NOT (i.id = ANY($2::text[])) "
            "AND NOT EXISTS (SELECT 1 FROM payments p WHERE p.invoice_id=i.id AND p.paid_by='seed')",
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
