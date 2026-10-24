"""Episode runner: the clock. Owner: Dev Ad.

One asyncio task per running episode. A day is:
  day.started → inject legit traffic → red /turn → green /turn → blue /audit → resolve attacks →
  score.updated → day.ended
Pause/resume/step are supported; a forced attack (judge pick) is queued and consumed by the next
red turn.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from .. import db
from ..config import settings
from ..events import bus
from ..scoring import score
from . import agents, legit_traffic

log = structlog.get_logger(__name__)


class EpisodeState:
    def __init__(self) -> None:
        self.task: asyncio.Task | None = None
        self.pause = asyncio.Event()
        self.pause.set()  # set = running
        self.forced_attack: dict[str, Any] | None = None
        self.day_lock = asyncio.Lock()


_states: dict[str, EpisodeState] = {}


def state(episode_id: str) -> EpisodeState:
    return _states.setdefault(episode_id, EpisodeState())


async def start(episode_id: str) -> None:
    st = state(episode_id)
    if st.task and not st.task.done():
        return
    await db.execute("UPDATE episodes SET status='running', started_at=COALESCE(started_at, now()) WHERE id=$1", episode_id)
    ep = await db.fetchrow("SELECT * FROM episodes WHERE id=$1", episode_id)
    if ep["current_day"] == 0:
        await bus.emit(episode_id, 0, "episode.started", {"controller_mode": ep["controller_mode"], "days": ep["days"], "seed": ep["seed"]})
    st.pause.set()
    st.task = asyncio.create_task(_loop(episode_id), name=f"episode-{episode_id}")


async def pause(episode_id: str) -> None:
    st = state(episode_id)
    st.pause.clear()
    await db.execute("UPDATE episodes SET status='paused' WHERE id=$1", episode_id)
    ep = await db.fetchrow("SELECT current_day FROM episodes WHERE id=$1", episode_id)
    await bus.emit(episode_id, ep["current_day"], "episode.paused", {})


async def resume(episode_id: str) -> None:
    st = state(episode_id)
    await db.execute("UPDATE episodes SET status='running' WHERE id=$1", episode_id)
    ep = await db.fetchrow("SELECT current_day FROM episodes WHERE id=$1", episode_id)
    await bus.emit(episode_id, ep["current_day"], "episode.resumed", {})
    if st.task is None or st.task.done():
        await start(episode_id)
    st.pause.set()


async def step(episode_id: str) -> dict[str, Any]:
    """Run exactly one day. Episode must not be actively looping."""
    st = state(episode_id)
    if st.task and not st.task.done() and st.pause.is_set():
        raise RuntimeError("episode is running; pause first")
    ep = await db.fetchrow("SELECT * FROM episodes WHERE id=$1", episode_id)
    if ep["status"] == "created":
        await db.execute("UPDATE episodes SET status='paused', started_at=now() WHERE id=$1", episode_id)
        await bus.emit(episode_id, 0, "episode.started", {"controller_mode": ep["controller_mode"], "days": ep["days"], "seed": ep["seed"]})
    return await run_day(episode_id)


def force_attack(episode_id: str, scheme_id: str, params: dict[str, Any] | None) -> None:
    state(episode_id).forced_attack = {"scheme_id": scheme_id, "params": params or {}}


async def set_controller(episode_id: str, mode: str) -> None:
    ep = await db.fetchrow("SELECT controller_mode, current_day FROM episodes WHERE id=$1", episode_id)
    await db.execute("UPDATE episodes SET controller_mode=$2 WHERE id=$1", episode_id, mode)
    await bus.emit(episode_id, ep["current_day"], "controller.changed", {"from": ep["controller_mode"], "to": mode}, agent="human")


# ---------- internals ----------


async def _loop(episode_id: str) -> None:
    try:
        while True:
            await state(episode_id).pause.wait()
            ep = await db.fetchrow("SELECT * FROM episodes WHERE id=$1", episode_id)
            if ep["current_day"] >= ep["days"]:
                await _finish(episode_id, ep["current_day"])
                return
            await run_day(episode_id)
            if settings.day_pause_sec:
                await asyncio.sleep(settings.day_pause_sec)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.exception("episode_loop_failed", episode_id=episode_id)
        await db.execute("UPDATE episodes SET status='failed' WHERE id=$1", episode_id)
        ep = await db.fetchrow("SELECT current_day FROM episodes WHERE id=$1", episode_id)
        await bus.emit(episode_id, ep["current_day"], "error", {"where": "orchestrator", "message": str(e)})


async def run_day(episode_id: str) -> dict[str, Any]:
    st = state(episode_id)
    async with st.day_lock:
        ep = await db.fetchrow("SELECT * FROM episodes WHERE id=$1", episode_id)
        day = ep["current_day"]
        if day >= ep["days"]:
            await _finish(episode_id, day)
            return {"done": True}
        mode = ep["controller_mode"]

        counts = await legit_traffic.inject(episode_id, ep["seed"], day)
        await bus.emit(episode_id, day, "day.started", {"day": day, "legit_injected": counts})

        # red
        options: dict[str, Any] = {}
        if st.forced_attack:
            options = st.forced_attack
            st.forced_attack = None
        elif ep["attack_plan"]:
            for item in ep["attack_plan"]:
                if item.get("day") == day:
                    options = {"scheme_id": item["scheme_id"], "params": item.get("params", {})}
        await _turn(episode_id, day, "red", mode, options)

        # green (controller mode may have been toggled mid-day; re-read)
        mode = await db.fetchval("SELECT controller_mode FROM episodes WHERE id=$1", episode_id)
        await _turn(episode_id, day, "green", mode, {})

        # blue audit
        blue_inputs = await _drain_inputs(episode_id, "blue", day)
        await bus.emit(episode_id, day, "turn.started", {"agent": "blue", "inputs": len(blue_inputs)})
        res = await agents.audit(episode_id, day, blue_inputs)
        await bus.emit(episode_id, day, "turn.ended", {"agent": "blue", "ok": bool(res.get("ok")), "summary": res.get("summary", "")})

        sc = await score.end_of_day(episode_id, day)
        await bus.emit(episode_id, day, "day.ended", {"day": day})
        await db.execute("UPDATE episodes SET current_day=$2 WHERE id=$1", episode_id, day + 1)
        if day + 1 >= ep["days"]:
            await _finish(episode_id, day + 1)
        return {"day": day, "score": sc}


async def _drain_inputs(episode_id: str, agent: str, day: int) -> list[dict[str, Any]]:
    rows = await db.fetch(
        "SELECT id, source, payload, created_at FROM inputs WHERE episode_id=$1 AND target=$2 AND consumed_day IS NULL ORDER BY id", episode_id, agent
    )
    if rows:
        await db.execute("UPDATE inputs SET consumed_day=$3 WHERE episode_id=$1 AND target=$2 AND consumed_day IS NULL", episode_id, agent, day)
    return [{"id": r["id"], "source": r["source"], "payload": r["payload"]} for r in rows]


async def _turn(episode_id: str, day: int, agent: str, mode: str, options: dict[str, Any]) -> None:
    options = {**options, "inputs": await _drain_inputs(episode_id, agent, day)}
    await bus.emit(episode_id, day, "turn.started", {"agent": agent, "inputs": len(options["inputs"])})
    res = await agents.turn(agent, episode_id, day, mode, options)
    usage = res.get("usage") or {}
    await bus.emit(
        episode_id,
        day,
        "turn.ended",
        {
            "agent": agent,
            "ok": bool(res.get("ok")),
            "summary": (res.get("summary") or "")[:1000],
            "duration_sec": res.get("duration_sec", 0),
            "factory_credits": usage.get("factory_credits"),
        },
    )


async def _finish(episode_id: str, day: int) -> None:
    ep = await db.fetchrow("SELECT status FROM episodes WHERE id=$1", episode_id)
    if ep and ep["status"] == "finished":
        return
    final = await score.compute(episode_id)
    await db.execute("UPDATE episodes SET status='finished', finished_at=now() WHERE id=$1", episode_id)
    await bus.emit(episode_id, day, "episode.ended", {"final_score": final})
