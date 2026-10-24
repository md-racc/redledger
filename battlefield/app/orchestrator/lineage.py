"""Lineage runner: generations of episodes with reflection between them. Owner: Dev Ad.

docs/EVOLUTION-DESIGN.md §2, contracts (ledger-api `/lineages*`, events.md, agent-service.md
`/reflect`). One asyncio task per running lineage, at most one running lineage per battlefield (agent
services serve one turn at a time). Generation g:

  create episode (seed base_seed + g) → playbook.updated(reflect)* → generation.started →
  [episode runs on the normal runner] → generation.ended → per agent: after-action review → /reflect

Progress lives in the DB, so a restart (lineage → paused) resumes where it stopped:
`lineages.current_generation` is the last generation created; generation g's reflection is done once
generation g+1 exists (or the lineage is finished). A reflection interrupted by a restart re-runs:
its review row is reused and an agent that already wrote a reflect version for g is skipped.
"""

from __future__ import annotations

import asyncio
from typing import Any

import asyncpg
import structlog

from agentkit.models import LineageConfig
from seed import company

from .. import db
from ..events import bus
from ..evolution import review
from ..scoring import score
from . import active, agents, runner

log = structlog.get_logger(__name__)

AGENTS = ("red", "green", "blue")
POLL_SEC = 1.0  # how often the loop re-checks a paused generation episode


class LineageState:
    def __init__(self) -> None:
        self.task: asyncio.Task | None = None
        self.gate = asyncio.Event()  # set = running
        self.gate.set()


_states: dict[str, LineageState] = {}
_credits: dict[str, float] = {}  # lineage → summed factory_credits (turns + reflections), lazily seeded
_armed: dict[str, bool] = {}
_reflect_spent: dict[str, float] = {}  # reflect usage has no event to re-seed from (in-memory only)
_reflect_done: set[tuple[str, int, str]] = set()  # (lineage, generation, agent) answered in this process
_demo_locks: dict[str, asyncio.Lock] = {}  # one demo reflection at a time per lineage
_background: set[asyncio.Task] = set()  # demo reflections started from runner._finish (kept referenced)
_demo_tasks: dict[tuple[str, int], asyncio.Task] = {}  # (lineage, generation) → its demo reflection
DEMO_REFLECT_WAIT_SEC = 60.0  # how long POST /episodes {lineage_id} waits for the previous demo's reflection


def state(lineage_id: str) -> LineageState:
    return _states.setdefault(lineage_id, LineageState())


def config(row: Any) -> LineageConfig:
    return LineageConfig.model_validate(row["config"] or {})


async def seed_playbooks(conn: Any, lineage_id: str) -> None:
    """Version 0 ({}, source seed, generation 0) of each agent's playbook."""
    for agent in AGENTS:
        await conn.execute(
            "INSERT INTO playbooks (lineage_id, agent, version, generation, source, content) VALUES ($1,$2,0,0,'seed','{}'::jsonb)"
            " ON CONFLICT (lineage_id, agent, version) DO NOTHING",
            lineage_id,
            agent,
        )


async def episode_of(lineage_id: str, generation: int) -> Any:
    return await db.fetchrow("SELECT * FROM episodes WHERE lineage_id=$1 AND generation=$2", lineage_id, generation)


