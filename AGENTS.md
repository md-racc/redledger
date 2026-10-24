# AGENTS.md — working agreement for humans and coding agents

Read `README.md` first, then `GIT.md`. This file tells you how to work in this repo without
breaking the other three people. It applies equally to a teammate and to Claude Code / Droid /
Cursor operating on their behalf. Each service directory has its own `AGENTS.md` for the dev who
owns it; read that one too before editing there.

Devs: **Ad** = backend (battlefield, agentkit, contracts, deploy; repo owner). **Al** = red.
**M** = green + blue. **R** = frontend + presentation.

## 1. What this project is, in two sentences

Red Ledger is an adversarial sandbox where a red-team agent commits financial fraud against a
synthetic company, a finance-ops agent does legitimate work, and a controller agent gates every
money-moving action and audits the books. Five containers (`battlefield`, `red`, `green`,
`blue`, `frontend`) plus Postgres; every agent talks only to `battlefield`'s Ledger API.

## 2. Ownership and boundaries

| Directory         | Owner | Others may edit?                                         |
|-------------------|-------|----------------------------------------------------------|
| `battlefield/`    | Ad    | PR with Ad as reviewer (R may add `/api/fe` reads; M may tune seed/traffic) |
| `agentkit/`       | Ad    | PR + one agent-team reviewer                             |
| `contracts/`      | Ad    | `contracts/` PR + **all** affected owners; CHANGELOG entry required |
| `red/`            | Al    | no                                                       |
| `green/`          | M     | no                                                       |
| `blue/`           | M     | no                                                       |
| `frontend/`       | R     | no                                                       |
| compose, Makefile, `.env.example`, `.github/` | Ad | PR                          |
| `DEVLOG.md`       | all   | append-only, one line per PR (see `GIT.md` §6)           |

A coding agent working in one directory must not modify files in another owner's directory. If
the task genuinely requires it, stop and say so; the human decides.

Branching, commits, PRs, and the coding-agent git rules are in `GIT.md`. Short version: branch
`<area>/<topic>`, stay in your area (CI enforces it), small PRs, squash-merge, never force-push,
one `DEVLOG.md` line per PR.

## 3. Non-negotiable invariants

1. **Agents never touch Postgres.** Only `battlefield` has `DATABASE_URL`. Red, green, and blue
   read and write the books exclusively through `agentkit.LedgerClient` → Ledger API over HTTP.
2. **Agents never call each other.** Red/green/blue do not know each other's URLs. The only
   exception is green's Droid permission handler mirroring `POST blue/gate`, which uses
   `BLUE_URL` and the same idempotency key the ledger call uses.
3. **The Ledger API is the enforcement point.** Blue's verdict is consulted inside battlefield on
   green's gated routes. Anything else (green's permission handler, UI hints) is a mirror, never a
   second source of truth.
4. **`origin` is secret.** `origin='red'` rows are ground truth for scoring. Battlefield strips
   `origin` from every response to any `X-Agent`. Never leak it through another field, an error
   message, or an event payload visible to agents.
5. **Every agent action is logged.** Every Ledger API call writes `audit_log`. Every tool call an
   agent makes also emits `agent.tool_call` / `agent.tool_result` events via `EventEmitter`.
   Don't add a code path that mutates state without both.
6. **Contracts beat code.** If code disagrees with `contracts/`, the code is wrong. If you need
   the contract to change, change the contract first (PR, CHANGELOG entry, ping affected owners),
   then the code.
7. **Idempotency keys are the Droid `tool_use_id`** when the call originates from a Droid tool,
   else a UUID4. Blue caches `/gate` verdicts by key for 120 s. Never reuse a key across different
   actions.
8. **Everything must run under `DRY_RUN=true` with no Factory or LLM keys.** Agents return canned
   turns; blue's gate runs rules only. Frontend must run with `NEXT_PUBLIC_MOCK=true` and no
   backend. Don't break these paths; they are how four of five people develop.
9. **No secrets in the repo, in images, or in `NEXT_PUBLIC_*`.** Secrets live in your local
   `.env` (gitignored) or in the GitHub `production` environment, which the deploy job renders
   into the VM's `.env` (`deploy/ENVIRONMENT.md`). Never bake one into an image or a build arg,
   never put one in a `NEXT_PUBLIC_*` var (those ship to the browser). `.env.example` has every
   variable with an empty or dummy value. Each dev uses their own `FACTORY_API_KEY` locally;
   the prod key exists only in `production`. Keys arrive via the shared vault, not Slack.
10. **Timeouts everywhere.** Every HTTP call has a timeout. Every Droid `stream()` has `timeout=`.
    A hung agent must fail a turn, not the episode.
