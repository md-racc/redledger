"""The evolution report and the lineage timeline. Owner: Dev Ad.

docs/EVOLUTION-DESIGN.md §7. Both documents are derived from the database only, operator-only
(`/api/fe/lineages/{id}/report|timeline`), and deterministic: rows are ordered explicitly, no
timestamps appear, and playbook diffs are structural. They use ground truth (`origin`) for rule
precision, which is fine here and nowhere an agent can read. Partial while the lineage runs.

Definitions the report relies on:
  - an attack's entities: its invoices and expenses, their vendors, its vendor changes and theirs;
  - a rule "fired on" an attack when a verdict on one of those entities, on or after the attack's
    `day_launched`, lists it (any verdict; a bank swap's vendor is legit and may be judged earlier);
  - `recall` of a rule = attacks it fired on / attacks launched in that generation;
  - `missed` = attacks whose outcome is `extracted` (money left and nothing stopped it);
  - learned rules = rule ids prefixed `learned:`; new / retired = ids first / last seen in a
    generation (retired: seen before, absent from the latest generation in which any rule fired).
"""

from __future__ import annotations

from typing import Any

from agentkit.models import LineageConfig

from .. import db
from ..orchestrator import runner
from ..scoring import score
from . import review

AGENTS = ("red", "green", "blue")

_ENTITIES_SQL = """
SELECT a.id, a.scheme_id, a.outcome, a.day_launched, e.eid
FROM attacks a
LEFT JOIN LATERAL (
  SELECT id AS eid FROM invoices WHERE attack_id = a.id
  UNION SELECT vendor_id FROM invoices WHERE attack_id = a.id
  UNION SELECT id FROM expenses WHERE attack_id = a.id
  UNION SELECT id FROM vendor_changes WHERE attack_id = a.id
  UNION SELECT vendor_id FROM vendor_changes WHERE attack_id = a.id
) e ON true
WHERE a.episode_id = $1
"""


def _num(v: Any) -> float:
    return round(float(v or 0), 2)


def diff(old: Any, new: Any, path: str = "") -> dict[str, Any]:
    """Structural diff of two JSON values: dicts recurse by key, anything else compares whole.
    Paths are dot-joined (the root is ""). Keys are sorted, so the result is deterministic."""
    out: dict[str, Any] = {"added": {}, "removed": {}, "changed": {}}
    if isinstance(old, dict) and isinstance(new, dict):
        for k in sorted(set(old) | set(new), key=str):
            p = f"{path}.{k}" if path else str(k)
            if k not in old:
                out["added"][p] = new[k]
            elif k not in new:
                out["removed"][p] = old[k]
            else:
                sub = diff(old[k], new[k], p)
                for part in out:
                    out[part].update(sub[part])
    elif old != new:
        out["changed"][path] = {"from": old, "to": new}
    return out


async def _lineage(lineage_id: str) -> Any:
    return await db.fetchrow("SELECT id, name, base_seed, config, status, current_generation FROM lineages WHERE id=$1", lineage_id)


async def _episodes(lineage_id: str) -> list[Any]:
    return await db.fetch("SELECT id, generation, seed, status, days, controller_mode FROM episodes WHERE lineage_id=$1 ORDER BY generation", lineage_id)


async def _credits(episode_id: str) -> float:
    rows = await db.fetch("SELECT payload->'factory_credits' AS c FROM events WHERE episode_id=$1 AND type='turn.ended'", episode_id)
    return _num(sum(runner.credits_of(r["c"]) for r in rows))  # same per-turn rule as the runner's credit guard


async def _red_mix(episode_id: str) -> dict[str, Any]:
    mix: dict[str, Any] = {}
    rows = await db.fetch(
        "SELECT scheme_id, outcome, COUNT(*) AS n, SUM(amount_extracted) AS extracted, SUM(target_amount) AS target "
        "FROM attacks WHERE episode_id=$1 GROUP BY scheme_id, outcome ORDER BY scheme_id, outcome",
        episode_id,
    )
    for r in rows:
        m = mix.setdefault(r["scheme_id"], {"launched": 0, "outcomes": {}, "amount_extracted": 0.0, "target_amount": 0.0})
        m["launched"] += r["n"]
        m["outcomes"][r["outcome"]] = r["n"]
        m["amount_extracted"] = _num(m["amount_extracted"] + float(r["extracted"] or 0))
        m["target_amount"] = _num(m["target_amount"] + float(r["target"] or 0))
    return mix