async def create_generation(lineage_id: str, generation: int, *, seed: int, days: int, mode: str, attack_plan: Any = None) -> str:
    """Insert generation `generation`'s episode, seed its company, bump current_generation, announce it.

    A demo (the lineage is finished or failed) first waits, up to DEMO_REFLECT_WAIT_SEC, for the previous
    demo's reflection (restarted if a restart lost it), so it starts from reflected playbooks. Past that it
    starts from the current playbooks, and a reflection that finishes after this episode exists is discarded
    (`_write_reflect`): the request must stay well under the edge's 100 s timeout."""
    try:
        await asyncio.wait_for(asyncio.shield(reflect_demo_later(lineage_id, generation - 1)), DEMO_REFLECT_WAIT_SEC)
    except TimeoutError:
        prev = await episode_of(lineage_id, generation - 1)
        log.warning(
            "demo_reflect_still_running",
            lineage_id=lineage_id,
            episode_id=prev["id"] if prev else None,
            generation=generation - 1,
            wait_sec=DEMO_REFLECT_WAIT_SEC,
        )
    eid = db.new_id("ep")
    async with db.pool().acquire() as conn, conn.transaction():
        await conn.execute(_GENERATION_LOCK, lineage_id)  # serialises with a late reflection's write (_write_reflect)
        await conn.execute(
            "INSERT INTO episodes (id, seed, controller_mode, days, attack_plan, lineage_id, generation) VALUES ($1,$2,$3,$4,$5,$6,$7)",
            eid,
            seed,
            mode,
            days,
            attack_plan,
            lineage_id,
            generation,
        )
        await conn.execute("UPDATE lineages SET current_generation=$2 WHERE id=$1", lineage_id, generation)
    await company.seed_episode(eid, seed)
    await announce(eid)
    return eid


async def discard_unannounced(ep: Any) -> bool:
    """A generation episode still `created` with no `generation.started` was interrupted between its insert
    and its announcement (possibly mid-seed). Nothing ran on it: delete it (ledger rows cascade) and its
    events, and step current_generation back so it is created afresh. True if it was discarded."""
    if ep["status"] != "created" or await db.fetchval("SELECT 1 FROM events WHERE episode_id=$1 AND type='generation.started' LIMIT 1", ep["id"]):
        return False
    async with db.pool().acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM events WHERE episode_id=$1", ep["id"])
        await conn.execute("DELETE FROM episodes WHERE id=$1", ep["id"])
        await conn.execute("UPDATE lineages SET current_generation=$2 WHERE id=$1", ep["lineage_id"], ep["generation"] - 1)
    log.warning("generation_discarded_unannounced", lineage_id=ep["lineage_id"], episode_id=ep["id"], generation=ep["generation"])
    return True


async def announce(episode_id: str) -> None:
    """Day 0 prefix of a generation's episode (events.md): playbook.updated(reflect)* → generation.started.
    Once per episode; episode.started follows when the runner starts it."""
    if await db.fetchval("SELECT 1 FROM events WHERE episode_id=$1 AND type='generation.started' LIMIT 1", episode_id):
        return
    ep = await db.fetchrow("SELECT lineage_id, generation, seed FROM episodes WHERE id=$1", episode_id)
    lid, g = ep["lineage_id"], ep["generation"]
    for p in await db.fetch("SELECT * FROM playbooks WHERE lineage_id=$1 AND source='reflect' AND generation=$2 ORDER BY agent, version", lid, g - 1):
        if await db.fetchval(
            "SELECT 1 FROM events WHERE episode_id=$1 AND type='playbook.updated' AND payload->>'agent'=$2 AND (payload->>'version')::int=$3 LIMIT 1",
            episode_id,
            p["agent"],
            p["version"],
        ):
            continue  # emitted before an interruption: once per version
        await bus.emit(
            episode_id,
            0,
            "playbook.updated",
            {
                "agent": p["agent"],
                "version": p["version"],
                "parent_version": p["parent_version"],
                "generation": g - 1,
                "source": "reflect",
                "rationale": p["rationale"],
            },
        )
    versions = {r["agent"]: r["v"] for r in await db.fetch("SELECT agent, MAX(version) AS v FROM playbooks WHERE lineage_id=$1 GROUP BY agent", lid)}
    await bus.emit(
        episode_id,
        0,
        "generation.started",
        {"lineage_id": lid, "generation": g, "seed": ep["seed"], "playbook_versions": {a: versions.get(a, 0) for a in AGENTS}},
    )


# ---------- control (called by api/control.py) ----------
#
# Status transitions are conditional UPDATEs under one process-wide lock (battlefield is a single
# worker), so two concurrent starts/resumes can never spawn two loops or run two lineages at once.

_control = asyncio.Lock()
_ONLY_ONE = "AND NOT EXISTS (SELECT 1 FROM lineages o WHERE o.status='running' AND o.id<>$1)"


