"""Which agent turn is running, per episode. Owner: Dev Ad.

The orchestrator marks a turn active for exactly as long as it is waiting on that agent
(`runner._turn`, the blue audit). Agent writes are accepted only for the active (episode, agent,
day): `auth.caller` 409s any other X-Agent write. So a turn battlefield has given up on (its /turn
HTTP wait timed out) or one orphaned by a battlefield restart (nothing is active in a new process)
cannot keep writing into the books. Reads are always allowed.

In-process, like the gate's escalation waiters: battlefield must run as a single uvicorn worker.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

NO_ACTIVE_TURN = "no active turn for this agent"

# Tests switch this off to call agent write routes directly; the guard's own tests switch it on.
ENFORCE = True


class NoActiveTurnError(Exception):
    """An agent write outside that agent's active turn; app.main turns it into 409 {"error": ...}."""


@dataclass(frozen=True)
class ActiveTurn:
    agent: str
    day: int
    turn_id: str


_active: dict[str, ActiveTurn] = {}


def active(episode_id: str) -> ActiveTurn | None:
    return _active.get(episode_id)


@contextmanager
def turn(episode_id: str, agent: str, day: int) -> Iterator[ActiveTurn]:
    """Mark this agent's turn active for the duration of the block (cleared on exit, error or cancel)."""
    t = ActiveTurn(agent=agent, day=day, turn_id=uuid.uuid4().hex)
    _active[episode_id] = t
    try:
        yield t
    finally:
        if _active.get(episode_id) is t:
            del _active[episode_id]


def may_write(episode_id: str, agent: str, day: int) -> bool:
    if not ENFORCE:
        return True
    t = _active.get(episode_id)
    return t is not None and t.agent == agent and t.day == day