async def _attack_rules(episode_id: str) -> list[dict[str, Any]]:
    """Per attack: scheme, outcome and the set of rule ids that fired on any of its entities on or after
    the day it launched (a bank swap's vendor is legit and may have been judged before the attack)."""
    fired: dict[str, list[tuple[int, list[str]]]] = {}
    for v in await db.fetch("SELECT entity_id, day, rules_fired FROM verdicts WHERE episode_id=$1 AND entity_id IS NOT NULL", episode_id):
        fired.setdefault(v["entity_id"], []).append((v["day"], [str(x) for x in (v["rules_fired"] or [])]))
    attacks: dict[str, dict[str, Any]] = {}
    for r in await db.fetch(_ENTITIES_SQL, episode_id):
        a = attacks.setdefault(r["id"], {"scheme_id": r["scheme_id"], "outcome": r["outcome"], "rules": set()})
        for day, rules in fired.get(r["eid"], []) if r["eid"] is not None else []:
            if day >= r["day_launched"]:
                a["rules"].update(rules)
    return [attacks[k] for k in sorted(attacks)]


def _matrix(attacks: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for a in attacks:
        m = out.setdefault(a["scheme_id"], {"attacks": 0, "caught": 0, "missed": 0, "rules": {}})
        m["attacks"] += 1
        m["caught"] += a["outcome"] in ("blocked", "flagged", "partial")
        m["missed"] += a["outcome"] == "extracted"
        for rule in sorted(a["rules"]):
            m["rules"][rule] = m["rules"].get(rule, 0) + 1
    for m in out.values():
        m["rules"] = {k: m["rules"][k] for k in sorted(m["rules"])}
    return {k: out[k] for k in sorted(out)}


async def _rules(episode_id: str, attacks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    launched = len(attacks)
    out = []
    for r in await review.rules(episode_id):
        hit = sum(1 for a in attacks if r["rule_id"] in a["rules"])
        out.append(
            {
                **r,
                "precision": round(r["on_red"] / r["fired"], 4) if r["fired"] else None,
                "attacks_hit": hit,
                "recall": round(hit / launched, 4) if launched else None,
            }
        )
    return sorted(out, key=lambda x: (-x["fired"], x["rule_id"]))


async def _green(episode_id: str, sc: dict[str, Any]) -> dict[str, Any]:
    actions = await db.fetchval("SELECT COUNT(*) FROM events WHERE episode_id=$1 AND type='ledger.mutation' AND agent='green'", episode_id)
    return {"actions": int(actions), "legit_processed": sc["legit_processed"], "legit_blocked": sc["legit_blocked"], "fraud_paid": sc["dollars_extracted"]}


async def _disclosures(episode_id: str) -> dict[str, Any]:
    out = {a: {"daily": 0, "aar": 0, "items": 0} for a in AGENTS}
    rows = await db.fetch(
        "SELECT agent, COUNT(*) FILTER (WHERE day IS NOT NULL) AS daily, COUNT(*) FILTER (WHERE day IS NULL) AS aar, "
        "COALESCE(SUM(jsonb_array_length(CASE WHEN jsonb_typeof(payload->'items')='array' THEN payload->'items' ELSE '[]'::jsonb END)),0) AS items "
        "FROM debriefs WHERE episode_id=$1 GROUP BY agent",
        episode_id,
    )
    for r in rows:
        out[r["agent"]] = {"daily": r["daily"], "aar": r["aar"], "items": int(r["items"])}
    return out


async def _playbooks(lineage_id: str) -> dict[str, list[dict[str, Any]]]:
    rows = await db.fetch(
        "SELECT agent, version, parent_version, generation, episode_id, day, source, content, rationale FROM playbooks "
        "WHERE lineage_id=$1 ORDER BY agent, version",
        lineage_id,
    )
    content: dict[tuple[str, int], Any] = {(r["agent"], r["version"]): r["content"] for r in rows}
    out: dict[str, list[dict[str, Any]]] = {a: [] for a in AGENTS}
    for r in rows:
        parent = content.get((r["agent"], r["parent_version"]), {}) if r["parent_version"] is not None else {}
        out.setdefault(r["agent"], []).append(
            {
                "version": r["version"],
                "parent_version": r["parent_version"],
                "generation": r["generation"],
                "episode_id": r["episode_id"],
                "day": r["day"],
                "source": r["source"],
                "rationale": r["rationale"],
                "content": r["content"],
                "diff": diff(parent, r["content"]),
            }
        )
    return out


async def _generation(ep: Any, runner_gens: int) -> dict[str, Any]:
    sc = await score.compute(ep["id"])
    attacks = await _attack_rules(ep["id"])
    return {
        "generation": ep["generation"],
        "episode_id": ep["id"],
        "seed": ep["seed"],
        "status": ep["status"],
        "days": ep["days"],
        "demo": ep["generation"] > runner_gens,
        "score": sc,
        "credits": await _credits(ep["id"]),
        "red_mix": await _red_mix(ep["id"]),
        "blue_rules": await _rules(ep["id"], attacks),
        "who_beat_whom": _matrix(attacks),
        "green": await _green(ep["id"], sc),
        "disclosures": await _disclosures(ep["id"]),
    }


async def _evolved(lineage_id: str) -> list[dict[str, Any]]:
    rows = await db.fetch(
        "SELECT a.scheme_id, MIN(e.generation) AS first_generation, MIN(a.params->>'parent') AS parent FROM attacks a "
        "JOIN episodes e ON e.id = a.episode_id WHERE e.lineage_id=$1 AND a.scheme_id LIKE 'evolved:%' GROUP BY a.scheme_id ORDER BY a.scheme_id",
        lineage_id,
    )
    return [{"scheme_id": r["scheme_id"], "first_generation": r["first_generation"], "parent": r["parent"]} for r in rows]


def _rule_lifecycle(gens: list[dict[str, Any]]) -> dict[str, Any]:
    gens = [g for g in gens if g["blue_rules"]]  # a generation where no rule fired says nothing about retirement
    seen: dict[str, list[int]] = {}
    for g in gens:
        for r in g["blue_rules"]:
            seen.setdefault(r["rule_id"], []).append(g["generation"])
    first_gen = gens[0]["generation"] if gens else None
    last_gen = gens[-1]["generation"] if gens else None
    out: dict[str, Any] = {"learned_rules": [], "new_rules": [], "retired_rules": []}
    for rule in sorted(seen):
        g = seen[rule]
        if rule.startswith("learned:"):
            out["learned_rules"].append({"rule_id": rule, "first_generation": min(g)})
        if min(g) != first_gen:
            out["new_rules"].append({"rule_id": rule, "first_generation": min(g)})
        if len(gens) > 1 and max(g) != last_gen:
            out["retired_rules"].append({"rule_id": rule, "last_generation": max(g)})
    return out


async def report(lineage_id: str) -> dict[str, Any] | None:
    ln = await _lineage(lineage_id)
    if ln is None:
        return None
    cfg = LineageConfig.model_validate(ln["config"] or {})
    gens = [await _generation(ep, cfg.generations) for ep in await _episodes(lineage_id)]
    return {
        "lineage": {
            "id": ln["id"],
            "name": ln["name"],
            "status": ln["status"],
            "base_seed": ln["base_seed"],
            "current_generation": ln["current_generation"],
            "config": cfg.model_dump(mode="json"),
        },
        "partial": ln["status"] not in ("finished", "failed"),
        "run_card": {
            "seeds": [g["seed"] for g in gens],
            "generations": cfg.generations,
            "demo_generations": [g["generation"] for g in gens if g["demo"]],
            "days": cfg.days,
            "controller_mode": cfg.controller_mode,
            "models": None,  # agent models live in the agent containers; battlefield doesn't know them
            "git_sha": None,  # not plumbed into battlefield yet (would be a new env var)
            "credits": [{"generation": g["generation"], "factory_credits": g["credits"]} for g in gens],
        },
        "generations": gens,
        "red": {"evolved_schemes": await _evolved(lineage_id)},
        "blue": _rule_lifecycle(gens),
        "playbooks": await _playbooks(lineage_id),
    }


def _order(entry: dict[str, Any]) -> tuple[Any, ...]:
    """Logical time: seeds, then per generation its turn-written versions by day, the generation's
    result, then the reflections on it (reflect versions carry the generation they reflect on)."""
    if entry["kind"] == "generation":
        return (entry["generation"], 2, 0, "", 0)
    phase = {"seed": 0, "turn": 1, "reflect": 3, "operator": 3}.get(entry["source"], 3)
    return (entry["generation"], phase, entry["day"] if entry["day"] is not None else -1, entry["agent"], entry["version"])


async def timeline(lineage_id: str) -> dict[str, Any] | None:
    ln = await _lineage(lineage_id)
    if ln is None:
        return None
    cfg = LineageConfig.model_validate(ln["config"] or {})
    gens = []
    for ep in await _episodes(lineage_id):
        d = await _disclosures(ep["id"])
        gens.append(
            {
                "generation": ep["generation"],
                "episode_id": ep["id"],
                "seed": ep["seed"],
                "status": ep["status"],
                "demo": ep["generation"] > cfg.generations,
                "score": await score.compute(ep["id"]),
                "debriefs": {a: {"daily": d[a]["daily"], "aar": d[a]["aar"]} for a in AGENTS},
            }
        )
    entries: list[dict[str, Any]] = [{"kind": "generation", **{k: g[k] for k in ("generation", "episode_id", "seed", "status", "demo", "score")}} for g in gens]
    for agent, versions in (await _playbooks(lineage_id)).items():
        for v in versions:
            entries.append(
                {
                    "kind": "playbook",
                    "agent": agent,
                    **{k: v[k] for k in ("version", "parent_version", "generation", "episode_id", "day", "source", "rationale", "diff")},
                }
            )
    entries.sort(key=_order)
    return {"lineage_id": ln["id"], "status": ln["status"], "partial": ln["status"] not in ("finished", "failed"), "generations": gens, "entries": entries}
