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
- Replays broadcast via `bus._broadcast` under a virtual episode id and are not persisted.
- No pagination on `/api/events` beyond `limit`; fine for 10-day episodes.
- Day pacing for demos is `DAY_PAUSE_SEC`; there is no per-turn pacing.

## Local

```
make mock-agents            # or run postgres + `uvicorn app.main:app --reload` + 3× `AGENT_NAME=x uvicorn mock_agents.server:app --port 800X`
make episode MODE=enforce SEED=42 DAYS=4
```
The scaffold was smoke-tested this way: 4-day enforce episode, mock agents, 4 attacks launched,
3 caught, $23.3k blocked, $0 extracted, 0 legit blocks.