async def start(lineage_id: str) -> bool:
    """created → running and spawn the loop. False (→ 409) if not created or another lineage runs."""
    async with _control:
        if b := await active.blocker(lineage_id=lineage_id):
            raise b
        if await db.fetchval(f"UPDATE lineages SET status='running' WHERE id=$1 AND status='created' {_ONLY_ONE} RETURNING id", lineage_id) is None:
            return False
        _spawn(lineage_id)
    return True


async def pause(lineage_id: str) -> bool:
    """running → paused, and pause its running generation episode. False (→ 409) if not running."""
    async with _control:
        ln = await db.fetchrow("UPDATE lineages SET status='paused' WHERE id=$1 AND status='running' RETURNING current_generation", lineage_id)
        if ln is None:
            return False
        state(lineage_id).gate.clear()
        ep = await episode_of(lineage_id, ln["current_generation"])
        if ep is not None:
            await bus.emit(ep["id"], ep["current_day"], "lineage.paused", {"lineage_id": lineage_id, "generation": ln["current_generation"]})
            if ep["status"] == "running":
                await runner.pause(ep["id"])
    return True


async def resume(lineage_id: str) -> bool:
    """paused → running. Resumes the generation episode only if the lineage paused it (§ paused_by_lineage);
    an episode paused by MAX_CREDITS_PER_EPISODE or by hand stays paused until POST /episodes/{id}/resume."""
    async with _control:
        if b := await active.blocker(lineage_id=lineage_id):
            raise b
        ln = await db.fetchrow(f"UPDATE lineages SET status='running' WHERE id=$1 AND status='paused' {_ONLY_ONE} RETURNING current_generation", lineage_id)
        if ln is None:
            return False
        _armed[lineage_id] = True  # an explicit human action re-arms the lineage credit guard
        ep = await episode_of(lineage_id, ln["current_generation"])
        if ep is not None:
            await bus.emit(ep["id"], ep["current_day"], "lineage.resumed", {"lineage_id": lineage_id, "generation": ln["current_generation"]})
            if ep["status"] == "paused" and await paused_by_lineage(ep["id"]):
                await _arm_episode(lineage_id, ep["id"])
                await runner.resume(ep["id"])
        st = state(lineage_id)
        st.gate.set()
        if st.task is None or st.task.done():
            _spawn(lineage_id)
    return True


async def paused_by_lineage(episode_id: str) -> bool:
    """Did the lineage (its pause or credit guard, both emitting `lineage.paused` first) or restart recovery
    (`error {where: orchestrator}` first) cause the episode's latest `episode.paused`? Deduced from the events
    between the last `episode.started`/`episode.resumed` and that pause. Never if the episode's own credit
    guard (MAX_CREDITS_PER_EPISODE) tripped in that span too: only POST /episodes/{id}/resume lifts it."""
    return bool(
        await db.fetchval(
            """
            WITH p AS (SELECT MAX(id) AS id FROM events WHERE episode_id=$1 AND type='episode.paused'),
                 r AS (SELECT COALESCE(MAX(e.id), 0) AS id FROM events e, p
                       WHERE e.episode_id=$1 AND e.type IN ('episode.started','episode.resumed') AND e.id < p.id)
            SELECT 1 FROM events e, p, r WHERE e.episode_id=$1 AND e.id > r.id AND e.id < p.id
              AND (e.type='lineage.paused' OR (e.type='error' AND e.payload->>'where'='orchestrator'))
              AND NOT EXISTS (SELECT 1 FROM events g WHERE g.episode_id=$1 AND g.id > r.id AND g.id <= p.id AND g.type='error'
                              AND g.payload->>'where'='credit_guard' AND g.payload->>'message' LIKE 'episode paused%')
            LIMIT 1
            """,
            episode_id,
        )
    )


def _spawn(lineage_id: str) -> None:
    st = state(lineage_id)
    st.gate.set()
    st.task = asyncio.create_task(_loop(lineage_id), name=f"lineage-{lineage_id}")


async def _arm_episode(lineage_id: str, episode_id: str) -> None:
    """Runner-created generations run headless: the lineage's day pause instead of DAY_PAUSE_SEC."""
    cfg = config(await db.fetchrow("SELECT config FROM lineages WHERE id=$1", lineage_id))
    rst = runner.state(episode_id)
    rst.day_pause_sec = cfg.headless.day_pause_sec if cfg.headless else None
    rst.lineage_id = lineage_id


