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

from .. import db, turns
from ..config import settings
from ..events import bus
from ..evolution import debrief
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
        # credit guard: None = not yet seeded from `turn.ended` events in this process
        self.credits_total: float | None = None
        self.credit_guard_armed = True
        self.day_pause_sec: float | None = None  # a headless lineage generation's pause; None = DAY_PAUSE_SEC
        self.lineage_id: str | None = None  # set by the lineage runner for the generations it runs (credit cap)


_states: dict[str, EpisodeState] = {}


def state(episode_id: str) -> EpisodeState:
    return _states.setdefault(episode_id, EpisodeState())


async def start(episode_id: str) -> None:
    st = state(episode_id)
    if st.task and not st.task.done():
        return
    await db.execute("UPDATE episodes SET status='running', started_at=COALESCE(started_at, now()) WHERE id=$1", episode_id)
    ep = await db.fetchrow("SELECT * FROM episodes WHERE id=$1", episode_id)
    # once per episode: a resume after a restart on day 0 must not announce the episode again
    if not await db.fetchval("SELECT 1 FROM events WHERE episode_id=$1 AND type='episode.started' LIMIT 1", episode_id):
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
    st.credit_guard_armed = True  # an explicit human action re-arms the credit guard
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
    st.credit_guard_armed = True  # an explicit human action re-arms the credit guard
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
            pause_sec = state(episode_id).day_pause_sec
            if pause_sec is None:
                pause_sec = settings.day_pause_sec
            if pause_sec:
                await asyncio.sleep(pause_sec)
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
        await _seed_credits(episode_id)

        # Idempotent per day: a day that already started (battlefield restarted mid-day, the episode was
        # paused by recover_after_restart and is now resumed) is not injected or announced again, and
        # turns that must not run twice are skipped (red and blue once started, green once ended; see
        # below). legit_traffic.inject has no per-day guard of its own.
        resumed = bool(await db.fetchval("SELECT 1 FROM events WHERE episode_id=$1 AND type='day.started' AND day=$2 LIMIT 1", episode_id, day))
        if resumed:
            log.info("day_resumed", episode_id=episode_id, day=day)
        else:
            counts = await legit_traffic.inject(episode_id, ep["seed"], day)
            await bus.emit(episode_id, day, "day.started", {"day": day, "legit_injected": counts})

        # red. Its writes (attacks, vendors, invoices) are not idempotent, so on a resumed day red counts
        # as done once its turn started or an attack of that day exists, even if the turn never ended.
        if resumed and await _red_started(episode_id, day):
            log.info("turn_skipped_resumed", episode_id=episode_id, day=day, agent="red")
        else:
            await _red_turn(episode_id, day, mode, ep, st)

        # green (controller mode may have been toggled mid-day; re-read)
        mode = await db.fetchval("SELECT controller_mode FROM episodes WHERE id=$1", episode_id)
        if resumed and await _turn_ended(episode_id, day, "green"):
            log.info("turn_skipped_resumed", episode_id=episode_id, day=day, agent="green")
        else:
            await _turn(episode_id, day, "green", mode, {})

        # blue audit: flags and reports are plain inserts, so a started audit is not re-run either
        if resumed and await _turn_started(episode_id, day, "blue"):
            log.info("turn_skipped_resumed", episode_id=episode_id, day=day, agent="blue")
        else:
            await _blue_audit(episode_id, day)

        sc = await score.end_of_day(episode_id, day)
        if ctx := await debrief.context(episode_id):
            await debrief.deliver(episode_id, day, ctx)  # lineage episodes only: score.updated → debrief.delivered* → day.ended
        await bus.emit(episode_id, day, "day.ended", {"day": day})
        await db.execute("UPDATE episodes SET current_day=$2 WHERE id=$1", episode_id, day + 1)
        if day + 1 >= ep["days"]:
            await _finish(episode_id, day + 1)
        return {"day": day, "score": sc}


