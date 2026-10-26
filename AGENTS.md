# AGENTS.md — maintenance guide

Red Ledger is a completed Cal Hacks 13.0 project, preserved with screenshots, recordings and
local setup. Hosted infrastructure is retired separately from the source; do not assume a live
service exists or redeploy it as part of routine maintenance.

Read `README.md`, then `GIT.md`, `docs/ARCHITECTURE.md`, the service's `AGENTS.md`, and the
relevant `contracts/` files before editing. Contracts remain authoritative.

## 1. Project and team

Red Ledger is an adversarial financial sandbox: red attempts fraud, green performs legitimate
AP work, and blue gates money-moving actions and audits the books. Only battlefield accesses
Postgres; all agents use its Ledger API.

Original contributors: **Ad** — battlefield, agentkit, contracts, deployment and integration;
**Al** — red; **M** — green and blue; **R** — frontend and presentation. These are author credits
and useful context, not exclusive maintenance boundaries. The repository maintainer handles
cross-area maintenance through reviewed PRs.

## 2. Scope and review

- State the files or directories you intend to change before editing. Keep changes focused.
- Work on a topic branch and preserve other people's uncommitted work. See `GIT.md`.
- Use PRs with passing checks and independent review for security, contracts, core runtime,
  deployment and changes spanning services. Merge only when the maintainer authorizes it.
- Change a contract and its CHANGELOG before dependent implementation; do not invent routes,
  event types or columns. Record experimentally verified SDK findings in the CHANGELOG.
- Keep historical `DEVLOG.md`, existing fragments, recordings and evidence intact. New devlog
  fragments are optional; PR descriptions carry current change and validation notes.

## 3. Non-negotiable invariants

1. **Agents never touch Postgres.** Only `battlefield` has `DATABASE_URL`. Red, green, and blue
   read and write the books exclusively through `agentkit.LedgerClient` → Ledger API over HTTP.
