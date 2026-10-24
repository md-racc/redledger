"""Daily lineage debriefs: the only place ground truth leaves battlefield mid-episode. Owner: Dev Ad.

contracts/agent-service.md "Lineages" is the spec. At the end of day d of a lineage episode (not the
last day), each agent gets a debrief built from what it may know, stored in `debriefs` exactly as
delivered, and read back from there on its day d+1 turn (so a restart between the two loses
nothing). Daily items come only from resolved red attacks; revealing one sets
`attacks.revealed_day`, which freezes its outcome (score.resolve_attacks) and its score contribution
(score.compute evaluates it as of that day). Everything an item shows is bounded to day <= revealed_day.

Legit items (blue's false positives, green's gate-blocked legit actions) are NOT in daily debriefs:
listing the legit items blue stopped would let it infer that the unlisted ones are red from attacks
still unresolved. `legit_items` builds them for the after-action review, after the episode ended.

Windowing: an attack is in day d's debrief while its revealed_day is one of the last `reveal_days`
days (d - reveal_days + 1 .. d), `new` on its revealed_day.
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
    built = await attack_items(episode_id, day - n + 1)
    for agent in AGENTS:
        if await db.fetchval("SELECT 1 FROM debriefs WHERE episode_id=$1 AND agent=$2 AND day=$3", episode_id, agent, day):
            continue
        items = [{**public(it), "new": it["_revealed_day"] == day} for it in built[agent]]
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
        revealed = len({it["_attack_id"] for it in built[agent]})  # distinct attacks behind the items (green: its fraud items)
        new = sum(1 for i in items if i["new"])
        await bus.emit(episode_id, day, "debrief.delivered", {"agent": agent, "day": day, "revealed_attacks": revealed, "new_items": new, "window_days": n})
        log.info("debrief_delivered", episode_id=episode_id, day=day, agent=agent, items=len(items), new=new)


def public(item: dict[str, Any]) -> dict[str, Any]:
    """An item as delivered: without the builder's private `_` keys."""
    return {k: v for k, v in item.items() if not k.startswith("_")}


async def attack_items(episode_id: str, since: int) -> dict[str, list[dict[str, Any]]]:
    """Per agent, the items of every attack revealed on or after `since` (each carries `_revealed_day`
    and `_attack_id`, stripped by `public`)."""
    out: dict[str, list[dict[str, Any]]] = {a: [] for a in AGENTS}
    ids_in = {r["id"] for r in await db.fetch("SELECT id FROM attacks WHERE episode_id=$1 AND revealed_day >= $2", episode_id, since)}
    parts = sorted((await score.attack_parts(episode_id, ids_in)).values(), key=lambda p: (p[0]["revealed_day"], p[0]["created_at"], p[0]["id"]))
    for a, rows, chs, ids in parts:
        lo, hi = a["day_launched"], a["revealed_day"]
        vendor_ids = sorted({r["owner_id"] for r in rows if r["kind"] == "invoice"} | {ch["vendor_id"] for ch in chs})
        verdicts = await db.fetch(
            "SELECT * FROM verdicts WHERE episode_id=$1 AND entity_id = ANY($2::text[]) AND day BETWEEN $3 AND $4 ORDER BY day, created_at",
            episode_id,
            ids,
            lo,
            hi,
        )
        flags = await db.fetch(
            "SELECT * FROM flags WHERE episode_id=$1 AND entity_id = ANY($2::text[]) AND day BETWEEN $3 AND $4 ORDER BY day, id", episode_id, ids, lo, hi
        )
        freezes = await _freezes(episode_id, vendor_ids, lo, hi)
        base = {
            "kind": "attack",
            "attack_id": a["id"],
            "scheme_id": a["scheme_id"],
            "day_launched": a["day_launched"],
            "resolved_day": a["resolved_day"],
            "outcome": a["outcome"],
            "amount_extracted": float(a["amount_extracted"]),
            "detected_day": a["detected_day"],
            "_revealed_day": hi,
            "_attack_id": a["id"],
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
        out["green"] += [{**f, "_attack_id": a["id"]} for f in await _fraud(episode_id, rows, chs, verdicts, lo, hi)]
    return out


_FRAUD_OUTCOMES = ("paid", "approved", "blocked", "rejected")


async def _fraud(episode_id: str, rows: list[Any], chs: list[dict[str, Any]], verdicts: list[Any], lo: int, hi: int) -> list[dict[str, Any]]:
    """Green's `fraud` items: red invoices/expenses and red vendor changes green actually acted on (a
    ledger.mutation it made, or a gate verdict on its attempt). `green_action` is green's last such action;
    `outcome` is the item's status (`approved`: green approved it and it was neither paid nor stopped; an
    invoice can only be `approved` in the after-action review, a daily debrief has only resolved attacks).
    Vendor changes carry `field` and no `amount`."""
    out = []
    for r in [*rows, *({"kind": "vendor_change", "id": ch["id"], "status": ch["status"], "field": ch["field"]} for ch in chs)]:
        if r["status"] not in _FRAUD_OUTCOMES:
            continue
        acts = [(v["day"], 0, v["action"]) for v in verdicts if v["agent"] == "green" and v["entity_id"] == r["id"]]
        for m in await db.fetch(
            "SELECT id, day, payload->>'action' AS action FROM events WHERE episode_id=$1 AND type='ledger.mutation' AND payload->>'agent'='green' "
            "AND payload->>'entity_id'=$2 AND day BETWEEN $3 AND $4",
            episode_id,
            r["id"],
            lo,
            hi,
        ):
            acts.append((m["day"], m["id"], m["action"]))
        if not acts:
            continue  # green never acted on it (e.g. blocked by a freeze): nothing to learn from
        day, _, action = max(acts)
        item = {
            "kind": "fraud",
            "entity_type": r["kind"],
            "entity_id": r["id"],
            "green_action": action,
            "outcome": r["status"],
            "day": day,
            "_revealed_day": hi,
        }
        if r["kind"] == "vendor_change":
            item["field"] = r["field"]
        else:
            item["amount"] = float(r["amount"])
        out.append(item)
    return out


async def _freezes(episode_id: str, vendor_ids: list[str], lo: int, hi: int) -> list[dict[str, Any]]:
    if not vendor_ids:
        return []
    rows = await db.fetch(
        "SELECT day, payload->>'vendor_id' AS vendor_id, payload->>'reason' AS reason FROM events "
        "WHERE episode_id=$1 AND type='vendor.frozen' AND payload->>'vendor_id' = ANY($2::text[]) AND day BETWEEN $3 AND $4 ORDER BY id",
        episode_id,
        vendor_ids,
        lo,
        hi,
    )
    return [dict(r) for r in rows]


def _amount(item: dict[str, Any]) -> dict[str, Any]:
    """`amount` is optional in the item shapes: omit it rather than send null (vendor changes have none)."""
    if item.get("amount") is None:
        item.pop("amount", None)
    return item


async def legit_items(episode_id: str) -> dict[str, list[dict[str, Any]]]:
    """After-action review only (never daily): blue's `false_positive` and green's `legit_blocked`
    items, on legit items in a terminal status. Shapes per contracts/agent-service.md, minus `new`."""
    out: dict[str, list[dict[str, Any]]] = {"blue": [], "green": []}
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
    for z in await _freezes(episode_id, sim_vendors, -(10**6), 10**6):
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
    return out