# ---------- the loop ----------


async def _loop(lineage_id: str) -> None:
    st = state(lineage_id)
    try:
        while True:
            await st.gate.wait()
            async with _control:  # atomic with resume(): a pause read here can't swallow a resume
                ln = await db.fetchrow("SELECT * FROM lineages WHERE id=$1", lineage_id)
                if ln["status"] == "paused":
                    st.gate.clear()  # stay alive and wait: resume() sets the gate, never needs to respawn
                    continue
            if ln["status"] != "running":
                return  # finished / failed (or never started)
            cfg, g = config(ln), ln["current_generation"]
            ep = await episode_of(lineage_id, g) if g else None
            if ep is not None and await discard_unannounced(ep):
                eid = await create_generation(lineage_id, g, seed=ep["seed"], days=ep["days"], mode=ep["controller_mode"], attack_plan=ep["attack_plan"])
                await _arm_episode(lineage_id, eid)
                continue
            if ep is not None and ep["status"] != "finished":
                if ep["status"] == "failed":
                    await db.execute("UPDATE lineages SET status='failed', finished_at=now() WHERE id=$1", lineage_id)
                    return
                if ep["status"] == "paused":  # a credit-guard (or manual) episode pause is never auto-resumed
                    await asyncio.sleep(POLL_SEC)
                    continue
                await _run_episode(lineage_id, ep)
                continue  # re-read: finished, failed or paused
            if ep is not None:
                if not await db.fetchval("SELECT 1 FROM events WHERE episode_id=$1 AND type='generation.ended' LIMIT 1", ep["id"]):
                    sc = await score.compute(ep["id"])
                    await bus.emit(ep["id"], ep["days"], "generation.ended", {"lineage_id": lineage_id, "generation": g, "score": sc})
                if not await _reflected(lineage_id, g, cfg):
                    await _reflect_all(lineage_id, g, ep, cfg)
            if not st.gate.is_set():
                continue  # paused during the reflection (e.g. lineage credit guard)
            if g >= cfg.generations:
                await db.execute("UPDATE lineages SET status='finished', finished_at=now() WHERE id=$1 AND status='running'", lineage_id)
                log.info("lineage_finished", lineage_id=lineage_id, generations=g)
                return
            eid = await create_generation(lineage_id, g + 1, seed=ln["base_seed"] + g + 1, days=cfg.days, mode=cfg.controller_mode)
            await _arm_episode(lineage_id, eid)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("lineage_loop_failed", lineage_id=lineage_id)
        await db.execute("UPDATE lineages SET status='failed', finished_at=now() WHERE id=$1", lineage_id)


async def _run_episode(lineage_id: str, ep: Any) -> None:
    """Start the generation's episode (or re-attach after a restart) and wait while its runner task runs."""
    await _arm_episode(lineage_id, ep["id"])
    await announce(ep["id"])
    rst = runner.state(ep["id"])
    if ep["status"] == "created" or rst.task is None or rst.task.done():
        await runner.start(ep["id"])
    while rst.task is not None and not rst.task.done() and rst.pause.is_set():
        await asyncio.wait({rst.task}, timeout=POLL_SEC)
    if not rst.pause.is_set():
        await asyncio.sleep(POLL_SEC)  # runner.pause clears the flag before it writes status 'paused'


async def _reflected(lineage_id: str, g: int, cfg: LineageConfig) -> bool:
    """Generation g's reflection is done once generation g+1 exists (the loop only creates it after)."""
    if cfg.reveal_generations == 0:
        return True
    return bool(await db.fetchval("SELECT 1 FROM episodes WHERE lineage_id=$1 AND generation=$2", lineage_id, g + 1))


