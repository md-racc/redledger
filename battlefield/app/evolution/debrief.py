"""Daily lineage debriefs: the only place ground truth leaves battlefield mid-episode. Owner: Dev Ad.

contracts/agent-service.md "Lineages" is the spec. At the end of day d of a lineage episode (not the
last day), each agent gets a debrief built from what it may know, stored in `debriefs` exactly as
delivered, and read back from there on its day d+1 turn (so a restart between the two loses
nothing). Only resolved attacks are revealed; revealing one sets `attacks.revealed_day`, which
freezes its outcome (score.resolve_attacks). Legit items appear only in a terminal status.

Windowing: an item is in day d's debrief while it was first revealed on one of the last
`reveal_days` days (d - reveal_days + 1 .. d), `new` on its first day. An attack's first day is its
`revealed_day`; a legit item's is the earliest earlier debrief that listed it.
"""

from __future__ import annotations

from typing import Any

import structlog

from agentkit.models import LineageConfig

from .. import db
from ..events import bus
from ..scoring import score

log = structlog.get_logger(__name__)

AGENTS = ("red", "green", "blue")
_TERMINAL = {"invoice": ("paid", "rejected", "blocked"), "expense": ("paid", "rejected", "blocked"), "vendor_change": ("approved", "rejected", "blocked")}
_TABLE = {"invoice": "invoices", "expense": "expenses", "vendor_change": "vendor_changes"}


async def context(episode_id: str) -> dict[str, Any] | None:
    """Lineage context of an episode, or None for a plain episode (which never reveals anything)."""
    rows = await db.fetch(  # no row for a plain episode
        "SELECT e.lineage_id, e.generation, e.days, l.config FROM episodes e JOIN lineages l ON l.id=e.lineage_id WHERE e.id=$1", episode_id
    )
    if not rows:
        return None
    row = rows[0]
    cfg = LineageConfig.model_validate(row["config"] or {})
    return {"lineage_id": row["lineage_id"], "generation": row["generation"], "days": row["days"], "reveal_days": cfg.reveal_days}


async def lineage_info(ctx: dict[str, Any], agent: str) -> dict[str, Any]:
    """`options.lineage` / blue's `lineage`: the agent's latest playbook version (0 before any write)."""
    v = await db.fetchval("SELECT MAX(version) FROM playbooks WHERE lineage_id=$1 AND agent=$2", ctx["lineage_id"], agent)
    return {"id": ctx["lineage_id"], "generation": ctx["generation"], "playbook_version": v or 0}


async def for_turn(episode_id: str, agent: str, day: int) -> dict[str, Any] | None:
    """The debrief built at the end of `day - 1`, as stored. None on day 0 or with reveal_days 0."""
    return await db.fetchval("SELECT payload FROM debriefs WHERE episode_id=$1 AND agent=$2 AND day=$3 ORDER BY id LIMIT 1", episode_id, agent, day - 1)


async def turn_fields(episode_id: str, agent: str, day: int, ctx: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"lineage": await lineage_info(ctx, agent)}
    if (d := await for_turn(episode_id, agent, day)) is not None:
        out["debrief"] = d
    return out


async def deliver(episode_id: str, day: int, ctx: dict[str, Any]) -> None:
    """Build, store and announce day `day`'s debriefs. Call after score.end_of_day, before day.ended.

    Idempotent per (episode, day, agent): a resumed day re-delivers nothing already stored.
    """
    n = ctx["reveal_days"]
    if n <= 0 or day + 1 >= ctx["days"]:
        return  # nothing revealed daily, or the last day: no next turn to deliver to
    await db.execute("UPDATE attacks SET revealed_day=$2 WHERE episode_id=$1 AND resolved_day IS NOT NULL AND revealed_day IS NULL", episode_id, day)
    lo = day - n + 1
    built = await _build(episode_id, day, lo)
    for agent in AGENTS:
        if await db.fetchval("SELECT 1 FROM debriefs WHERE episode_id=$1 AND agent=$2 AND day=$3", episode_id, agent, day):
            continue
        items = await _window(episode_id, agent, day, lo, built[agent])
        payload = {"day": day, "window_days": n, "items": items}
        await db.execute(
            "INSERT INTO debriefs (lineage_id, generation, episode_id, day, agent, payload) VALUES ($1,$2,$3,$4,$5,$6)",
            ctx["lineage_id"],
            ctx["generation"],
            episode_id,
            day,
            agent,
            payload,
        )
        revealed = sum(1 for i in items if i["kind"] == "attack")
        new = sum(1 for i in items if i["new"])
        await bus.emit(episode_id, day, "debrief.delivered", {"agent": agent, "day": day, "revealed_attacks": revealed, "new_items": new, "window_days": n})
        log.info("debrief_delivered", episode_id=episode_id, day=day, agent=agent, items=len(items), new=new)


