# Contracts changelog

Every change to anything in `contracts/` gets an entry here, in the same PR. Newest first.
Format: date · author · which file(s) · what changed · who was pinged.

Also record **Findings**: empirical answers to questions the docs left open (Droid SDK behavior,
sponsor API quirks). A finding is a contract too: once recorded, code relies on it.

## Findings

- 2026-10-24 · M · **Green's nine AP Session tool IDs were observed with no model/tool execution.** A real droid-sdk 0.5.0 / mcp 1.30.0 OFF `Session.list_tools()` matched `green-ledger___ap_queue`, `green-ledger___approve_expense`, `green-ledger___approve_invoice`, `green-ledger___approve_vendor_change`, `green-ledger___match_invoice`, `green-ledger___pay_expense`, `green-ledger___pay_invoice`, `green-ledger___reject_invoice`, `green-ledger___reject_vendor_change`. Command: `UV_NO_ENV_FILE=1 python /tmp/redledger-green-sdk-list-only.py` in the installed SDK environment, using CLI authentication, `_env_file=None` and an empty temporary Session cwd. First observed on main `e6d1e56`'s unchanged AP surface; replay matched canonical #94 at `34f9fc2`. Portable source and sanitized JSON: [#94 evidence](https://github.com/md-racc/redledger/pull/94#issuecomment-6386862610). Zero streams, agent tool execution, Ledger/provider calls; this does not prove OFF prompting, callback granularity, invocation/CANCEL delivery, restriction enforcement or live acceptance. No guard lift; FYI Ad/M.
- 2026-10-24 · M · **One real OFF Blue MCP `post_report` call requested permission and preserved its SDK identity.** With droid-sdk 0.5.0 / mcp 1.30.0, CLI authentication and `gemini-3.8-flash` / low, local combined snapshot `7889fba` (#85 + #90 policy, shared #84) observed one `PROCEED_ONCE` callback, a verified SDK ID matching the intercepted LedgerClient report header and confirmed receipt, and one shared narration pair. A concurrent local ASGI gate allowed in 3.284 ms during a two-second intercepted write; reported usage was 2,989 Factory credits. Command: `UV_NO_ENV_FILE=1 python /tmp/redledger-blue-authenticated-sdk-probe.py` in the installed SDK environment with sponsor credentials cleared; portable form: `cd blue && UV_NO_ENV_FILE=1 uv run --no-sync python tests/sdk_authenticated_probe.py --allow-model-call` after #85/#90. The earlier attempt and portable replay were inconclusive (no tool/write/usage); repeatability and every-tool permission behavior remain unqualified. Synthetic books/intercepted HTTP only: no real Ledger commit, CRS/provider access, production gate or shadow acceptance, and no live guard lift. FYI Ad/M; portable source and full limits in #90's `blue/SDK-READINESS.md`.
- 2026-10-24 · M · **Blue's seven in-process session tool IDs were observed, not inferred.** With droid-sdk 0.5.0 / mcp 1.30.0 and the CRS tool set, a real `Session.list_tools()` matched `blue-ledger___benford_check`, `blue-ledger___crs_identity_check`, `blue-ledger___day_activity`, `blue-ledger___freeze_vendor`, `blue-ledger___post_report`, `blue-ledger___raise_flag`, `blue-ledger___vendor_dedupe`. Command: `cd blue && UV_OFFLINE=1 UV_NO_ENV_FILE=1 uv run --extra dev --extra droid python` with the list-only here-document in `blue/SDK-READINESS.md` §Session tool-ID discovery (companion Blue invocation PR, after #64). No stream, agent tool, ledger write or CRS request ran; this does not qualify invocation delivery, owner-loop safety or live audit. FYI Ad/M.
- 2026-10-24 · Ad · **The Droid CLI never passes the tool_use_id to an MCP tool handler.** CLI
  0.249.0 calls in-process tools with `_meta: {assemblySessionId, caller}` only; the id is visible
  in the permission request (`McpToolAction.tool_use.id`) and the stream (`ToolCall.tool_use_id`).
  agentkit binds executions to ids from those (`agentkit/invocation.py`). Proved by reading the
  binary, not running it: `grep -a -o -E '.{0,900}_meta:\{assemblySessionId:m,caller:C\}' droid`
  on `downloads.factory.ai/factory-cli/releases/0.249.0/linux/x64/droid`.
- 2026-10-24 · Ad · **MCP permission rule: a call asks for permission iff its impact level
  (low 1 / medium 2 / high 3) exceeds the autonomy level (off 0 … high 3).** So `Autonomy.OFF`
  (green) asks for every MCP call and `HIGH` (red) for none. Static read of the same binary
  (`shouldConfirmExecution`); not yet confirmed in a live run, so this settles the "does OFF raise
  a permission request for every MCP tool call" question only provisionally.
- 2026-10-24 · Al · **In-process MCP tool IDs are `"<server>___<tool>"`** (three underscores),
  e.g. `red-ledger___inspect_books`. `session.list_tools()` reports `source=None` for them, so
  matching on `source` finds nothing and `restrict_tools` silently stays unapplied (the agent
  then gets Droid's ~34 built-ins). Droid defers MCP tools and loads them through `ToolSearch`;
  with `restrict_tools` set to the `___` IDs the model still finds and calls the ledger tools.
  Proved by PR #9's live red run in the red container against `make mock-agents` (droid-sdk
  0.5.0, Factory CLI 0.248.0, real `FACTORY_API_KEY`).
- 2026-10-24 · Al · **Model menu and cost.** `list_models(api_key=…)` lists ~60 models, each
  with a `token_multiplier`; cheapest usable for red: `gemini-3.8-flash` 0.3, `gpt-5.4-mini`
  0.3, `claude-haiku-4-5` 0.4. A trivial one-tool turn costs ~10k `factory_credits`, mostly
  ~31k input tokens of tool/system context; a live red turn measured ~6.7k credits (seed 34,
  controller off, 2 days, `gemini-3.8-flash`, reasoning `low`; turns 14 s / 79 s). Proved by
  the same PR #9 live run.
- 2026-10-24 · Al · **In-process MCP tools that `await` stall the run.** A tool that returns
  instantly completes; the same tool with `await asyncio.sleep(0.3)` or an httpx call hits
  `RunTimeoutError` every time. Fix in agentkit: `DroidAgent._offload` runs each tool's
  coroutine to completion on a small thread pool. Proved by PR #9's repro in the red container
  (same setup as above).
- 2026-10-23 · Ad · **Droid CLI install works in `python:3.11-slim`.** Proved by deploy run
  40050204221 (`gh run view 40050204221 --log`, job `build (red …)`): "Factory CLI v0.248.0
  installed successfully to /root/.local/bin/droid", and `droid-sdk==0.5.0` resolved via
  `agentkit[droid]`. Details from reading the installer script:
  `curl -fsSL https://app.factory.ai/cli | sh` is the documented Linux line (docs.factory.ai CLI
  quickstart). Proved by `curl -fsSL https://app.factory.ai/cli -o install.sh` and reading it: it
  needs only `curl` + `sha256sum`, installs to `$HOME/.local/bin/droid` (already on the agent
  Dockerfiles' PATH), and hardcodes the version it fetches (v0.248.0 today), so rebuilds drift
  unless pinned (`droid update --version <v>` after install, or `npm install -g droid@<v>`). It
  picks the AVX2 vs `-baseline` binary from the *build* host's CPU. The `|| echo WARN` in the
  agent Dockerfiles hides a failed install (owners Al/M may want it removed now that it works).
- Still open:
  - Does `Autonomy.OFF` raise a permission request for every MCP tool call? (green dev, Fri night)
  - Does `comment=` on a `CANCEL` reach the model as the rejection reason? (green dev)

## Changes

- 2026-10-24 · Ad · agent-service.md, ledger-api.yaml · token refusals: audited (claimed agent, `presented_by`, 401, never the token) only when the presented token belongs to a known caller; an unknown token is only logged, so unauthenticated requests never write to the database (#109 verification); refusal rows are operator-only (excluded from agents' `GET /audit_log`) so they can't reveal who tried to act as whom · Ad integrates

- 2026-10-24 · Ad · agent-service.md, ledger-api.yaml · per-agent tokens: `AGENT_TOKEN_RED/GREEN/BLUE` (battlefield holds all three, each agent container only its own as `AGENT_TOKEN`); a request with `X-Agent: <a>` must present that agent's token, another agent's token → 401 (audited), so no agent can act or read as another; battlefield calls each agent with its own token; single-token fallback to shared `AGENT_TOKEN` / `INTERNAL_TOKEN` with a startup warning keeps DRY_RUN/mock/local-stack working. Also contracts `POST /inputs` 403 (agent body episode_id ≠ X-Episode, #104) and 422 · Ad integrates; Al/M/R notified

- 2026-10-24 · Ad · schema.sql · `events` and `audit_log` primary keys `(id)` → `(id, ts)` (new databases via CREATE TABLE; existing ones via an idempotent upgrade that only rewrites a primary key that is exactly `(id)`), plus plain `events_id` / `audit_id` indexes for `after_id` cursors. Why: Timescale (INTEGRATIONS.md B1) partitions hypertables on `ts` and requires it in every unique index. Nothing references either table by foreign key or `ON CONFLICT (id)`; `id` stays a BIGSERIAL and is still unique in practice. Hypertable creation itself happens in battlefield startup, guarded so a plain `postgres:16` keeps ordinary tables (next PR) · Ad integrates; R notified (event ids unchanged)

- 2026-10-24 · Ad · ledger-api.yaml, agentkit models · `Preparation.decided_by` is nullable: null exactly while `effective` is `pending` (an enforced escalation is held). `GET /preparations/{key}` during a hold returned null and failed model validation (step 2a verification) · Ad integrates; M notified

- 2026-10-24 · Ad · ledger-api.yaml, agent-service.md, events.md, schema.sql, agentkit models · gate preparations (integration package A, docs/AD-INTEGRATION-DESIGN.md §2–§3, decisions D1–D14): `POST /preparations` (green, keyed by the SDK tool_use_id; validates, gates, persists the verdict, marks an enforced block, holds an enforced escalation; 200 for allow **and** block with a required `effective`) and `GET /preparations/{key}`; `preparations` table (binding, mode, day, narrow state fingerprint, fixed 120 s expiry never extended); the gated route consumes a preparation (no second gate call) and answers `409 PreparationRejected` (`preparation_expired|stale|consumed|pending`) — binding/mode/day changes refused in every mode, expiry and fingerprint drift only in enforce; unprepared gated calls gate inline as before; `verdicts.cause` (`control|gate_unavailable`) on verdicts, `GateBlocked`, `gate.verdict`, `escalation.opened`, plus `preparation_id`; green's cancel `cause` vocabulary; **green no longer calls blue** (the `/gate` mirror is removed; blue `/gate` is battlefield-only, D1); live green/blue Droid writes use only SDK-reported tool_use_ids (red best-effort until Al opts in, D7); contracts the existing `409 {error: 'no active turn for this agent'}` for agent writes outside the active turn (#52). Gated-route 409s are typed `oneOf [PreparationRejected, ConflictError]` (ConflictError = the existing `{detail}` / `{error, verdict_id}` / `{error}` bodies); the per-action state fingerprint, the restart sweep (pending → block/timeout), `decided_by` semantics, green's handler causes for 422/409, and that prepare doesn't count toward `<tool_use_id>:<n>` are in the contract; `Preparation.amount` nullable; `GATED_ACTIONS` derived from the `GatedAction` literal. AGENTS.md invariant 2's mirror exception and invariant 7's UUID4 wording are removed in a later docs PR (design PR 9) · Ad integrates; green/blue (M), red (Al), frontend (R) notified

- 2026-10-24 · Ad · agent-service.md, events.md · green `fraud` debrief/AAR items cover red `vendor_change`s green approved or rejected (`field`, no `amount`) and gain outcome `approved` (green approved; neither paid nor stopped) — green could not learn about bank swaps (acceptance run); `debrief.delivered.revealed_attacks` counts the attacks behind green's `fraud` items · Ad integrates; M notified

- 2026-10-24 · Ad · agent-service.md · debrief safety (from E2a-2 verification): daily debriefs reveal only resolved red attacks; `false_positive` / `legit_blocked` move to the after-action review (listing legit blocks/freezes let agents infer unlisted ones were red); a live approved bank swap is unresolved; revealed attacks are scored as of `revealed_day` (outcome, detection and score contribution) and `controls`/`caught_by` stop at `revealed_day`; change attribution always over all attacks; green `fraud.green_action` never inferred · Ad integrates; Al/M/R notified

- 2026-10-24 · Ad · schema.sql, ledger-api.yaml, agent-service.md, events.md, agentkit models · lineages (docs/EVOLUTION-DESIGN.md §4): tables `lineages`, `playbooks`, `debriefs`; `episodes.lineage_id/generation` (unique per lineage, seeds never reused within a lineage), `attacks.resolved_day/revealed_day` (revealed outcomes frozen); operator `/lineages*`, `/fe/lineages/{id}/timeline|report`, `POST /episodes {lineage_id}`; agent `GET/PUT /playbook`, `GET /playbook/history` (PUT idempotent on X-Tool-Use-Id, 409 on a reused key with a different body; playbook.* audit rows operator-only); `options.lineage`/`options.debrief` on `/turn`, `lineage`/`debrief` on blue `/audit`, `playbook_version` on `/gate`; `POST /reflect` on every agent (DRY_RUN → `playbook: null`); events `generation.*`, `playbook.updated`, `debrief.delivered` (counts incl. `new_items`), `lineage.paused|resumed`, lineage `credit_guard`. Invariant 4 amendment (lands in `AGENTS.md` via PR E5): *`origin` is secret during play; the only exception is battlefield's debrief and after-action review in a lineage episode, which may reveal the ground truth of resolved attacks after the day they resolved, within the lineage's reveal window, and log every disclosure in `debriefs`.* Plain episodes unchanged · all (Ad integrates; no owner approval required)

- 2026-10-24 · Ad · ledger-api.yaml, events.md · replays are persisted as real `replay_*` episodes (404/409/422, runner routes 409); ws tickets gain a per-ticket nonce (`<scope>.<exp>.<nonce>.<sig>`); replayed events carry no `replay` flag · frontend (R)

- 2026-10-24 · Ad · agent-service.md, ledger-api.yaml · idempotency keys are bound to their first action (409 on reuse for a different action); n-th ledger write of one tool call is `<tool_use_id>:<n>`; green mirror uses the first write's key · green (M), blue (M), red (Al)

- 2026-10-24 · Ad · ledger-api.yaml, events.md · agent-facing /audit_log excludes red's rows; legit_injected gains vendor_changes/new_vendors · blue (M), red (Al), frontend (R)

- 2026-10-24 · Ad · schema.sql, ledger-api.yaml · attacks.created_at (in Attack responses); vendor_changes.attack_id (hidden from agents) · red (Al), frontend (R)

- 2026-10-23 · Ad · agent-service.md, ledger-api.yaml, events.md · split INTERNAL_TOKEN into AGENT_TOKEN/OPERATOR_TOKEN, POST /ws/ticket, GET /events operator-only, credit_guard error · all

- 2026-10-23 · adi · schema.sql (agent_state, inputs), events.md (x.* namespace), agent-service.md (options.inputs, extension points), ledger-api.yaml (state/inputs/query) · extension points · all

- 2026-10-23 · adi · schema.sql, ledger-api.yaml, events.md, agent-service.md · initial contracts · all
