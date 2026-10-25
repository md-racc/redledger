# battlefield/ — working guide for Dev Ad and any coding agent in this directory

This is the center spoke: Ledger API, gatekeeper, orchestrator, event bus, scoring, mock agents,
and the frontend read API. Everyone else builds against it. Changes here are the ones most
likely to break someone else's day, so the bar is: contracts first, tests second, code third.

## Layout

| Path | What |
|---|---|
| `app/main.py` | FastAPI app; routers mounted under `/api` |
| `app/config.py` | env-only settings |
| `app/db.py` | asyncpg pool, schema apply on startup, `row_to_dict(hide=...)`, `HIDDEN_COLUMNS` |
| `app/auth.py` | bearer + `Caller` (X-Agent/X-Episode/X-Day/X-Tool-Use-Id) + `allow(...)` per-route permissions |
| `app/api/reads.py` | read routes for all agents; hides provenance for agents |
| `app/api/red_writes.py` | red's submission surface; tags origin='red', links `attack_id` |
| `app/api/green_writes.py` | gated AP routes; context assembly for blue; 403 on block |
| `app/api/blue_writes.py` | flags, freeze, reports |
| `app/api/events_api.py` | GET/POST /events, WS /ws |
| `app/api/control.py` | episodes, controller toggle, forced attacks, escalations, replays, health |
| `app/api/frontend.py` | `/api/fe/*` read-only derived views for Dev R |
| `app/gate/gatekeeper.py` | the enforcement point; modes; escalation wait |
| `app/orchestrator/runner.py` | the clock; day loop; pause/step |
| `app/orchestrator/legit_traffic.py` | per-day legit business (Dev M tunes via PR) |
| `app/orchestrator/agents.py` | HTTP to red/green/blue |
| `app/scoring/score.py` | attack outcome resolution + Score |
| `seed/company.py` | Coastal Supply Co. generator (Dev M tunes via PR) |
| `mock_agents/server.py` | stub red/green/blue; one app, `AGENT_NAME` selects |
| `fixtures/episodes/*.jsonl` | recorded episodes; `sample-enforce-4d.jsonl` came from the scaffold smoke run |
| `db/schema.sql` | build-time copy of `contracts/schema.sql` (gitignored) |

## Rules specific to this directory

- Schema changes go to `contracts/schema.sql` + CHANGELOG, never to `db/`. Schema is applied
  with `CREATE TABLE IF NOT EXISTS` on startup; a column change means `make db-reset` for
  everyone, so announce it.
- Every mutating route: `audit.record(...)` and `audit.mutation(...)`. No exceptions.
- Every response to an `X-Agent` caller goes through `row_to_dict(..., hide=c.hide)`. If you
  add a column that reveals provenance, add it to `HIDDEN_COLUMNS`.
- New gated route → add its action to `GATED_ACTIONS` in `agentkit/models.py` (that's a
  contracts change) and to `contracts/agent-service.md`.
- New event type → `contracts/events.md`, `agentkit/models.py::EventType`, and the frontend
  `CARD_TYPES` in `api/frontend.py` if it should make a card.
- `/api/fe` endpoints are read-only SQL. Dev R may PR new ones here with Ad as reviewer.

## Extension points you host (README §16)

`battlefield/extensions/` is loaded by `extensions.mount_all` at startup; `contracts/ext/*/*.sql`
by `db.apply_schema` after the core. Core extension routes live in `app/api/extension_points.py`
(`/state`, `/inputs`, `/fe/query`). The orchestrator drains `inputs` into `options.inputs` per
turn. Keep these stable: they are what lets the other three work without you.

## Lineages you run (README §15)

- `app/orchestrator/lineage.py` (generation loop, start/pause/resume under one lock + conditional
  status updates, restart recovery, demo reflection), `app/evolution/{debrief,review,report,export}.py`,
  playbook routes in `app/api/playbooks.py`.
- Information policy (AGENTS.md invariant 4): daily debriefs = resolved red attacks only; legit
  items only in after-action reviews; every disclosure stored in `debriefs`; revealed attacks are
  scored as of `revealed_day`. Any change here needs a contracts PR and a verifier.
- Headless generations: escalations auto-block after the lineage's `headless.escalation_timeout_sec`
  (gatekeeper infers headless from the lineage being running or paused; demos need a finished lineage).
