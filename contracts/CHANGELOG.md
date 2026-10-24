# Contracts changelog

Every change to anything in `contracts/` gets an entry here, in the same PR. Newest first.
Format: date · author · which file(s) · what changed · who was pinged.

Also record **Findings**: empirical answers to questions the docs left open (Droid SDK behavior,
sponsor API quirks). A finding is a contract too: once recorded, code relies on it.

## Findings

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

- 2026-10-24 · Ad · schema.sql, ledger-api.yaml, agent-service.md, events.md, agentkit models · lineages (docs/EVOLUTION-DESIGN.md §4): tables `lineages`, `playbooks`, `debriefs`; `episodes.lineage_id/generation` (unique per lineage, seeds never reused within a lineage), `attacks.resolved_day/revealed_day` (revealed outcomes frozen); operator `/lineages*`, `/fe/lineages/{id}/timeline|report`, `POST /episodes {lineage_id}`; agent `GET/PUT /playbook`, `GET /playbook/history` (PUT idempotent on X-Tool-Use-Id, 409 on a reused key with a different body; playbook.* audit rows operator-only); `options.lineage`/`options.debrief` on `/turn`, `lineage`/`debrief` on blue `/audit`, `playbook_version` on `/gate`; `POST /reflect` on every agent (DRY_RUN → `playbook: null`); events `generation.*`, `playbook.updated`, `debrief.delivered` (counts incl. `new_items`), `lineage.paused|resumed`, lineage `credit_guard`. Invariant 4 amendment (lands in `AGENTS.md` via PR E5): *`origin` is secret during play; the only exception is battlefield's debrief and after-action review in a lineage episode, which may reveal the ground truth of resolved attacks after the day they resolved, within the lineage's reveal window, and log every disclosure in `debriefs`.* Plain episodes unchanged · all (Ad integrates; no owner approval required)

- 2026-10-24 · Ad · ledger-api.yaml, events.md · replays are persisted as real `replay_*` episodes (404/409/422, runner routes 409); ws tickets gain a per-ticket nonce (`<scope>.<exp>.<nonce>.<sig>`); replayed events carry no `replay` flag · frontend (R)

- 2026-10-24 · Ad · agent-service.md, ledger-api.yaml · idempotency keys are bound to their first action (409 on reuse for a different action); n-th ledger write of one tool call is `<tool_use_id>:<n>`; green mirror uses the first write's key · green (M), blue (M), red (Al)

- 2026-10-24 · Ad · ledger-api.yaml, events.md · agent-facing /audit_log excludes red's rows; legit_injected gains vendor_changes/new_vendors · blue (M), red (Al), frontend (R)

- 2026-10-24 · Ad · schema.sql, ledger-api.yaml · attacks.created_at (in Attack responses); vendor_changes.attack_id (hidden from agents) · red (Al), frontend (R)

- 2026-10-23 · Ad · agent-service.md, ledger-api.yaml, events.md · split INTERNAL_TOKEN into AGENT_TOKEN/OPERATOR_TOKEN, POST /ws/ticket, GET /events operator-only, credit_guard error · all

- 2026-10-23 · adi · schema.sql (agent_state, inputs), events.md (x.* namespace), agent-service.md (options.inputs, extension points), ledger-api.yaml (state/inputs/query) · extension points · all

- 2026-10-23 · adi · schema.sql, ledger-api.yaml, events.md, agent-service.md · initial contracts · all
