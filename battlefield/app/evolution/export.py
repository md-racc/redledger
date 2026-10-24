"""One lineage as one JSON document: the source of `make lineage-export`. Owner: Dev Ad.

Operator only, and it contains ground truth (`origin`, `attack_id`, every red row): it is a local log
bundle for reports and post-mortems, never something an agent or the browser sees. One query per table
over all of the lineage's episodes (no per-generation round trips), plus one score per generation.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .. import db
from ..orchestrator.runner import credits_of
from ..scoring import score

AGENTS = ("red", "green", "blue")


def _by_episode(rows: list[Any]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in db.rows_to_list(rows):
        out[r["episode_id"]].append(r)
    return out


def _credits(events: list[dict[str, Any]]) -> dict[str, Any]:
    """factory_credits per agent and day, from turn.ended (DRY_RUN / missing → 0)."""
    by_day: list[dict[str, Any]] = []
    total: dict[str, float] = {a: 0.0 for a in AGENTS}
    for e in events:
        if e["type"] != "turn.ended":
            continue
        agent = (e["payload"] or {}).get("agent")
        spent = credits_of((e["payload"] or {}).get("factory_credits"))
        by_day.append({"day": e["day"], "agent": agent, "factory_credits": spent})
        if agent in total:
            total[agent] += spent
    return {"by_day": by_day, "total": total}


def _playbooks(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {a: [] for a in AGENTS}
    for r in rows:
        out[r["agent"]].append(r)
    return out


async def bundle(lineage_id: str, generation: int | None = None) -> dict[str, Any] | None:
    """None when the lineage does not exist. `generation` limits `generations` to that one."""
    ln = await db.fetchrow("SELECT * FROM lineages WHERE id=$1", lineage_id)
    if ln is None:
        return None
    eps = await db.fetch("SELECT * FROM episodes WHERE lineage_id=$1 AND ($2::int IS NULL OR generation=$2) ORDER BY generation", lineage_id, generation)
    ids = [e["id"] for e in eps]
    events = _by_episode(await db.fetch("SELECT * FROM events WHERE episode_id = ANY($1::text[]) ORDER BY id", ids))
    audit = _by_episode(await db.fetch("SELECT * FROM audit_log WHERE episode_id = ANY($1::text[]) ORDER BY id", ids))
    verdicts = _by_episode(await db.fetch("SELECT * FROM verdicts WHERE episode_id = ANY($1::text[]) ORDER BY created_at, id", ids))
    attacks = _by_episode(await db.fetch("SELECT * FROM attacks WHERE episode_id = ANY($1::text[]) ORDER BY day_launched, created_at, id", ids))
    debriefs = _by_episode(
        await db.fetch("SELECT * FROM debriefs WHERE lineage_id=$1 AND episode_id = ANY($2::text[]) ORDER BY day NULLS LAST, id", lineage_id, ids)
    )
    pbs = db.rows_to_list(await db.fetch("SELECT * FROM playbooks WHERE lineage_id=$1 ORDER BY agent, version", lineage_id))

    gens = []
    for e in eps:
        ev = events.get(e["id"], [])
        gens.append(
            {
                "generation": e["generation"],
                "episode_id": e["id"],
                "seed": e["seed"],
                "status": e["status"],
                "episode": db.row_to_dict(e),
                "score": await score.compute(e["id"]),
                "credits": _credits(ev),
                "events": ev,
                "audit_log": audit.get(e["id"], []),
                "verdicts": verdicts.get(e["id"], []),
                "attacks": attacks.get(e["id"], []),
                "debriefs": debriefs.get(e["id"], []),
                "playbooks": _playbooks([p for p in pbs if p["generation"] == e["generation"]]),
            }
        )
    return {"lineage": db.row_to_dict(ln), "playbooks": _playbooks(pbs), "generations": gens}