11. **Agents read the books, never the scoreboard or each other.** Battlefield enforces part of
    this (below); the rest is a rule every agent team and reviewer holds to:
    - No agent code or Droid tool calls `GET /api/events` or `WS /api/ws`. That stream carries
      `attack.launched`/`attack.outcome`, red-tagged `ledger.mutation`s, and every agent's
      narration and gate reasoning. Agents *emit* events; only the frontend/operator reads them.
    - No agent calls `/api/fe/*`, `/api/attacks/all`, `/api/episodes/*/score`, or any route
      without `X-Agent`. A bearer call without `X-Agent` is an operator call and sees `origin`.
      Go through `agentkit.LedgerClient` only; no raw `httpx` to battlefield.
    - **Blue** reads `GET /api/audit_log` only with `agent=green` (or `agent=blue`). Red's rows
      list exactly which vendors/invoices/expenses are fraud; reading them is reading ground
      truth. Never give the blue Droid session an unfiltered audit-log tool.
    - **Red** learns only from the books and its own calls' results. It does not read blue's
      reports (`/api/reports`), flags, verdict reasons, or green's narration.
    - **Green** reads `/api/flags` (by contract) and nothing of red's or blue's internals.
    - No system prompt mentions `origin`, `attack_id`, scoring, or the other agents' existence
      beyond what the role implies.
    Enforced in code: `GET /api/events`, `/api/ws`, `/api/fe/*` and every control-plane route
    reject `AGENT_TOKEN` (invariant 12), so an agent can't reach them at all. Not enforced:
    blue's `audit_log` filter, red not reading reports/flags; a reviewer checks every agent's
    tool list for those. Filtering `audit_log` server-side is a candidate contracts change.
12. **Two tokens, chosen by `X-Agent`.** A request with `X-Agent` presents `AGENT_TOKEN`; a
    request without it presents `OPERATOR_TOKEN`. The wrong one for the role is a 401, so an
    agent cannot make an operator call and the frontend cannot act as an agent. Agents hold only
    `AGENT_TOKEN` (via `agentkit.AgentSettings`; `INTERNAL_TOKEN` is a legacy fallback). The
    browser holds neither: REST goes through the frontend server's `/api/bf/*` proxy, and the
    WebSocket connects with a 60 s single-use ticket from `/api/bf/ws-ticket`. Never pass
    `?token=` from browser code. `GET /api/events` already rejects agents (403).

## 4. Tech conventions

**Python services (`battlefield`, `red`, `green`, `blue`, `agentkit`)**
- Python 3.11. `uv` for deps (`uv sync --extra dev`), `ruff` (root `ruff.toml`) for lint+format, `pytest`. Type hints on
  everything public; pydantic v2 models for anything that crosses a process boundary.
- FastAPI + `httpx.AsyncClient`. Async all the way down; the Droid SDK is asyncio-only.
- Structured logging (`structlog`) to stdout, JSON in containers. Include `episode_id`, `day`,
  `agent` on every log line.
- Config via environment only (`pydantic-settings`). No config files.
- One `Dockerfile` per service, `python:3.11-slim` base. Agent images additionally install the
  Droid CLI per Factory's install docs and `pip install "droid-sdk[mcp]"`.

**Frontend**
- Next.js 15 app router, TypeScript strict, Tailwind, shadcn/ui. No Redux; a single event
  reducer (`lib/reducer.ts`) derives all UI state from the event stream.
- API types generated from `contracts/ledger-api.yaml` (`npm run gen:api`). Don't hand-write
  them.
- Components are presentational and take derived state; WebSocket and replay both feed the
  same reducer.

**Database**
- Postgres 16. `contracts/schema.sql` is the schema; battlefield applies it at startup with
  `CREATE TABLE IF NOT EXISTS`. A column change = edit `contracts/schema.sql` (contracts PR) and
  everyone runs `make db-reset`. No migration tool this weekend.
- Timescale is an image swap (`timescale/timescaledb:latest-pg16`) and a hypertable on
  `events` and `audit_log`. Optional; don't let it block anything.

## 5. Droid SDK usage rules (red, green, blue audit)

Subclass `agentkit.DroidAgent`. It handles session lifecycle, in-process MCP server creation
from your tool functions, stream→event forwarding, timeouts, and DRY_RUN. You supply: a system
prompt, a list of tool functions (thin wrappers over `LedgerClient`), a model id, an autonomy
level, and optionally a permission handler.