async def _turn_event(episode_id: str, day: int, agent: str, type_: str) -> bool:
    return bool(
        await db.fetchval("SELECT 1 FROM events WHERE episode_id=$1 AND type=$2 AND day=$3 AND payload->>'agent'=$4 LIMIT 1", episode_id, type_, day, agent)
    )


async def _turn_ended(episode_id: str, day: int, agent: str) -> bool:
    """Did this agent's turn already finish on this day (before a restart)?"""
    return await _turn_event(episode_id, day, agent, "turn.ended")


async def _turn_started(episode_id: str, day: int, agent: str) -> bool:
    return await _turn_event(episode_id, day, agent, "turn.started")


async def _red_started(episode_id: str, day: int) -> bool:
    if await _turn_started(episode_id, day, "red"):
        return True
    return bool(await db.fetchval("SELECT 1 FROM attacks WHERE episode_id=$1 AND day_launched=$2 LIMIT 1", episode_id, day))


async def _red_turn(episode_id: str, day: int, mode: str, ep: Any, st: EpisodeState) -> None:
    options: dict[str, Any] = {}
    if st.forced_attack:
        options = st.forced_attack
        st.forced_attack = None
    elif ep["attack_plan"]:
        for item in ep["attack_plan"]:
            if item.get("day") == day:
                options = {"scheme_id": item["scheme_id"], "params": item.get("params", {})}
    await _turn(episode_id, day, "red", mode, options)


async def _blue_audit(episode_id: str, day: int) -> None:
    blue_inputs = await _drain_inputs(episode_id, "blue", day)
    ctx = await debrief.context(episode_id)
    extra = await debrief.turn_fields(episode_id, "blue", day, ctx) if ctx else {}  # lineage + debrief, top-level on /audit
    await bus.emit(episode_id, day, "turn.started", {"agent": "blue", "inputs": len(blue_inputs)})
    with turns.turn(episode_id, "blue", day):
        res = await agents.audit(episode_id, day, blue_inputs, **extra)
    blue_credits = (res.get("usage") or {}).get("factory_credits")
    await bus.emit(
        episode_id,
        day,
        "turn.ended",
        {"agent": "blue", "ok": bool(res.get("ok")), "summary": res.get("summary", ""), "factory_credits": blue_credits},
    )
    await _charge_credits(episode_id, day, blue_credits)


async def _drain_inputs(episode_id: str, agent: str, day: int) -> list[dict[str, Any]]:
    rows = await db.fetch(
        "SELECT id, source, payload, created_at FROM inputs WHERE episode_id=$1 AND target=$2 AND consumed_day IS NULL ORDER BY id", episode_id, agent
    )
    if rows:
        await db.execute("UPDATE inputs SET consumed_day=$3 WHERE episode_id=$1 AND target=$2 AND consumed_day IS NULL", episode_id, agent, day)
    return [{"id": r["id"], "source": r["source"], "payload": r["payload"]} for r in rows]


async def _turn(episode_id: str, day: int, agent: str, mode: str, options: dict[str, Any]) -> None:
    options = {**options, "inputs": await _drain_inputs(episode_id, agent, day)}
    if ctx := await debrief.context(episode_id):
        options.update(await debrief.turn_fields(episode_id, agent, day, ctx))  # options.lineage / options.debrief
    await bus.emit(episode_id, day, "turn.started", {"agent": agent, "inputs": len(options["inputs"])})
    with turns.turn(episode_id, agent, day):  # agent writes are accepted only while this is active
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
    await _charge_credits(episode_id, day, usage.get("factory_credits"))


# ---------- credit guard ----------


def credits_of(value: Any) -> float:
    """A turn's `factory_credits` as a float. DRY_RUN / missing / garbage → 0."""
    if value is None or isinstance(value, bool):
        return 0.0
    try:
        return max(float(value), 0.0)
    except (TypeError, ValueError):
        return 0.0


