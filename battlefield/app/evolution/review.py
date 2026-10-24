"""After-action reviews: what each agent is shown between generations. Owner: Dev Ad.

contracts/agent-service.md `POST /reflect`. Built once the generation's episode has finished, so
nothing is still in play: every attack of the generation is covered whether or not it resolved (its
outcome as scored at the end), plus the legit items kept out of daily debriefs (`debrief.legit_items`).
Stored in `debriefs` with `day` NULL exactly as sent; a re-run after a restart sends the stored copy.
"""

from __future__ import annotations

from typing import Any

from agentkit.models import LineageConfig

from .. import db
from ..scoring import score
from . import debrief

_RULES_SQL = """
SELECT r.rule_id, COUNT(*) AS fired,
       COUNT(*) FILTER (WHERE x.origin = 'red') AS on_red,
       COUNT(*) FILTER (WHERE x.origin = 'sim') AS on_legit
FROM verdicts v
CROSS JOIN LATERAL jsonb_array_elements_text(v.rules_fired) AS r(rule_id)
CROSS JOIN LATERAL (SELECT COALESCE(
    (SELECT origin FROM invoices WHERE id = v.entity_id),
    (SELECT origin FROM expenses WHERE id = v.entity_id),
    (SELECT origin FROM vendor_changes WHERE id = v.entity_id),
    (SELECT origin FROM vendors WHERE id = v.entity_id)) AS origin) x
WHERE v.episode_id = $1
GROUP BY r.rule_id ORDER BY fired DESC, r.rule_id
"""


async def close(episode_id: str) -> None:
    """The episode is over: every attack not yet revealed is revealed by the review, as of the last day.
    Scoring is unchanged (score.compute evaluated as of `days` sees every event of the episode)."""
    await db.execute(
        "UPDATE attacks a SET revealed_day = e.days FROM episodes e WHERE a.episode_id = $1 AND e.id = a.episode_id AND a.revealed_day IS NULL", episode_id
    )


async def persist(lineage_id: str, generation: int, ep: Any, agent: str, cfg: LineageConfig) -> dict[str, Any]:
    """The review for `agent`, stored in `debriefs` (day NULL) the first time and reused after that."""
    stored = await db.fetchval(
        "SELECT payload FROM debriefs WHERE lineage_id=$1 AND generation=$2 AND agent=$3 AND day IS NULL ORDER BY id LIMIT 1", lineage_id, generation, agent
    )
    if stored is not None:
        return stored
    payload = await build(lineage_id, generation, ep, agent, cfg)
    await db.execute(
        "INSERT INTO debriefs (lineage_id, generation, episode_id, day, agent, payload) VALUES ($1,$2,$3,NULL,$4,$5)",
        lineage_id,
        generation,
        ep["id"],
        agent,
        payload,
    )
    return payload


async def build(lineage_id: str, generation: int, ep: Any, agent: str, cfg: LineageConfig) -> dict[str, Any]:
    items = [debrief.public(it) for it in (await debrief.attack_items(ep["id"], -(10**6)))[agent]]
    if agent in ("blue", "green"):
        items += (await debrief.legit_items(ep["id"]))[agent]
    out: dict[str, Any] = {"generation": generation, "episode_id": ep["id"], "seed": ep["seed"], "score": await score.compute(ep["id"]), "items": items}
    if agent == "blue":
        out["rules"] = await rules(ep["id"])
    out["history"] = await history(lineage_id, generation, cfg.reveal_generations - 1, agent)
    return out


async def rules(episode_id: str) -> list[dict[str, Any]]:
    """Blue's precision table: per rule id, verdicts it fired on, split by the judged entity's origin."""
    return [{"rule_id": r["rule_id"], "fired": r["fired"], "on_red": r["on_red"], "on_legit": r["on_legit"]} for r in await db.fetch(_RULES_SQL, episode_id)]


async def history(lineage_id: str, generation: int, n: int, agent: str) -> list[dict[str, Any]]:
    """The `n` generations before `generation`, oldest first: seed, score and per-agent counts."""
    if n <= 0:
        return []
    eps = await db.fetch(
        "SELECT id, generation, seed FROM episodes WHERE lineage_id=$1 AND generation < $2 AND generation >= $3 ORDER BY generation",
        lineage_id,
        generation,
        generation - n,
    )
    out = []
    for e in eps:
        by_scheme: dict[str, dict[str, int]] = {}
        for r in await db.fetch("SELECT scheme_id, outcome, COUNT(*) AS n FROM attacks WHERE episode_id=$1 GROUP BY scheme_id, outcome", e["id"]):
            by_scheme.setdefault(r["scheme_id"], {})[r["outcome"]] = r["n"]
        summary: dict[str, Any] = {"attacks_by_scheme": by_scheme}
        if agent == "blue":
            summary["rules"] = {r["rule_id"]: {"fired": r["fired"], "on_red": r["on_red"], "on_legit": r["on_legit"]} for r in await rules(e["id"])}
        out.append({"generation": e["generation"], "seed": e["seed"], "score": await score.compute(e["id"]), "summary": summary})
    return out