- `system_prompt` is a **string** (replaces Droid's default coding prompt). Never use the
  `append` preset form; the default prompt is about editing code and will confuse the agent.
- `disable_builtin_skills=True` always. `restrict_tools` to your MCP server's tools; verify the
  exact tool IDs with `session.list_tools()` once and hardcode them.
- Red: `Autonomy.HIGH`, permission handler always `PROCEED_ONCE`.
- Green: `Autonomy.OFF` so every tool call raises a permission request; handler calls
  `POST blue/gate` with the ledger idempotency key and returns `CANCEL` on block. Verify on day
  one that MCP tool calls actually trigger permission requests at `OFF`; if they don't, document
  the finding in `contracts/CHANGELOG.md` and rely on ledger-side enforcement alone.
- Never return `PROCEED_ALWAYS*` / `PROCEED_AUTO_RUN*` from any handler. They disable the gate.
- Handlers may be async and may do I/O. They must not start a turn on the same session.
- Pin models via `DROID_MODEL_*`. Don't use `model="auto"` in anything that runs during judging.
- Use `include_partial_messages=True` and forward `ThinkingDelta`/`TextDelta` as
  `agent.thinking` events, `ToolCall`/`ToolResult` as `agent.tool_call`/`agent.tool_result`.
  Don't also forward the complete `AssistantMessage` text; it duplicates the deltas.
- Log `result.usage.factory_credits` per turn at INFO. We need the burn rate.
- Every `stream()` gets `timeout=TURN_TIMEOUT_SEC - 10`.
- Catch handler exceptions and fail closed (block) in green; the SDK turns handler exceptions
  into cancels but you want the reason logged.

## 6. How each team develops locally

```
make mock-agents        # battlefield + postgres + stub agents; use this if you are red/green/blue
# then in your own dir:
uv sync && uv run uvicorn server:app --port 800X --reload
```
Tokens: your `.env` sets `AGENT_TOKEN` and `OPERATOR_TOKEN` to two different local strings
(invariant 12). A service you run on the host needs the same `AGENT_TOKEN` battlefield has
(compose default `change-me-agent`); `make` targets send `OPERATOR_TOKEN`.

Frontend: `cd frontend && NEXT_PUBLIC_MOCK=true npm run dev` until battlefield is stable, then
set the server-side `BATTLEFIELD_URL` and `OPERATOR_TOKEN` (`frontend/.env.example`) to point
the `/api/bf/*` proxy at a battlefield, normally your local `make mock-agents`.

Backend: `make up-dry` runs the real stack with agents in DRY_RUN.

Before pushing: `make test` in your directory and `make lint`. CI runs both per service.

## 7. Definition of done for a PR

- One `DEVLOG.md` line appended.
- Runs under `DRY_RUN=true` / `NEXT_PUBLIC_MOCK=true`.
- Does not change `contracts/` without a CHANGELOG entry and reviewer from each affected owner.
- Emits the events the README says it should.
- Has at least one test touching the new code path (unit for rules/schemes, integration via
  `httpx` against the FastAPI app for routes).
- No new environment variable without an entry in `.env.example` and README §11.

## 8. For coding agents specifically

- Start by reading `README.md` §§0, 1, 5, 6, 7, `GIT.md` §7, the `AGENTS.md` in your directory, and the `contracts/` file relevant to your task.
- State which directory you are working in before editing. Stay there.
- Do not invent endpoints, event types, or table columns. If the contract lacks what you need,
  write the proposed contract change as a diff to `contracts/` and stop for human review.
- Do not stub out the Ledger API with direct DB access "just to test". Use `make mock-agents`
  or the fixtures.
- Do not install new top-level dependencies without noting why in the PR description.
- Prefer small, verifiable steps: one route, one scheme, one component per PR.
- When a Droid SDK behavior is uncertain (permission prompting at a given autonomy, tool ID
  format, whether `comment` on CANCEL reaches the model), write a 10-line script to test it and
  record the answer in `contracts/CHANGELOG.md` under "Findings". Don't guess.
- Never commit `.env`, recorded episodes containing real keys in payloads, or Factory session
  files.

## 9. Glossary

- **Episode** — one simulation run with fixed seed and controller mode.
- **Day / tick** — one orchestrator iteration: inject → red → green → blue audit → score.
- **Gate** — blue's synchronous verdict on a green mutation. `allow | block | escalate`.
- **Shadow mode** — gate evaluated and logged, not enforced.
- **Scheme** — a red attack template (`red/schemes/`).
- **Verdict card** — frontend rendering of a `gate.verdict` event: what it saw, why, what it did.
- **Origin** — hidden provenance column (`sim | red | green | blue`) used for scoring.
- **Fixture** — a recorded episode (`*.jsonl` of events) used for replay and frontend dev.

## 10. If you are an orchestrator spawning subagents (read this first)

Every dev here runs Claude Code Max with heavy subagent fan-out. The first agent to read this
file is probably planning work for others, not writing code. These rules are for you.

**Plan by file ownership, not by feature.** Split the task so that no two subagents ever edit
the same file. Give each subagent an explicit list of files it may create or modify. Two
subagents editing `agent.py` concurrently is the single most expensive mistake available.

**One worktree per implementer.** Spawn implementers with `isolation: "worktree"` (or
`git worktree add ../<area>-<topic> -b <area>/<topic> origin/main`). Each worktree is one
branch. Never let two subagents share a working tree. Name branches `<area>/<topic>-<n>` if a
feature needs several implementers; you merge them into `<area>/<topic>` yourself before the PR.

**You own git. Subagents commit on their own branch and stop.** Subagents do not push, do not
open PRs, do not merge, do not touch `main`, do not rebase anything shared. You review the diff
of each worktree (`git diff origin/main...`) before pushing a branch. `.claude/settings.json`
denies the destructive commands repo-wide; do not instruct a subagent to work around a denial.

**Feed context, don't make them hunt.** You read `AGENTS.md`, `GIT.md`, the directory's
`AGENTS.md`, and the relevant `contracts/` file once. Each subagent prompt then contains: the
paste-ready block from the directory's `AGENTS.md`, its exact file list, the contract excerpt it
needs (the route signatures or event payloads, not the whole file), and the DRY_RUN requirement.
A subagent that spends 40k tokens rediscovering the repo is your planning failure.

**Verification is a separate subagent.** After implementers finish, spawn one reviewer per
worktree that has not seen the implementation: it runs `make lint test-<area>` (and
`make mock-agents` + an episode for battlefield-touching work), reads the diff against the
directory's `AGENTS.md` boundaries and the contract, checks any agent tool list against §3
invariant 11 (no peeking), and reports pass/fail with specifics.
Implementers grading their own work is not verification.

**Boundaries propagate.** A subagent you spawn from a `red/` task inherits the `red/`
boundary: `red/**`, `battlefield/extensions/red_*.py`, `contracts/ext/red/**`, `DEVLOG.md`.
If a subagent reports it needs a change elsewhere, that is a contracts change: collect the
proposed diff, stop, hand it to the human. Do not spawn a subagent into another team's
directory "just to fix one thing".

**Fan-out limits.** Up to four implementers in parallel per area is fine for pure code. For
anything touching `contracts/ext/<area>/*.sql` or `battlefield/extensions/`, one at a time:
schema files are applied in filename order on startup and two subagents inventing `01_` names
collide. Do not run more than one `make mock-agents` stack per machine; it binds ports
5432/8000-8003.

**Shared infrastructure is read-only to subagents.** No subagent deploys, runs `make up` against
the staging box, rotates a key, or edits `.env`. Local `make mock-agents` and `DRY_RUN=true` are
the only environments a subagent runs against. The VM is Ad's.

**Reporting.** Subagents return a short summary: files changed, tests run and results, open
questions, anything that smelled like a contract gap. Not file dumps, not transcripts. You
append exactly one `DEVLOG.md` line per PR, written from those summaries, naming the dev you
work for (Ad / Al / M / R), not the agent.

**Findings.** If any subagent empirically settles one of the open questions in
`contracts/CHANGELOG.md` (Droid autonomy behavior, tool ID format, CLI install line), record
the answer there under Findings in the same PR. That is a contracts-adjacent write every area
is allowed to make: one line, dated, with the command that proved it.

**When to stop and ask the human.** A contracts change is needed; a test you did not write
fails on `main`; a subagent wants to delete or skip a test; two subagents disagree about an
interface; anything would touch another team's directory; you are about to spawn a fifth
parallel implementer; the task would take more than ~2 hours of wall clock. Ask, don't guess.

### Subagent prompt skeleton

```
Role: implementer for <area>/, branch <area>/<topic>-<n>, worktree <path>.
Owner dev: <Ad|Al|M|R>. You report to the orchestrator, not to git.
Files you may create/modify: <explicit list>. Nothing else. If you need another file, stop and say so.
Contract excerpt you depend on: <paste the exact routes / payloads / schema lines>.
Requirement: must work under DRY_RUN=true (agents) or NEXT_PUBLIC_MOCK=true (frontend).
Done means: `make lint test-<area>` passes in your worktree; commit on your branch with message
`<area>: <imperative summary>`; do NOT push; reply with: files changed, tests run, open questions.
Never: force-push, reset --hard, delete tests, edit DEVLOG.md, edit .env, touch another directory.
Task: <one concrete deliverable>
```