def credit_guard_tripped(total: float, limit: float) -> bool:
    """True when the episode has spent at least `limit` credits. `limit <= 0` disables the guard."""
    return limit > 0 and total >= limit


async def _seed_credits(episode_id: str) -> None:
    """Lazily seed the running total from this episode's `turn.ended` events (fresh process/restart).

    Called at the top of run_day, before any turn of the day, so the sum never includes a turn that
    _charge_credits is about to add.
    """
    st = state(episode_id)
    if st.credits_total is not None:
        return
    total = await db.fetchval(
        "SELECT COALESCE(SUM((payload->>'factory_credits')::float8), 0) FROM events "
        "WHERE episode_id=$1 AND type='turn.ended' AND jsonb_typeof(payload->'factory_credits')='number'",
        episode_id,
    )
    st.credits_total = float(total or 0)


async def _charge_credits(episode_id: str, day: int, factory_credits: Any) -> None:
    """Add one turn's credits to the episode total and pause the episode if it crossed the limit.

    Re-arm policy: a trip disarms the guard, so the rest of the current day (which still runs to
    `day.ended` to keep the events.md ordering) cannot emit a second pause. resume() and step()
    re-arm it. While armed, the guard trips only on a turn that actually spent credits (> 0) and
    leaves the total >= limit; so after a resume an over-limit episode gets exactly one more paid
    turn before pausing again, and zero-credit turns (DRY_RUN) never trip. Raising the limit means
    restarting battlefield with a higher MAX_CREDITS_PER_EPISODE.
    """
    st = state(episode_id)
    spent = credits_of(factory_credits)
    if st.credits_total is None:
        # turn ran outside run_day (shouldn't happen): the seed sum already includes this turn's
        # just-emitted turn.ended, so seed instead of adding.
        await _seed_credits(episode_id)
    else:
        st.credits_total += spent
    if st.lineage_id is not None:
        from . import lineage  # late: lineage imports this module

        await lineage.charge_turn(st.lineage_id, episode_id, day, spent)  # the lineage's config.max_credits
    limit = settings.max_credits_per_episode  # MAX_CREDITS_PER_EPISODE; 0 disables the guard
    total = st.credits_total or 0.0
    if not (st.credit_guard_armed and spent > 0 and credit_guard_tripped(total, limit)):
        return
    st.credit_guard_armed = False
    log.warning("credit_guard_tripped", episode_id=episode_id, day=day, agent="battlefield", credits=total, limit=limit)
    await bus.emit(episode_id, day, "error", {"where": "credit_guard", "message": f"episode paused at {total:g} credits (limit {limit:g})"})
    status = await db.fetchval("SELECT status FROM episodes WHERE id=$1", episode_id)
    if status == "paused":  # e.g. a manual step: stay paused, don't emit a second episode.paused
        st.pause.clear()
    else:
        await pause(episode_id)


async def _finish(episode_id: str, day: int) -> None:
    ep = await db.fetchrow("SELECT status FROM episodes WHERE id=$1", episode_id)
    if ep and ep["status"] == "finished":
        return
    final = await score.compute(episode_id)
    await db.execute("UPDATE episodes SET status='finished', finished_at=now() WHERE id=$1", episode_id)
    await bus.emit(episode_id, day, "episode.ended", {"final_score": final})
    gen = await db.fetchrow("SELECT lineage_id, generation FROM episodes WHERE id=$1 AND lineage_id IS NOT NULL", episode_id)
    if gen is not None:  # every lineage generation, runner-owned or a demo: episode.ended → generation.ended
        await bus.emit(episode_id, day, "generation.ended", {"lineage_id": gen["lineage_id"], "generation": gen["generation"], "score": final})
        from . import lineage  # late: lineage imports this module

        lineage.reflect_demo_later(gen["lineage_id"], gen["generation"])  # a demo reflects too; no-op for the loop's own