2. **Agents never call each other.** Red/green/blue do not know each other's URLs. No
   exceptions: blue `/gate` is called only by battlefield. Green learns the verdict before acting by
   preparing the action (`POST /api/preparations`, keyed by its tool-use id) and acting on the
   returned `effective` (design D1, contracts #80).
3. **The Ledger API is the enforcement point.** Blue's verdict is consulted inside battlefield, at
   preparation and on green's gated routes, which consume the matching preparation. Anything else
   (green's permission handler, UI hints) only reflects that decision, never a second source of
   truth.
4. **`origin` is secret during play.** `origin='red'` rows are ground truth for scoring. Battlefield
   strips `origin` from every response to any `X-Agent`. Never leak it through another field, an
   error message, or an event payload visible to agents. The only exception is battlefield's
   debrief and after-action review in a lineage episode (`contracts/agent-service.md`, Lineages):
   daily debriefs may reveal **resolved** red attacks within the lineage's reveal window, legit
   items appear only in the after-action review once the episode has ended, and every disclosure
   is stored in `debriefs`. Plain episodes reveal nothing. No agent ever sees another agent's
   playbook.
5. **Every agent action is logged.** Every Ledger API call writes `audit_log`. Every tool call an
   agent makes also emits `agent.tool_call` / `agent.tool_result` events via `EventEmitter`.
   Don't add a code path that mutates state without both.
6. **Contracts beat code.** If code disagrees with `contracts/`, the code is wrong. If you need
   the contract to change, change the contract first (PR, CHANGELOG entry, ping affected owners),
   then the code.
7. **Idempotency keys are the SDK-reported Droid `tool_use_id`** (`<id>:<n>` for a tool's n-th
   write). Strict agents (`identity="strict"`: green and blue live, D7) refuse unverified, explicit or
   ambiguous ids before anything is sent (#84). A UUID4 is used only under DRY_RUN or by
   best-effort agents (red). Preparations expire after 120 s. Never reuse a key across
   different actions: a different binding under the same key is a 409.
8. **Everything must run under `DRY_RUN=true` with no Factory or LLM keys.** Agents return canned
   turns; blue's gate runs rules only. Frontend must run with `NEXT_PUBLIC_MOCK=true` and no
   backend. Keep both paths working for local reproduction.
9. **No secrets in the repo, in images, or in `NEXT_PUBLIC_*`.** Secrets live in your local
   `.env` (gitignored) or in the GitHub `production` environment, which the deploy job renders
   into the VM's `.env` (`docs/OPERATIONS.md` (Environment variables)). Never bake one into an image or a build arg,
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
    reject `AGENT_TOKEN` (invariant 12), so an agent can't reach them at all. `GET /api/audit_log`
    is blue-only and, for any agent caller, returns green/blue rows only, never `attacks.*`,
    playbook or token-refusal rows (`battlefield/app/api/reads.py`, #31); `GET /api/flags` is
    green/blue-only. Not enforced: red not reading a report (`GET /api/reports/{id}` accepts any
    caller); a reviewer checks every agent's tool list for that.
12. **Two tokens, chosen by `X-Agent`.** A request with `X-Agent` presents `AGENT_TOKEN` (that
    agent's own `AGENT_TOKEN_<AGENT>` when set; another agent's → 401, #108/#109); a request
    without it presents `OPERATOR_TOKEN`. The wrong one for the role is a 401, so an
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
level, an `identity` policy (`strict` | `best_effort`; strict by default at autonomy `off`), and
optionally a permission handler. Live turns and reflections run on their own thread and loop
(`agentkit.sync.run_on_turn_loop`), so the service loop (`/health`, blue's `/gate`) stays responsive;
share turn-scoped state across loops only through `agentkit.TurnLock`. `ledger_tool(...,
redact=fn)` redacts `agent.tool_call` arguments on every narration path.

- `system_prompt` is a **string** (replaces Droid's default coding prompt). Never use the
  `append` preset form; the default prompt is about editing code and will confuse the agent.
- `disable_builtin_skills=True` always. `restrict_tools` to your MCP server's tools; verify the
  exact tool IDs with `session.list_tools()` once and hardcode them.
- Red: `Autonomy.HIGH`, permission handler always `PROCEED_ONCE`, best-effort identity.
- Green: `Autonomy.OFF`, strict identity, so every tool call raises a permission request; the
  handler prepares the action (`LedgerClient.prepare`) and answers `PROCEED_ONCE` on
  `effective: allow`, `CANCEL` with the contract's cause otherwise (`contracts/agent-service.md`,
  Green). That every MCP call at `OFF` raises a request is a recorded Finding (`contracts/CHANGELOG.md`,
  static read of the CLI, then a live blue audit at `OFF`: 6 calls, 6 requests, #119); should it
  ever stop holding, record that there and rely on ledger-side enforcement alone.
- Blue audit: `Autonomy.OFF`, strict identity, permission handler always `PROCEED_ONCE` (D11, #90);
  the live-audit guard is lifted (#157), so the audit runs on Droid whenever `DRY_RUN_BLUE=false`.
  The hackathon deployment ran it live (`DRY_RUN_BLUE=false`); set it explicitly, because an unset
  `DRY_RUN_BLUE` follows the global `DRY_RUN`.
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

## 6. Validation and configuration

Use Python 3.11, `uv`, `ruff`, and `pytest` for Python services. Run the affected service's
`make test-<service>` and lint checks; API or enforcement changes also need a local keyless
integration smoke. Frontend changes need typecheck, lint, tests and a mock-mode build as appropriate.
Tests for changed behavior must exercise the actual path; never delete or skip a failing test
to make a change pass. Report unrelated failures.

`make mock-agents` starts the local backend with stub agents. `make up-dry` runs the full keyless
stack. `make local-stack AGENTS=mock` is the process-based alternative. Do not run multiple
stacks on the same ports. Frontend standalone: `cd frontend && NEXT_PUBLIC_MOCK=true npm run dev`.
See `docs/OPERATIONS.md` for setup and environment variables. New environment variables need
entries in `.env.example` and the operations guide.

## 7. Coding agents and delegation

Use isolated worktrees for parallel implementers and assign explicit, non-overlapping file
lists. Give each implementer the relevant contract and local guide. Implementers may commit
on their own branch; only the coordinating agent handles publication when authorized.
A fresh reviewer must independently check the final diff and relevant validation results.
Do not assume every task needs subagents or a standing orchestration loop.

Never force-push, rewrite shared history, destroy uncommitted work, access production, rotate
credentials or deploy without authorization. Do not read or edit `.env` or commit secrets,
Factory session files or recordings containing credentials. Existing tool approval denials
remain in force; do not bypass them. Report a contract gap or external blocker while continuing
independent authorized work.
