"""At most one active run per battlefield. Owner: Dev Ad.

Each agent service serves one turn at a time (agentkit's turn lock), so two runs driving the agents at
once collide: the loser's turns all come back `409 turn already in progress` and record nothing.
"Active" = a non-replay episode with status running, an episode being stepped, or a lineage with
status running. A lineage's own generation episodes are part of that lineage's run. Replays never
call agents and are ignored.

Callers check `blocker()` and flip status while holding `lineage._control` (battlefield is a single
worker), so two concurrent starts can never both pass. Restart recovery already pauses every running
episode and lineage, so nothing stale is left active after a restart; `_stepping` is in-process only.
"""

from __future__ import annotations

from typing import Any

from .. import db

REPLAY_PREFIX = "replay_"

_stepping: set[str] = set()


class ActiveRunError(Exception):
    """Starting this run would overlap the active one → 409 (contracts: one active run at a time)."""

    def __init__(self, episode_id: str | None, lineage_id: str | None) -> None:
        super().__init__("another run is active")
        self.episode_id = episode_id
        self.lineage_id = lineage_id

    def body(self) -> dict[str, Any]:
        return {"error": "another run is active", "episode_id": self.episode_id, "lineage_id": self.lineage_id}


async def blocker(*, episode_id: str | None = None, lineage_id: str | None = None) -> ActiveRunError | None:
    """The active run that `episode_id` / `lineage_id` would overlap, or None.

    An episode that belongs to a lineage is part of that lineage's run, so it never blocks itself."""
    own_lineage = lineage_id
    if episode_id is not None and own_lineage is None:
        own_lineage = await db.fetchval("SELECT lineage_id FROM episodes WHERE id=$1", episode_id)
    for ep in sorted(_stepping):
        if ep != episode_id and await _other_lineage(ep, own_lineage):
            return ActiveRunError(ep, await db.fetchval("SELECT lineage_id FROM episodes WHERE id=$1", ep))
    row = await db.fetchrow(
        "SELECT id, lineage_id FROM episodes WHERE status='running' AND left(id, length($3)) <> $3 "
        "AND id IS DISTINCT FROM $1 AND ($2::text IS NULL OR lineage_id IS DISTINCT FROM $2) ORDER BY id LIMIT 1",
        episode_id,
        own_lineage,
        REPLAY_PREFIX,
    )
    if row is not None:
        return ActiveRunError(row["id"], row["lineage_id"])
    ln = await db.fetchrow(
        "SELECT id, current_generation FROM lineages WHERE status='running' AND ($1::text IS NULL OR id <> $1) ORDER BY id LIMIT 1",
        own_lineage,
    )
    if ln is not None:
        ep = await db.fetchval("SELECT id FROM episodes WHERE lineage_id=$1 AND generation=$2", ln["id"], ln["current_generation"])
        return ActiveRunError(ep, ln["id"])
    return None


async def _other_lineage(episode_id: str, own_lineage: str | None) -> bool:
    if own_lineage is None:
        return True
    return await db.fetchval("SELECT lineage_id FROM episodes WHERE id=$1", episode_id) != own_lineage


def begin_step(episode_id: str) -> None:
    """Mark an episode active for the duration of a manual step (its status stays paused)."""
    _stepping.add(episode_id)


def end_step(episode_id: str) -> None:
    _stepping.discard(episode_id)