def reflect_demo_later(lineage_id: str, generation: int) -> asyncio.Task:
    """runner._finish hook for every lineage episode: reflect a demo generation in the background (the
    loop reflects its own generations; `reflect_demo` returns at once for those). Reuses a task still
    running for the same generation; a finished one is cheap to re-run (stored reviews, skipped agents)."""
    key = (lineage_id, generation)
    t = _demo_tasks.get(key)
    if t is not None and not t.done():
        return t
    t = asyncio.create_task(reflect_demo(lineage_id, generation), name=f"demo-reflect-{lineage_id}-{generation}")
    _demo_tasks[key] = t
    _background.add(t)
    t.add_done_callback(_reflect_task_done)
    return t


def _reflect_task_done(t: asyncio.Task) -> None:
    _background.discard(t)
    for key in [k for k, v in _demo_tasks.items() if v is t]:
        del _demo_tasks[key]
    if not t.cancelled() and (e := t.exception()) is not None:
        log.error("demo_reflect_task_failed", task=t.get_name(), error=repr(e), exc_info=e)


async def reflect_demo(lineage_id: str, generation: int) -> None:
    """After-action review + /reflect for a finished demo generation (POST /episodes {lineage_id}, run outside
    the loop, so only on a finished or failed lineage). Idempotent like the loop's reflection: stored reviews
    are reused and an agent with a reflect version for it is skipped. Stops at the lineage credit cap."""
    async with _demo_locks.setdefault(lineage_id, asyncio.Lock()):
        ln = await db.fetchrow("SELECT * FROM lineages WHERE id=$1", lineage_id)
        if ln is None or ln["status"] not in ("finished", "failed"):
            return  # the loop owns (and reflects) the generations of a created/running/paused lineage
        ep = await episode_of(lineage_id, generation)
        if ep is None or ep["status"] != "finished":
            return
        try:
            await _reflect_all(lineage_id, generation, ep, config(ln), demo=True)
        except Exception:
            log.exception("demo_reflect_failed", lineage_id=lineage_id, episode_id=ep["id"], generation=generation)


async def _over_cap(lineage_id: str, cfg: LineageConfig) -> bool:
    """The lineage's spend so far, re-counted from events: demo turns are not charged by the runner (only the
    loop's generations are), and the cap stops a demo's reflection, never the demo itself."""
    _credits.pop(lineage_id, None)
    await _seed_credits(lineage_id)
    return runner.credit_guard_tripped(_credits[lineage_id], cfg.max_credits)


async def _reflect_all(lineage_id: str, g: int, ep: Any, cfg: LineageConfig, *, demo: bool = False) -> None:
    if cfg.reveal_generations == 0:
        return
    await review.close(ep["id"])
    for agent in AGENTS:
        if demo and await _over_cap(lineage_id, cfg):
            log.warning("demo_reflect_skipped_credit_cap", lineage_id=lineage_id, episode_id=ep["id"], day=ep["days"], agent=agent)
            return  # nothing to pause (the lineage is over): the remaining agents keep their playbooks
        if not demo:
            await state(lineage_id).gate.wait()
        if (lineage_id, g, agent) in _reflect_done or await db.fetchval(
            "SELECT 1 FROM playbooks WHERE lineage_id=$1 AND agent=$2 AND source='reflect' AND generation=$3", lineage_id, agent, g
        ):
            continue  # answered already (a pause mid-reflection), or wrote its version before a restart
        rv = await review.persist(lineage_id, g, ep, agent, cfg)
        current = await db.fetchrow(
            "SELECT version, parent_version, generation, episode_id, day, source, content, rationale FROM playbooks"
            " WHERE lineage_id=$1 AND agent=$2 ORDER BY version DESC LIMIT 1",
            lineage_id,
            agent,
        )
        body = {"lineage_id": lineage_id, "generation": g, "episode_id": ep["id"], "review": rv, "playbook": db.row_to_dict(current)}
        res = await agents.reflect(agent, body)
        spent = runner.credits_of((res.get("usage") or {}).get("factory_credits"))
        log.info("reflect_done", lineage_id=lineage_id, episode_id=ep["id"], day=ep["days"], agent=agent, ok=bool(res.get("ok")), factory_credits=spent)
        new = res.get("playbook")
        if res.get("ok") and isinstance(new, dict):
            await _write_reflect(lineage_id, agent, g, ep["id"], new, str(res.get("rationale") or ""))
        _reflect_done.add((lineage_id, g, agent))
        await charge_reflect(lineage_id, ep["id"], ep["days"], spent, check=not demo)