- Known gap: `/reflect` credits not persisted across restarts (`_reflect_spent` is in-memory).
  Per-agent tokens are live (#108–#111): each `X-Agent` must present its own
  `AGENT_TOKEN_<AGENT>`; the shared `AGENT_TOKEN` is only the fallback, with a `token_separation`
  startup warning (`app/config.py`).

## Paste this to your coding agent as its first message

```
You are working in the Red Ledger repo, directory `battlefield/` (and `agentkit/`, `contracts/`),
as Dev Ad's coding agent. Before any edit: read `battlefield/AGENTS.md`, `AGENTS.md`, `GIT.md`,
`README.md`, and all of `contracts/`. Confirm `git branch --show-current` starts with
`battlefield/` or `contracts/`. A contracts change requires a `contracts/CHANGELOG.md` entry in
the same PR. Never write to `red/ green/ blue/ frontend/`. Never force-push or merge. Run
`make lint test-agentkit test-battlefield` before each push; if postgres is available, also run
a 4-day `make mock-agents` + `make episode` smoke and paste the score into the PR.
Goal for this session: <fill in>
```

## Known gaps left for Ad (from the scaffold smoke run)

- `bank_swap` scoring (done): red `vendor_changes` carry `attack_id` (set by `POST
  /vendor_changes` to red's latest attack that day, hidden from agents like invoices/expenses),
  and `score._attribute` credits each change to that attack. An approved red `bank_account`
  change is live from its `resolved_day` until the vendor's next approved `bank_account` change.
  While live, non-red payments to `new_value` are extracted, and the vendor's non-red invoices
  that get a block/escalate verdict or end blocked/rejected count as caught at pay time. Those
  invoices count for detection and toward `dollars_blocked`, mark the change blocked (partial if
  money already left), and are excluded from the false-positive numbers; diverted payments are
  excluded from `legit_processed`. Blocked/rejected change or frozen vendor = blocked;
  change-only attacks stopped at the change get their target credited to `dollars_blocked`.
  A red invoice of an attack with an attributed red `bank_account` change, on a non-red vendor,
  paid to an account other than an approved change's `new_value` (the swap was not in effect, so
  the money went to the real vendor's account on file) is not extracted (`score._misdirected`):
  a blocked swap whose decoy invoice got paid resolves `blocked`, not `partial`.
  Detection only counts verdicts/flags on or after `day_launched`. Remaining limits: rows with
  NULL `attack_id` (legacy rows from before the column, or a change red made before declaring
  any attack that day) still use the old same-day heuristic (attacks launched on its
  `requested_day`, preferring ones with no invoice/expense rows; a NULL change on a day with no
  attack scores no dollars but still clears false positives); any block of that vendor's
  invoice while a swap is live is credited, whatever the rule that fired.
- `red_writes._current_attack` (fixed): links new rows to today's attack with the latest
  `attacks.created_at` (`id` only breaks ties), so several attacks in one red turn link
  correctly as long as red declares each attack before submitting its rows. Rows submitted
  before any declaration that day stay unlinked.
- `legit_traffic` false-positive bait (done): one legit `bank_account` change per 3 days
  (established vendor, old_value = current account, ~60% while it has open invoices) and one
  legit new vendor per 4 days (PO on its first day, first invoice > $1k under it 1-2 days
  later), on seeded days, counted in `legit_injected.vendor_changes` / `.new_vendors`. Dev M
  tunes the constants at the top of `legit_traffic.py`. Not yet: legit address/name changes.
- `GET /audit_log` for agents (fixed): only red's legwork writes audit rows for sim-shaped
  entities, so red's rows (entity ids in `result`, the scheme story in `attacks.declare`) were
  provenance. `list_audit` now gives any X-Agent caller only `agent IN ('green','blue')` rows and
  never an `attacks.*` action; `agent=red` returns `[]`, not 403. Operator view is unfiltered.
  A new agent that writes audit rows stays hidden from agents until added to that allowlist.
- False positives (done, Ad's call): each legit (sim) item is charged once, by its worst outcome.
  Blocked (ended blocked, any block verdict, or an escalation that ended block/timeout) costs
  `amount × FP_PENALTY_RATE + FP_FLAT_PENALTY`; escalated but never blocked (approved or still open)
  costs `FP_FLAT_PENALTY`. Shadow verdicts score as "would-have" costs the same way, so
  off/shadow/enforce compare cleanly, and `legit_blocked` in shadow counts would-have blocks. Live
  red-swap pay-time stops stay excluded. **Docs PR needed:** README §4's `false_positive_cost` line
  still says `(legit blocks + legit escalations) × FP_FLAT_PENALTY`.
- Escalations (done): close exactly once (resolver, timeout or orphan sweep); a same-key replay
  joins the open escalation or reuses its decision; on startup open escalations are timed out
  (their held request died with the old process) and `running` episodes are paused with an
  `error {where:"orchestrator"}`, never auto-resumed; `replay_*` episodes still `running` are marked
  `failed` with `error {where:"replay"}`. Resuming such an episode re-runs its current
  day, but `run_day` is idempotent per day: if the episode already has that day's `day.started`, it
  skips legit traffic and the event (logs `day_resumed`) and every agent turn that already has a
  `turn.ended` that day (logs `turn_skipped_resumed`); red and blue count as done once their turn
  *started* (red also if an attack of that day exists), since their writes aren't idempotent; only
  green (gated, compare-and-set) re-runs an interrupted turn. `episode.started` is emitted once.
- Active-turn guard (`app/turns.py`): the runner marks (episode, agent, day) active only while it
  waits on that agent's `/turn` or blue's `/audit`; `auth.caller` answers any other X-Agent write
  (POST/PATCH/PUT/DELETE, incl. `/events`, `/state`, `/inputs`) with an audited 409
  `{"error":"no active turn for this agent"}`. Reads stay open; operator calls and the
  orchestrator's own DB writes don't pass through it. A turn battlefield stopped waiting on, or one
  orphaned by a restart, can't write; a gated write admitted during the turn (an escalation hold)
  still completes. **In-process**, like the escalation waiters: battlefield must run as one
  uvicorn worker. Tests disable it by default (`conftest._no_turn_guard`; `turn_guard` re-enables).
  Gate checks are single-flight per (episode, X-Tool-Use-Id). Mock blue
  escalates on demand with `MOCK_BLUE_ESCALATE`; drive it with `scripts/escalation_smoke.py`. **Docs PR needed:** README §11
  should list `MOCK_BLUE_ESCALATE` (mock only), and events.md could list `where: orchestrator`.
- Replays (done): `POST /replays/{id}/play` creates a real `episodes` row `replay_<fixture>_<8hex>`
  (status `running`→`finished`/`failed`; seed/mode/days from the fixture's `episode.started`) and
  re-emits every fixture event through `bus.emit`, paced by original `ts` / speed (gap cap 3 s), so
  `GET /events`, WS `after_id` catch-up and tickets work; concurrent plays get distinct ids. A
  caller-supplied `episode_id` must match `replay_[A-Za-z0-9_-]{1,57}` and not exist (else 422/409).
  Replays have no ledger rows, the runner/controller routes 409 on them, and any X-Agent request
  with a `replay_*` X-Episode is 403. Fixtures are validated before the row is created (422 names
  the line; symlinks resolving outside FIXTURES_DIR 404); shutdown cancels replays as `failed`. `/fe` for a replay:
  snapshot score, timeline (cash_in/out null), attacks, compare, feed, thinking, activity `turns`
  come from events; vendors, verdicts*, ap_aging, leaderboard, search, reports, escalations, entity
  trails and activity `activity` are table-derived and empty (404 for trails).
- No pagination on `/api/events` beyond `limit`; fine for 10-day episodes.
- Day pacing for demos is `DAY_PAUSE_SEC`; there is no per-turn pacing.

## Local

```
make mock-agents            # or run postgres + `uvicorn app.main:app --reload` + 3× `AGENT_NAME=x uvicorn mock_agents.server:app --port 800X`
make episode MODE=enforce SEED=42 DAYS=4
```
The scaffold was smoke-tested this way: 4-day enforce episode, mock agents, 4 attacks launched,
3 caught, $23.3k blocked, $0 extracted, 0 legit blocks.

### Without Docker (`make local-stack`)

For a machine with no Docker or system Postgres. It runs Postgres 16 via `pgserver` (unix socket, data
in `.local-stack/pgdata`), battlefield on :8000 and red/green/blue on :8001–8003 as plain processes.
`.local-stack/` ignores itself and holds the per-data-dir tokens (`env`, mode 600, never printed),
logs (`logs/<name>.log`, each run starts with a `=== local-stack start` line) and pid files.
Requirements: `python3`, `uv` (it fetches `pgserver` via `uvx`) and `curl`. It runs on Linux and on
stock macOS: bash 3.2 or newer, no `setsid` or GNU-only tools needed (each service gets its own process
group through a small `python3` `os.setsid()` shim).

```
make local-stack                 # all three agents mocked (AGENTS=mock)
make local-stack BLUE=real       # real keyless blue (DRY_RUN=true) on top of mock red/green
make local-stack AGENTS=real     # every agent from its own directory (red/, green/, blue/)
make local-stack-status          # health of each process + postgres
make episode MODE=enforce SEED=42 DAYS=2     # the usual curl targets pick up the stack's token
make evolve GENS=2 DAYS=2 && make evolution-report LN=<id>
make local-stack-stop            # stop everything; RESET=1 CONFIRM=yes also wipes the DB and tokens
```

- Real agents run `DRY_RUN=true` unless you export `DRY_RUN=false` or `DRY_RUN_<AGENT>=false`.
  `FACTORY_API_KEY`, `DROID_MODEL_<AGENT>`, `DROID_REASONING_<AGENT>` and `CRS_*` come from your own
  shell environment; the script never reads or writes any `.env`. A live session spends credits.
- It refuses to start if :8000–8003 are in use (e.g. a docker stack), and never touches other processes.
- While the stack is up, `make episode`/`evolve`/`score`/... use its operator token automatically
  (`.local-stack/env` wins over `.env`); after `local-stack-stop` they fall back to `.env` / `change-me`.