def _key(item: dict[str, Any]) -> str:
    if item["kind"] == "attack":
        return f"attack:{item['attack_id']}"
    if item["kind"] == "legit_blocked":
        return f"legit_blocked:{item['verdict_id']}"
    return f"{item['kind']}:{item['entity_type']}:{item['entity_id']}"


async def _window(episode_id: str, agent: str, day: int, lo: int, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep attacks revealed in [lo, day] and legit items first listed in [lo, day]; set `new`."""
    first: dict[str, int] = {}
    for r in await db.fetch("SELECT day, payload FROM debriefs WHERE episode_id=$1 AND agent=$2 AND day < $3 ORDER BY day", episode_id, agent, day):
        for it in r["payload"]["items"]:
            first.setdefault(_key(it), r["day"])
    out = []
    for it in candidates:
        if it["kind"] == "attack" or it["kind"] == "fraud":
            since = it.pop("_revealed_day")
        else:
            since = first.get(_key(it), day)
        if since >= lo:
            out.append({**it, "new": since == day})
    return out


async def _build(episode_id: str, day: int, lo: int) -> dict[str, list[dict[str, Any]]]:
    """Every candidate item per agent, before windowing. Attack items carry `_revealed_day`."""
    out: dict[str, list[dict[str, Any]]] = {a: [] for a in AGENTS}
    attacks = await db.fetch("SELECT * FROM attacks WHERE episode_id=$1 AND revealed_day >= $2 ORDER BY revealed_day, created_at, id", episode_id, lo)
    parts = await score.attack_parts(episode_id, attacks) if attacks else {}
    for a in attacks:
        rows, chs, ids = parts[a["id"]]
        vendor_ids = sorted({r["owner_id"] for r in rows if r["kind"] == "invoice"} | {ch["vendor_id"] for ch in chs})
        verdicts = await db.fetch(
            "SELECT * FROM verdicts WHERE episode_id=$1 AND entity_id = ANY($2::text[]) AND day >= $3 ORDER BY day, created_at",
            episode_id,
            ids,
            a["day_launched"],
        )
        flags = await db.fetch(
            "SELECT * FROM flags WHERE episode_id=$1 AND entity_id = ANY($2::text[]) AND day >= $3 ORDER BY day, id", episode_id, ids, a["day_launched"]
        )
        freezes = await _freezes(episode_id, vendor_ids, a["day_launched"])
        base = {
            "kind": "attack",
            "attack_id": a["id"],
            "scheme_id": a["scheme_id"],
            "day_launched": a["day_launched"],
            "resolved_day": a["resolved_day"],
            "outcome": a["outcome"],
            "amount_extracted": float(a["amount_extracted"]),
            "detected_day": a["detected_day"],
            "_revealed_day": a["revealed_day"],
        }
        controls = (
            [
                {"kind": "verdict", "day": v["day"], "action": v["action"], "verdict": v["verdict"], "rules_fired": v["rules_fired"], "reason": v["reason"]}
                for v in verdicts
            ]
            + [{"kind": "flag", "day": f["day"], "severity": f["severity"], "reason": f["reason"]} for f in flags]
            + [{"kind": "freeze", "day": z["day"], "vendor_id": z["vendor_id"], "reason": z["reason"]} for z in freezes]
        )
        out["red"].append({**base, "controls": sorted(controls, key=lambda c: c["day"])})
        red_owned = await db.fetch(
            "SELECT 'vendor' AS t, id FROM vendors WHERE episode_id=$1 AND origin='red' AND id = ANY($2::text[]) "
            "UNION ALL SELECT 'employee', id FROM employees WHERE episode_id=$1 AND origin='red' AND id = ANY($2::text[])",
            episode_id,
            ids,
        )
        entities = (
            [{"entity_type": r["kind"], "entity_id": r["id"], "amount": float(r["amount"])} for r in rows]
            + [{"entity_type": "vendor_change", "entity_id": ch["id"]} for ch in chs]
            + [{"entity_type": r["t"], "entity_id": r["id"]} for r in red_owned]
        )
        caught = (
            [{"kind": "verdict", "id": v["id"], "day": v["day"], "rules_fired": v["rules_fired"]} for v in verdicts if v["verdict"] in ("block", "escalate")]
            + [{"kind": "flag", "id": f["id"], "day": f["day"]} for f in flags]
            + [{"kind": "freeze", "id": z["vendor_id"], "day": z["day"]} for z in freezes]
        )
        out["blue"].append({**base, "display_name": a["display_name"], "entities": entities, "caught_by": sorted(caught, key=lambda c: c["day"])})
        for r in rows:
            if r["status"] not in ("paid", "blocked", "rejected"):
                continue
            gv = [v for v in verdicts if v["agent"] == "green" and v["entity_id"] == r["id"]]
            if not gv and r["status"] == "blocked":
                continue  # blocked without a green action (e.g. by a freeze): green did not act on it
            action = gv[-1]["action"] if gv else f"{r['kind']}s.{'pay' if r['status'] == 'paid' else 'reject'}"
            out["green"].append(
                {
                    "kind": "fraud",
                    "entity_type": r["kind"],
                    "entity_id": r["id"],
                    "amount": float(r["amount"]),
                    "green_action": action,
                    "outcome": r["status"],
                    "day": r["status_day"] if r["status_day"] is not None else a["resolved_day"],
                    "_revealed_day": a["revealed_day"],
                }
            )
    await _legit(episode_id, out)
    return out


def _amount(item: dict[str, Any]) -> dict[str, Any]:
    """`amount` is optional in the item shapes: omit it rather than send null (vendor changes have none)."""
    if item.get("amount") is None:
        item.pop("amount", None)
    return item


async def _freezes(episode_id: str, vendor_ids: list[str], since: int) -> list[dict[str, Any]]:
    if not vendor_ids:
        return []
    rows = await db.fetch(
        "SELECT day, payload->>'vendor_id' AS vendor_id, payload->>'reason' AS reason FROM events "
        "WHERE episode_id=$1 AND type='vendor.frozen' AND payload->>'vendor_id' = ANY($2::text[]) AND day >= $3 ORDER BY id",
        episode_id,
        vendor_ids,
        since,
    )
    return [dict(r) for r in rows]


async def _legit(episode_id: str, out: dict[str, list[dict[str, Any]]]) -> None:
    """Blue's false positives and green's gate-blocked actions, on legit items in a terminal status."""
    # sim invoices stopped while a red bank swap was live were the controller being right (score.compute)
    not_fp = sorted({i for ch in await score._red_changes(episode_id) for i in ch["stopped"]})
    legit: dict[str, tuple[str, float | None]] = {}
    for etype, statuses in _TERMINAL.items():
        amount = "amount" if etype != "vendor_change" else "NULL::numeric"
        for r in await db.fetch(
            f"SELECT id, {amount} AS amount FROM {_TABLE[etype]} WHERE episode_id=$1 AND origin='sim' AND status = ANY($2::text[]) AND NOT (id = ANY($3::text[]))",
            episode_id,
            list(statuses),
            not_fp,
        ):
            legit[r["id"]] = (etype, float(r["amount"]) if r["amount"] is not None else None)
    ids = list(legit)
    verdicts = await db.fetch("SELECT * FROM verdicts WHERE episode_id=$1 AND entity_id = ANY($2::text[]) ORDER BY day, created_at", episode_id, ids)
    flags = await db.fetch("SELECT * FROM flags WHERE episode_id=$1 AND entity_id = ANY($2::text[]) ORDER BY day, id", episode_id, ids)
    by: dict[str, dict[str, Any]] = {}
    for v in verdicts:
        if v["verdict"] in ("block", "escalate"):
            by.setdefault(v["entity_id"], {"kind": "verdict", "id": v["id"], "day": v["day"], "rules_fired": v["rules_fired"]})
        if v["agent"] == "green" and v["verdict"] == "block" and v["enforced"]:
            etype, amt = legit[v["entity_id"]]
            out["green"].append(
                _amount(
                    {
                        "kind": "legit_blocked",
                        "entity_type": etype,
                        "entity_id": v["entity_id"],
                        "amount": amt,
                        "action": v["action"],
                        "verdict_id": v["id"],
                        "day": v["day"],
                    }
                )
            )
    for f in flags:
        c = by.get(f["entity_id"])
        if c is None or f["day"] < c["day"]:
            by[f["entity_id"]] = {"kind": "flag", "id": f["id"], "day": f["day"]}
    for eid, c in sorted(by.items(), key=lambda kv: (kv[1]["day"], kv[0])):
        etype, amt = legit[eid]
        out["blue"].append(_amount({"kind": "false_positive", "entity_type": etype, "entity_id": eid, "amount": amt, "day": c.pop("day"), "by": c}))
    sim_vendors = [r["id"] for r in await db.fetch("SELECT id FROM vendors WHERE episode_id=$1 AND origin='sim'", episode_id)]
    seen: set[str] = set()
    for z in await _freezes(episode_id, sim_vendors, -(10**6)):
        if z["vendor_id"] not in seen:
            seen.add(z["vendor_id"])
            out["blue"].append(
                {
                    "kind": "false_positive",
                    "entity_type": "vendor",
                    "entity_id": z["vendor_id"],
                    "day": z["day"],
                    "by": {"kind": "freeze", "id": z["vendor_id"]},
                }
            )