_GENERATION_LOCK = "SELECT pg_advisory_xact_lock(hashtext('lineage-generation'), hashtext($1))"


async def _write_reflect(lineage_id: str, agent: str, g: int, episode_id: str, content: dict[str, Any], rationale: str) -> None:
    """Write generation g's reflect version, unless generation g+1 already exists: a demo reflection that
    outlived the next demo's wait would otherwise land mid-episode, unannounced, on top of what that
    generation learned. Same lock as create_generation, so the check and the insert can't interleave."""
    try:
        async with db.pool().acquire() as conn, conn.transaction():
            await conn.execute(_GENERATION_LOCK, lineage_id)
            if await conn.fetchval("SELECT 1 FROM episodes WHERE lineage_id=$1 AND generation=$2", lineage_id, g + 1):
                log.warning("demo_reflect_late_discarded", lineage_id=lineage_id, generation=g, agent=agent, episode_id=episode_id)
                return
            await conn.execute("SELECT pg_advisory_xact_lock(hashtext('playbooks'), hashtext($1 || '/' || $2))", lineage_id, agent)
            latest = await conn.fetchval("SELECT MAX(version) FROM playbooks WHERE lineage_id=$1 AND agent=$2", lineage_id, agent)
            await conn.execute(
                "INSERT INTO playbooks (lineage_id, agent, version, parent_version, generation, episode_id, source, content, rationale)"
                " VALUES ($1,$2,$3,$4,$5,$6,'reflect',$7,$8)",
                lineage_id,
                agent,
                (latest or 0) + 1,
                latest or 0,
                g,
                episode_id,
                content,
                rationale,
            )
    except asyncpg.CheckViolationError:
        log.warning("reflect_playbook_too_large", lineage_id=lineage_id, agent=agent, generation=g)  # the playbook is kept


# ---------- lineage credit guard ----------


async def _seed_credits(lineage_id: str) -> None:
    if lineage_id in _credits:
        return
    total = await db.fetchval(
        "SELECT COALESCE(SUM((ev.payload->>'factory_credits')::float8), 0) FROM events ev JOIN episodes e ON e.id=ev.episode_id "
        "WHERE e.lineage_id=$1 AND ev.type='turn.ended' AND jsonb_typeof(ev.payload->'factory_credits')='number'",
        lineage_id,
    )
    _credits[lineage_id] = float(total or 0) + _reflect_spent.get(lineage_id, 0.0)


async def charge_turn(lineage_id: str, episode_id: str, day: int, spent: float) -> None:
    """Runner hook after every turn of a generation it runs (its turn.ended is already emitted)."""
    if lineage_id not in _credits:
        await _seed_credits(lineage_id)  # the seed sum already includes this turn
    else:
        _credits[lineage_id] += spent
    await _check(lineage_id, episode_id, day, spent)


async def charge_reflect(lineage_id: str, episode_id: str, day: int, spent: float, *, check: bool = True) -> None:
    _reflect_spent[lineage_id] = _reflect_spent.get(lineage_id, 0.0) + spent
    if lineage_id not in _credits:
        await _seed_credits(lineage_id)
    else:
        _credits[lineage_id] += spent
    if check:  # a demo's reflection stops at the cap itself (_reflect_all): no lineage to pause
        await _check(lineage_id, episode_id, day, spent)


async def _check(lineage_id: str, episode_id: str, day: int, spent: float) -> None:
    limit = config(await db.fetchrow("SELECT config FROM lineages WHERE id=$1", lineage_id)).max_credits
    total = _credits[lineage_id]
    if not (_armed.get(lineage_id, True) and spent > 0 and runner.credit_guard_tripped(total, limit)):
        return
    _armed[lineage_id] = False
    log.warning("lineage_credit_guard_tripped", lineage_id=lineage_id, episode_id=episode_id, day=day, agent="battlefield", credits=total, limit=limit)
    await bus.emit(episode_id, day, "error", {"where": "credit_guard", "message": f"lineage paused at {total:g} credits (limit {limit:g})"})
    await pause(lineage_id)
