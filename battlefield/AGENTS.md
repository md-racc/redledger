# battlefield/ — maintenance guide (original author: Ad)

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
| `seed/company.py` | `COMPANY` (Meridian Components, an electronics components distributor) and its themed seed generator: vendor names and line items by kind (Dev M tunes via PR) |
| `mock_agents/server.py` | stub red/green/blue; one app, `AGENT_NAME` selects |
| `fixtures/episodes/*.jsonl` | recorded episodes; `sample-enforce-4d.jsonl` came from the scaffold smoke run |
| `db/schema.sql` | build-time copy of `contracts/schema.sql` (gitignored) |

## Rules specific to this directory

- Schema changes go to `contracts/schema.sql` + CHANGELOG, never to `db/`. Schema is applied
  with `CREATE TABLE IF NOT EXISTS` on startup; a column change means `make db-reset` for
  everyone, so announce it.
- Every mutating route: `audit.record(...)` and `audit.mutation(...)`. No exceptions.
- Every ledger response to an `X-Agent` caller goes through `row_to_dict(..., hide=c.hide)`. If you
  add a column that reveals provenance, add it to `HIDDEN_COLUMNS`.
- New gated route → add its action to `GATED_ACTIONS` in `agentkit/models.py` (that's a
  contracts change) and to `contracts/agent-service.md`.
- New event type → `contracts/events.md`, `agentkit/models.py::EventType`, and the frontend
  `CARD_TYPES` in `api/frontend.py` if it should make a card.
- `/api/fe` endpoints are read-only SQL. Keep authentication and provenance filtering intact.

## Extension points you host (docs/ARCHITECTURE.md (Routes and extensions))

`battlefield/extensions/` is loaded by `extensions.mount_all` at startup; `contracts/ext/*/*.sql`
by `db.apply_schema` after the core. Core extension routes live in `app/api/extension_points.py`
(`/state`, `/inputs`, `/fe/query`). The orchestrator drains `inputs` into `options.inputs` per
turn. Keep extension compatibility stable.

## Lineages you run (docs/ARCHITECTURE.md (Evolution))

- `app/orchestrator/lineage.py` (generation loop, start/pause/resume under one lock + conditional
  status updates, restart recovery, demo reflection), `app/evolution/{debrief,review,report,export}.py`,
  playbook routes in `app/api/playbooks.py`.
- Information policy (AGENTS.md invariant 4): daily debriefs = resolved red attacks only; legit
  items only in after-action reviews; every disclosure stored in `debriefs`; revealed attacks are
  scored as of `revealed_day`. Any change here needs a contracts PR and independent review.
- Headless generations: escalations auto-block after the lineage's `headless.escalation_timeout_sec`
  (gatekeeper infers headless from the lineage being running or paused; demos need a finished lineage).
- Known gap: `/reflect` credits not persisted across restarts (`_reflect_spent` is in-memory).
  Per-agent tokens are live (#108–#111): each `X-Agent` must present its own
  `AGENT_TOKEN_<AGENT>`; the shared `AGENT_TOKEN` is only the fallback, with a `token_separation`
  startup warning (`app/config.py`).

## Runtime constraints

- Run battlefield with one uvicorn worker: active-turn tracking and escalation waiters are
  process-local. On restart, interrupted episodes pause and orphaned escalations block.
- Preserve idempotent day recovery and exactly-once escalation resolution. Red and blue turns
  that already started must not be re-run after restart.
- Keep scoring attribution, false positives and provenance filtering covered by tests.
- Replay episodes have event history, not ledger rows; mutation routes must reject them.
- `/reflect` credit tracking is process-local; do not claim restart-persistent reflection budgets.

## Local

```
make mock-agents            # or run postgres + `uvicorn app.main:app --reload` + 3× `AGENT_NAME=x uvicorn mock_agents.server:app --port 800X`
make episode MODE=enforce SEED=42 DAYS=4
```
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

## Maintenance validation

Follow root `AGENTS.md` and `docs/CONTRIBUTING.md`; historical team prefixes are no longer path restrictions.
Run root `make lint test-battlefield` for changes here; keep `DRY_RUN=true` keyless.
Use `agentkit.LedgerClient` for agent ledger access and preserve the root information boundaries.
