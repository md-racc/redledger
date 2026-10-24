# Red Ledger: Factory track, "Best Use of the Factory Droid SDK"

Status as of 2026-10-24 ~23:00Z, main @ 0de4fe8; prod runs 4c6bdd9 (#131).

Paths are relative to the repo root (github.com/md-racc/redledger). "Finding" means a dated line under
`## Findings` in `contracts/CHANGELOG.md`. Status legend: `LIVE` (on prod, app.redledger.us, with a real
model today), `ON MAIN` (merged and tested, runs keyless, not exercised live on prod), `PLANNED`, `NOT DOING`.

---

## 1. Prize snapshot

| | |
|---|---|
| Prize | Factory, "Best Use of the Factory Droid SDK" |
| Value | $2,000 + Factory credits + swag (team research; **confirm on Devpost**) |
| Published criteria | None found (Devpost could not be fetched). **Confirm on Devpost.** |
| What we assume the judges look for | People who know the SDK well, so we expect them to look at depth and correctness: Droid used for non-coding work, the SDK's control surface (autonomy, permission handler, `restrict_tools`, `disable_builtin_skills`, string `system_prompt`), in-process MCP tools, streaming, usage/credits, failure handling, and what we learned empirically. This is our reading, not a published rubric. |
| Team's own note | `INTEGRATIONS.md` §5 row A2 (refreshed in #135): "Point judges at `README.md` §6 'Where Droid runs'; lead with a live episode, not a feature tour; don't claim green/blue run live until #78 clears". README §6 "Where Droid runs" (#135) is the one-table summary of every Session, autonomy, handler and tool ID in this doc |

---

## 2. Our angle

**One sentence.** Red Ledger runs three non-coding Droid agents (an attacker, a finance clerk and a
controller) against one synthetic company's books. Their only tools are in-process MCP tools, and the
Droid `tool_use_id` is carried through every permission request, event and ledger write, so each action
is idempotent, auditable and gateable. The red attacker runs live on prod today.

**30-second version (for Factory judges).**
> We used Droid as a general agent runtime, not a coding assistant. Each agent gets a string
> `system_prompt` that replaces Droid's coding prompt, `disable_builtin_skills=True`, and `restrict_tools`
> set to its exact `<agent>-ledger___<tool>` IDs. Its tools are in-process MCP tools over our Ledger API.
> Autonomy is how we set each agent's trust level. Red runs at `HIGH` and is never asked anything.
> Green and blue run at `OFF`, so every tool call raises a permission request. We use that request as
> the hook for our financial gate. The Droid CLI never passes the `tool_use_id` to the tool handler, so
> agentkit reads it from the permission request and the stream and binds it to the execution. That ID
> becomes the ledger's idempotency key (`X-Tool-Use-Id`, `<id>:<n>` for later writes). A strict mode
> refuses to run any call it can't match to an SDK-reported ID. Red runs live on `gpt-5.4-mini`:
> about 11 s and about 2.6k credits per turn. We wrote down what we learned as dated Findings: the tool
> ID format, awaiting tools stalling 0.5.0, the permission rule, and a model stall.

---

## 3. Criteria → evidence matrix

No published criteria, so the rows are the SDK surfaces this track is about.

| Criterion / interest | What we have | Status | Evidence |
|---|---|---|---|
| Droid for non-coding work | Attacker / AP clerk / controller agents; string `system_prompt` per agent (no `append` preset) | red `LIVE`; green, blue `ON MAIN` | `agentkit/agentkit/droid_agent.py:624-633`; `red/prompts/system.md`, `green/prompts/system.md`, `blue/prompts/audit.md`; AGENTS.md §5 |
| Built-ins off | `disable_builtin_skills=True` on every Session | `LIVE` (red) | `droid_agent.py:626` |
| In-process MCP tools | `droid_sdk.mcp.create_sdk_mcp_server(name="<agent>-ledger")`, one `tool()` per `@ledger_tool` function | `LIVE` (red) | `droid_agent.py:399-403`; `agentkit/agentkit/tools.py` |
| `restrict_tools` with exact IDs | red 8 IDs (derived, then checked exactly against `list_tools`); green 9 and blue 7 pinned constants observed with a real `Session.list_tools()` | red `LIVE`; green, blue `ON MAIN` | `droid_agent.py:632, 680-707`; `green/agent.py:21-31`; `blue/audit/agent.py:28-36`; Findings (Al, M ×2) |
| Autonomy + permission handler as a control surface | red `HIGH` + default `PROCEED_ONCE`; green `OFF` + handler that prepares through battlefield and returns `PROCEED_ONCE`/`CANCEL`; blue `OFF` + `PROCEED_ONCE`; never `PROCEED_ALWAYS*` | red `LIVE`; green/blue handlers `ON MAIN`, behind hard guards | `red/agent.py:22`; `green/agent.py:47, 85-113`; `blue/audit/agent.py:41, 65-68`; `contracts/agent-service.md` §Green |
| tool_use_id → idempotency key | Permission request / stream IDs bound to executions; `X-Tool-Use-Id` = id, then `<id>:<n>`; battlefield 409 on reuse for a different action | `LIVE` for red (best-effort); strict path proven on a real Ledger for blue (#119) | `agentkit/agentkit/invocation.py`; `ledger_client.py:115-131`; #33, #34, #84 |
| Strict identity | `identity="strict"` refuses unverified/ambiguous/conflicting/explicit IDs before running or writing | `ON MAIN` (green, blue); proven for blue in an authorized local real-Ledger run | `droid_agent.py:471-483`; `invocation.py` `claim_checked`; #84; `blue/SDK-READINESS.md` |
| Streaming → UI events | `include_partial_messages=True`; `ThinkingDelta`/`TextDelta` → `agent.thinking`; `ToolCallDelta`/`ToolCall`/`ToolResult` used for ID binding; tool events emitted by the tool wrapper | `LIVE` (red) | `droid_agent.py:651-664`; `agentkit/agentkit/events.py`; `/backstage/red` (`frontend/docs/backstage.md`) |
| Timeouts | stream `TURN_TIMEOUT_SEC-10`, per-tool cap `TURN_TIMEOUT_SEC-20` plus a turn-wide deadline, turn-loop ceiling, bounded flush/teardown | `LIVE` | `droid_agent.py:311-327, 434-469, 651`; `agentkit/agentkit/sync.py`; #20, #79, #81 |
| Usage / credits | `result.usage.factory_credits` logged per turn, returned in `/turn`, put on `turn.ended`, summed by a per-episode and per-lineage credit guard | `LIVE` (red) | `droid_agent.py:668-675`; `battlefield/app/orchestrator/runner.py:280-345`; `.../lineage.py`; `make prod-credits` |
| Model pinning | `DROID_MODEL_RED/GREEN/BLUE`, `DROID_REASONING_*` validated at startup | `LIVE` (red: `gpt-5.4-mini`, low) | `agentkit/agentkit/config.py`; `docker-compose.yml:97-131`; Finding (#118) |
| DRY_RUN | Every agent runs keyless with no SDK import; per-agent `DRY_RUN_RED/GREEN/BLUE` | `LIVE` (green, blue keyless on prod) | `droid_agent.py:340-342`; `.env.example:50-55` |
| Empirical findings | 10 dated Droid-related Findings + 2 open questions | n/a | `contracts/CHANGELOG.md` §Findings (all listed in §4.9) |
| Droid packaged in containers | CLI via `curl -fsSL https://app.factory.ai/cli \| sh` in `python:3.11-slim`; `droid-sdk[mcp]` via `agentkit[droid]` | `LIVE` | `red/Dockerfile`; Finding 2026-10-23 |

---

## 4. What we have, in detail

### 4.1 One shared base class: `agentkit.DroidAgent`. `LIVE` (red), `ON MAIN` (green, blue)

Every agent subclasses `DroidAgent` (`agentkit/agentkit/droid_agent.py`) and supplies: `name`,
`autonomy`, `system_prompt`, `tools()`, `build_prompt(req)`, `dry_run_turn(req)`, and optionally
`on_permission`, `reflect`, `identity`. The base class owns the whole SDK lifecycle, so the three teams
never touch Session plumbing. One live turn (`_droid_turn`, lines 610-678) goes like this:

1. Build a turn-scoped `InvocationRegistry` and an in-process MCP server named `<agent>-ledger` from the
   agent's `@ledger_tool` functions (each wrapped by `_offload`, §4.4).
2. `SessionConfig(autonomy=…, disable_builtin_skills=True, system_prompt=<string>, mcp_servers=[server],
   restrict_tools=<exact IDs>)`.
3. `Session(model=DROID_MODEL, reasoning_effort=ReasoningEffort(DROID_REASONING) or None, config,
   interactions=InteractionHandlers(on_permission=_permission_entry), api_key=FACTORY_API_KEY)`.
4. `_learn_tool_ids(session)`: `session.list_tools()` compared exactly against the expected set (§4.3).
5. `session.stream(prompt, include_partial_messages=True, timeout=TURN_TIMEOUT_SEC - 10)`.
6. Forward stream events (§4.6); `registry.close()` in `finally`, so every call that never ran still
   gets its event pair.
7. Read `stream.result.usage`. Log `turn_usage … credits=` at INFO and return `Usage(factory_credits,
   input_tokens, output_tokens)`. A result with `success=False` raises, and the turn becomes `ok:false`.

`make_agent_app` (`agentkit/agentkit/server.py`) gives every agent `/health`, `/turn` and `/reflect`,
with bearer auth and a one-turn-at-a-time lock (a second call gets 409). The SDK is imported lazily,
so DRY_RUN and tests run without it.

### 4.2 Per-agent configuration (exact)

| | red | green | blue (audit) |
|---|---|---|---|
| Class | `RedAgent` (`red/agent.py`) | `GreenAgent` (`green/agent.py`) | `AuditAgent` (`blue/audit/agent.py`) |
| Autonomy | `"high"` → `Autonomy.HIGH` | `"off"` → `Autonomy.OFF` | `"off"` → `Autonomy.OFF` |
| Identity policy | best_effort (the default when autonomy ≠ off) | `"strict"` | `"strict"` |
| Permission handler | base default: always `PROCEED_ONCE` (`droid_agent.py:256-264`). At HIGH the CLI never asks (Finding, permission rule) | `on_permission` (`green/agent.py:85-113`), see §4.5 | always `PROCEED_ONCE` (`blue/audit/agent.py:65-68`) |
| `restrict_tools` | `red-ledger___add_employee`, `red-ledger___create_vendor`, `red-ledger___inspect_books`, `red-ledger___list_schemes`, `red-ledger___request_vendor_bank_change`, `red-ledger___run_scheme`, `red-ledger___submit_expense`, `red-ledger___submit_invoice`. Derived as `f"{name}-ledger___{tool}"` from `red/tools.py`, then replaced by the exact matches from `list_tools()` | pinned `AP_TOOL_IDS` (`green/agent.py:21-31`): `green-ledger___ap_queue`, `…___approve_expense`, `…___approve_invoice`, `…___approve_vendor_change`, `…___match_invoice`, `…___pay_expense`, `…___pay_invoice`, `…___reject_invoice`, `…___reject_vendor_change`. Set before the first Session | pinned `AUDIT_TOOL_IDS` (`blue/audit/agent.py:28-36`): `blue-ledger___benford_check`, `…___crs_identity_check`, `…___day_activity`, `…___freeze_vendor`, `…___post_report`, `…___raise_flag`, `…___vendor_dedupe`. Set before the first Session |
| Model env | `DROID_MODEL_RED`, `DROID_REASONING_RED` | `DROID_MODEL_GREEN`, `DROID_REASONING_GREEN` | `DROID_MODEL_BLUE`, `DROID_REASONING_BLUE` |
| Prod today | **`LIVE`**: `dry_run=false`, `gpt-5.4-mini`, reasoning `low` (prod `/health`; Finding #118; README §6 "Where Droid runs") | `dry_run=true` (keyless) | `dry_run=true` (keyless) |
| Live guard | none | `_droid_turn` raises `PREREQUISITE` unconditionally (`green/agent.py:81-83`) | `_droid_turn` raises unconditionally (`blue/audit/agent.py:150-163`); `live_readiness().ready` is hard-typed `False` |
| Prompt | 11-line attacker prompt; per-turn prompt inlines the scheme catalog and says "inspect_books once, run_scheme once, one sentence, stop" (`red/agent.py:63-72`) | AP-clerk procedure (`green/prompts/system.md`) | controller prompt plus a JSON snapshot of service-derived facts (`blue/audit/agent.py:141-148`) |

**Wording note.** AGENTS.md §5 says "verify the exact tool IDs once and hardcode them". Green and blue
hardcode them. Red derives them from its tool list and requires an exact match against
`session.list_tools()`. Say "exact tool IDs, checked against `list_tools()`", not "hardcoded" for all three.

### 4.3 `restrict_tools` and exact tool IDs. `LIVE` (red)

- In-process MCP tool IDs are `"<server>___<tool>"` (three underscores). `list_tools()` reports
  `source=None` for them, so filtering on `source` silently left `restrict_tools` unapplied, and the
  agent got Droid's ~34 built-ins (Finding, Al, PR #9). Without the restriction, the code comment notes,
  the agent "spends the turn reading its own source" (`droid_agent.py:629-631`).
- `_learn_tool_ids` (`droid_agent.py:684-707`, from #84 B-3) matches exactly, with no suffix match.
  For best_effort (red), a mismatch or a failed listing is logged and the turn goes on. For strict
  (green, blue), it runs on every live turn, and a missing ID, an extra ID or a listing failure fails
  the turn **before `stream()`**.
- Droid defers MCP tools and loads them through its `ToolSearch`. With `restrict_tools` set to the
  `___` IDs, the model still finds and calls the ledger tools (Finding, Al). The gemini stall (§4.9)
  showed up as exactly one built-in `ToolSearch` and no ledger calls.

### 4.4 In-process MCP tools and the tool bridge. `LIVE` (red)

- Tools are plain async functions decorated with `@ledger_tool(name, description, redact=…)`
  (`agentkit/agentkit/tools.py`). They reach the turn's `LedgerClient` / `EventEmitter` through
  contextvars (`ctx`). The same functions are called directly by `dry_run_turn`.
- **Finding (Al, PR #9):** with droid-sdk 0.5.0, an in-process tool that `await`s anything (even
  `asyncio.sleep(0.3)` or an httpx call) stalls the run until `RunTimeoutError`. So `_offload`
  (`droid_agent.py:509-608`) hands the SDK a **sync** handler. It runs the coroutine to completion on
  a private event loop in a 4-worker thread pool, with its own `LedgerClient`, under
  `contextvars.copy_context()`, and with a budget (§4.7). Tool narration from the worker is buffered
  and replayed on the loop thread before the call's `agent.tool_result`.
- The sync handler blocks the Session's loop while the tool runs. Each turn therefore runs on its own
  thread and loop (`agentkit/agentkit/sync.py` `run_on_turn_loop`, #79), and the service loop stays
  responsive. #79's test: a tool that froze its loop for 2 s left service-loop gaps and `/health`
  latency at ≤ 50 ms.
- **Teardown (#81):** after #79, prod red logged `Task was destroyed but it is pending!`
  (sse_starlette `_shutdown_watcher` left by the SDK's in-process MCP server). The turn loop now
  cancels leftover tasks with a bounded `TEARDOWN_SEC = 2.0` and logs `turn_loop_tasks_abandoned`
  instead of hanging.
- Keyless test against the real SDK MCP server: `agentkit/tests/test_turn_loop_mcp.py` drives a real
  `droid_sdk.mcp` server with a real MCP `call_tool` (no CLI, no model, no keys). It is skipped when
  `droid-sdk[mcp]` is not installed.

### 4.5 tool_use_id → Ledger idempotency key. `LIVE` (red, best-effort); strict `ON MAIN`

**The problem (Finding, Ad):** Droid CLI 0.249.0 calls in-process tools with
`callTool({name, arguments, _meta:{assemblySessionId, caller}})`, with no `tool_use_id`. The handler
only gets validated arguments (`droid_sdk/mcp.py`). The ID shows up in two places: the permission
request (`McpToolAction.tool_use.id`) and the stream (`ToolCall.tool_use_id`, `ToolCallDelta.tool_use.id`).
This was proved by reading the binary (`grep -a … _meta:\{assemblySessionId:m,caller:C\}` on the
0.249.0 linux-x64 `droid`), not by guessing.

**How agentkit binds it** (`agentkit/agentkit/invocation.py`, #34):

1. `_permission_entry` calls `registry.observe_permission(request)` *before* the subclass handler runs.
   The CLI waits for our answer before it executes, so registration always comes before execution.
   The stream's `ToolCallDelta`/`ToolCall` also register IDs (`droid_agent.py:655-662`).
2. When the SDK invokes our sync handler, `_begin_invocation` links the execution to a registered
   tool use: an `_meta` hint, if one ever equals a registered ID (forward-compatible, never true on
   CLI 0.249.0, and the first call per process logs the `_meta` keys); else the oldest registered,
   not yet executed use of the same tool with **identical canonical arguments**. Canonical means
   validated through the same pydantic model `droid_sdk.mcp.tool` builds, so defaults and coercions
   match. At `OFF` (`require_permission`), only approved uses can be claimed. A cancelled or undecided
   call can never lend its ID. There is no "last seen ID" fallback.
3. The `Invocation` is bound in a contextvar. `LedgerClient._write` (`ledger_client.py:115-131`) sends
   `X-Tool-Use-Id = <tool_use_id>` on the call's first write and `<tool_use_id>:<n>` on the n-th
   (`invocation.write_key`). Example: red's `run_scheme("ghost_vendor")` makes `POST /attacks` (id),
   `POST /vendors` (`id:2`) and `POST /invoices` (`id:3`) (`red/tools.py:58-70`,
   `red/schemes/ghost_vendor.py`). An explicit key the invocation already used raises
   `IdempotencyKeyReused` before anything is sent.
4. The same ID is on that call's `agent.tool_call` and `agent.tool_result`. Every registered ID gets
   exactly one pair, including CANCELs, handler exceptions (which fail closed) and calls that never ran.
5. Battlefield binds a key to the first action it judged (action, entity_type, entity_id, amount).
   The same key on a different action gets an audited `409 "idempotency key reused for a different
   action"` and is never replayed (#33; `battlefield/app/gate/gatekeeper.py:54`;
   `contracts/agent-service.md` §Blue). Writes without `X-Tool-Use-Id` get 400 (`battlefield/app/auth.py:170`).

**Red (best-effort, HIGH):** there is no permission request, so the stream `ToolCall` is the only
source of the ID, and it races the MCP HTTP call. If it loses, the execution runs under a UUID4
(logged `tool_use_id_unverified`). The late `ToolCall` then gets a link pair
`{"ran_as": <local id>}`, so the SDK ID is still accounted for. How often red wins that race on prod is
`UNVERIFIED` (not measured).

**Strict identity (#84, green and blue):** `identity_policy()` is strict when autonomy is `off`.
In a strict live turn:
- `registry.claim_checked` refuses with `unverified` (no match), `ambiguous` (more than one equally
  preferred identical use; D8 refuses them all), `conflicting` (an `_meta` hint that disagrees with the
  arguments) or `explicit` (a caller-supplied `_tool_use_id`).
- A refused call **does not run**. The model gets
  `{"error":true,"identity":<reason>,"not_run":true,…}` with one event pair under a local ID.
- `LedgerClient._write` raises `UnverifiedInvocation` before sending if the current invocation's
  source is not `permission | stream | mcp_meta`, or if an explicit key isn't `<id>` / `<id>:<n>` of
  this call. `LedgerClient.prepare` refuses a non-SDK-reported `ToolUse` the same way.
- Tool-ID drift fails the turn before streaming (§4.3).

**Green's handler (dormant, `green/agent.py:85-113`; contract `contracts/agent-service.md` §Green):**
no bound registry → `CANCEL`. More than one action or use in one request → `CANCEL` ("batched
permissions are unsupported", because one SDK response covers the whole batch). Unverified source →
`CANCEL`. Otherwise `decide_preparation` (`green/preparation.py`) maps the tool and its args to
`{action, entity_id, args}` and calls `POST /api/preparations` with `X-Tool-Use-Id = tool_use_id`.
Battlefield asks blue `/gate`, persists the verdict and answers `effective`. `allow` → `PROCEED_ONCE`.
`block` → `CANCEL` with a JSON comment `{cause, reason, verdict_cause}`, where cause is `control_hold`,
`escalation_timeout`, `integration_failure` or `invalid_state`. The tool's own gated write then uses
the same key and consumes the preparation without a second gate call (#80, #86, #87, #89). An earlier
design had green call blue directly. #80 removed that, so green prepares only against battlefield
(`green/IDENTITY.md`).

### 4.6 Streaming → events. `LIVE` (red)

- `ThinkingDelta` and `TextDelta` → `emitter.thinking(text)`. Deltas are buffered and flushed as one
  `agent.thinking` once over 200 chars or when a tool call starts (`events.py`). The complete
  `AssistantMessage` is not forwarded (AGENTS.md §5: it would duplicate the deltas).
- `agent.tool_call` / `agent.tool_result` are emitted by `_offload` around the actual execution, under
  the SDK ID. The stream's `ToolCall`/`ToolResult` are used to learn IDs and to close calls that never
  reached our handler. Events go to battlefield `POST /api/events` in batches. The end-of-turn flush
  has a 5 s budget (#20), and leftovers are logged `events_dropped`.
- What the audience sees: `/backstage/red` prints red's thinking and tool calls live
  (`frontend/docs/backstage.md`).

### 4.7 Timeouts (defaults, `TURN_TIMEOUT_SEC=180`). `LIVE`

| Bound | Value | Where |
|---|---|---|
| Droid `stream(timeout=)` | `TURN_TIMEOUT_SEC - 10` = 170 s | `droid_agent.py:651` |
| Per-tool cap, also the turn-wide tool window | `max(5, TURN_TIMEOUT_SEC - 20)` = 160 s; each call clamped to what the turn has left (floor 1 s) | `droid_agent.py:434-469` |
| Wait on a wedged tool thread | + 2 s grace; model gets "tool timed out … outcome unknown, re-read the books before retrying" | `droid_agent.py:574-590` |
| Turn-loop ceiling | `TURN_TIMEOUT_SEC`, cancel join ≤ 2 s | `droid_agent.py:311-327`; `sync.py` |
| Battlefield's wait on `/turn` | `TURN_TIMEOUT_SEC + 5` | `droid_agent.py:316-319` docstring; `contracts/agent-service.md` |
| DRY_RUN turn | `TURN_TIMEOUT_SEC - 5` | `droid_agent.py:341` |
| `/reflect` | `TURN_TIMEOUT_SEC - 10` | `droid_agent.py:372` |
| Ledger read timeout | `max(HTTP_TIMEOUT_SEC, ESCALATION_TIMEOUT_SEC + GATE_TIMEOUT_SEC + 15)` = 113 s (a gated write may be held for a human) | `ledger_client.py:76-81` |
| Blue audit budget | `min(170, TURN_TIMEOUT_SEC - 10)` | `blue/audit/agent.py:89` |

The tool cap sits above the 90 s escalation hold on purpose. Cutting a held green payment short would
tell the model "failed" while battlefield might still pay it (#20, #34). agentkit warns at startup if
`TURN_TIMEOUT_SEC` makes that impossible.

### 4.8 Usage, credits and the credit guard. `LIVE`

- Per turn: `result.usage.factory_credits`, input and output tokens → `TurnResponse.usage` → battlefield
  `turn.ended {factory_credits}` (`runner.py:280-295`).
- `MAX_CREDITS_PER_EPISODE` (battlefield): the per-episode running total pauses the episode with an
  `error {where:"credit_guard"}` event once a paid turn crosses the limit. Only a human
  `resume`/`step` re-arms it. DRY_RUN turns report no credits and never trip it (`runner.py:300-345`).
  It counts after each turn, so a turn already running can overshoot once.
- Lineages have their own `config.max_credits` across generations (`battlefield/app/orchestrator/lineage.py`).
  `make prod-evolve` requires `MAX_CREDITS`. `make prod-credits` prints credits per agent and day.
- Prod runs `MAX_CREDITS_PER_EPISODE=375000`, the value `deploy/PROD-OPS.md` recommends. At the measured
  ~2.6k credits per red turn, a 10-day episode (10 red turns) spends ~25k (the #136 recordings: 26,230 and 24,449),
  so the guard is a runaway stop, not a budget that bites in normal play.
- Reflection between generations is deterministic code for all three agents (`red/evolution.py` fold,
  `green/playbook.py`, `blue/gate/learned.py`). It makes no Droid call and spends no credits.

### 4.9 Empirical Droid Findings (`contracts/CHANGELOG.md` §Findings), all of them

| Date · who | Finding | What it proved / how |
|---|---|---|
| 2026-10-23 · Ad | Droid CLI installs in `python:3.11-slim` via `curl -fsSL https://app.factory.ai/cli \| sh`; `droid-sdk==0.5.0` resolves via `agentkit[droid]` | Deploy run log ("Factory CLI v0.248.0 installed successfully"). Reading the installer: it needs only curl + sha256sum, hardcodes the version (so rebuilds drift unless pinned) and picks AVX2 vs baseline from the *build* host's CPU |
| 2026-10-24 · Al | Awaiting in-process MCP tools stall the run (`RunTimeoutError`) | Repro in the red container (PR #9); fix is `_offload` |
| 2026-10-24 · Al | Model menu and cost: `list_models` ~60 models with `token_multiplier` (gemini-3.8-flash 0.3, gpt-5.4-mini 0.3, claude-haiku-4-5 0.4); trivial one-tool turn ~10k credits (mostly ~31k input tokens of tool/system context); a live red turn ~6.7k credits (gemini-3.8-flash, low, turns 14 s / 79 s) | PR #9 live run |
| 2026-10-24 · Al | In-process MCP tool IDs are `<server>___<tool>`; `list_tools()` gives `source=None`, so a source filter leaves `restrict_tools` unapplied (~34 built-ins); MCP tools are deferred behind `ToolSearch` but still found | PR #9 live red run against `make mock-agents` |
| 2026-10-24 · Ad | MCP permission rule: a call asks iff its impact level (low 1 / medium 2 / high 3) exceeds autonomy (off 0 … high 3), so `OFF` asks for every MCP call and `HIGH` for none | Static read of `shouldConfirmExecution` in the CLI binary. **Recorded as provisional** (not yet confirmed live) |
| 2026-10-24 · Ad | The CLI never passes `tool_use_id` to an MCP tool handler (`_meta:{assemblySessionId, caller}` only) | `grep -a` on the 0.249.0 binary |
| 2026-10-24 · M | Blue's 7 session tool IDs observed with a real `Session.list_tools()` (SDK 0.5.0 / MCP 1.30.0) | List-only probe; no stream or tool run |
| 2026-10-24 · M | One real OFF blue `post_report` call requested permission and kept its SDK identity: one `PROCEED_ONCE`, verified ID = intercepted `X-Tool-Use-Id` = receipt, one event pair; concurrent local `/gate` 3.284 ms; 2,989 credits | Authenticated probe, intercepted HTTP, `gemini-3.8-flash` low |
| 2026-10-24 · M | Green's 9 AP session tool IDs observed with zero streams or tool calls | List-only probe, #94 evidence |
| 2026-10-24 · Ad | `gemini-3.8-flash` stalled live red turns on prod from ~20:30Z: almost no stream output, one built-in `ToolSearch` after 80–140 s, no ledger tools, `RunTimeoutError` at 170 s (ep_1961aa7021ec, ep_9a15474fb8e7), with the same image, CLI and `droid-sdk==0.5.0` that worked at 16:04Z in 20–38 s. Switching only `DROID_MODEL_RED=gpt-5.4-mini` (low) fixed it: full attack in 11.2 s, 2,635 credits/turn (ep_568aef023d7c) | Prod episodes; #118 |
| Still open | (1) Does `Autonomy.OFF` raise a permission request for every MCP call? (2) Does `comment=` on `CANCEL` reach the model? | (1) Blue's real-Ledger run (#119) saw 6 tool calls with 6 permission requests for blue's tools, which supports the provisional rule, but the CHANGELOG line has not been updated. (2) Untested; green's acceptance matrix row "cancellation" would settle it (`green/SDK-ACCEPTANCE.md`) |

Also measured, outside CHANGELOG (`blue/SDK-READINESS.md`): on `gemini-3.8-flash`, 2 of 7 blue audit
sessions produced zero stream events for the whole 170 s, while minimal probes finished in < 7 s.
At ~15–40 s per tool round-trip, 1 of 5 non-stalled audits finished in budget. Per-turn credits varied
widely (9,834 for a 6-call audit; 5,825 and 3,308 for one-word probes), which suggests a large fixed
per-session overhead in metering.

### 4.10 Blue: real-Ledger Droid acceptance. `ON MAIN` (local, authorized runs only; not on prod)

`blue/tests/sdk_real_ledger_acceptance.py` (#119, not collected by pytest, needs `--allow-model-call`)
serves the real `AuditAgent` through a test-only `_droid_turn` subclass against a local battlefield,
with Postgres and mock red/green, for a 1-day enforce episode. The checks use operator reads only.
- **Happy path** (ep_edd0d922b9a5, `gemini-3.8-flash`, 9,834 credits): 6 tool calls, 6 permission
  requests, exactly one event pair each, all IDs SDK-reported. Real commits `flags.raise` 201 and
  `reports.post` 201 with `confirmed` receipts. Same-key replay of the report → audited 409, no second
  execution. `/gate` sampled every 50 ms during the live audit: 1,817 samples, p95 8.04 ms, max 56.6 ms,
  zero errors.
- **Interrupted path** (ep_677e52f4197f, `gpt-5.4-mini`, 2,317 credits, 18.4 s wall): battlefield was
  SIGKILLed while the `post_report` write was being sent, then restarted. The receipt was `unknown`
  with 0 commits. Same-key replay → 409 with no second commit. `/gate` max 69.19 ms over 275 samples.
- Blue's `/gate` itself is not a Droid call. It is rules plus an optional bounded LLM advisory
  (`blue/gate/engine.py`, `blue/gate/llm.py`, 2.4 s deadline) and has an 8 s budget. Droid is used for
  the agentic audit, not the synchronous hot path.

### 4.11 Why green and blue are not live yet (readiness guards). `ON MAIN`, `PLANNED` P4

- **Green:** `GreenAgent._droid_turn` raises `PREREQUISITE` ("SDK permission, restriction, identity and
  cancellation acceptance are required before Droid execution") before any SDK import, MCP server or
  Session. It checks nothing at runtime: it is a hard stop that only a reviewed PR can lift.
  `/health` reports `droid_ok:false` in DRY_RUN without probing. The acceptance proposal
  (`green/SDK-ACCEPTANCE.md`) would need: one targeted call per AP tool under OFF, with the permission
  arriving before execution, one SDK ID, and only `PROCEED_ONCE` allowing it; CANCEL with a nonce in
  the comment reaching the model; batch granularity; restriction enforcement; and 4 real-Ledger
  Stage B rows (off allow, shadow, enforce block, enforce escalation timeout). Proposed ceiling:
  16 sessions, 50,000 credits. **Not authorized or run.** The harnesses exist and refuse before any
  SDK access (`green/tests/sdk_acceptance_harness.py`, `sdk_stage_b_harness.py`).
- **Blue:** `AuditAgent._droid_turn` raises unconditionally ("no stream or write attempted") and
  records a gap. `blue/audit/readiness.py` `live_readiness()` returns `ready=False` (typed
  `Literal[False]`) with reason codes `blue_session_ids_unverified`, `sdk_invocation_binding_unverified`,
  `blue_owner_loop_safety_unverified`, `blue_narration_ownership_unverified`,
  `nonblocking_bridge_unverified`, `live_audit_disabled` (+ `sdk_unavailable`). `/health.droid_ok`
  echoes that (always false). The offline diagnostic (`python -m audit.readiness`) never opens a
  Session. Several of those codes are now covered by #119's authorized evidence, but the guard has
  not been lifted. M's stated next steps are CRS acceptance and the three-day all-real shadow run (#78).
- **Prod switch:** compose resolves `DRY_RUN: ${DRY_RUN_<AGENT>:-${DRY_RUN:-false}}`
  (`docker-compose.yml:97, 113, 129`). Prod runs `DRY_RUN=false`, `DRY_RUN_GREEN=true`,
  `DRY_RUN_BLUE=true` (`deploy/ENVIRONMENT.md:91`).

### 4.12 Red on Droid in practice. `LIVE`

- Tools (8): `list_schemes`, `inspect_books`, `run_scheme`, `create_vendor`, `submit_invoice`,
  `request_vendor_bank_change`, `submit_expense`, `add_employee`. Red has no pay, approve, freeze or
  audit-log tool, and battlefield strips `origin` from every agent response (`battlefield/app/db.py:22`).
- Schemes: `ghost_vendor`, `bank_swap`, `duplicate_invoice`, `threshold_split`, `ghost_employee`
  (`red/schemes/`).
- Prompt shaping, learned live: the catalog is inlined and the turn is limited to one `inspect_books`
  plus one `run_scheme`, because live turns that wandered ran past the timeout (`red/agent.py:64-65`).
  A judge-forced attack uses a "You MUST run scheme X" prompt (`red/agent.py:57-62`).
- Lineage learning (#105): the playbook goes into the prompt as a labelled DATA block. `inspect_books`
  persists the deterministic fold via `PUT /api/playbook` under the call's invocation key. `/reflect`
  is the same fold with no model call. The model *uses* the playbook. It does not write it.

### 4.13 DRY_RUN. `LIVE`

Every agent's `dry_run_turn` calls its own tool functions directly, makes real Ledger calls and emits
the same events, with no SDK import (`droid_agent.py:340-342`). Red, green (#92) and blue (#79 test
fixture) also run keyless turns on the shared turn loop, so keyless suites exercise the threading.
Keyless runs are how four of five people develop (AGENTS.md §3.8), and how green and blue run on prod today.

---

## 5. What's in flight / planned (Factory-relevant)

| Item | Owner | Depends on | If it doesn't land, say |
|---|---|---|---|
| **P1** Live-red lineage on prod. **Done:** `ln_f52a3df83c8d`, 5 generations × 8 days, enforce, `gpt-5.4-mini` | Ad | — | Done. Red spent 20,402 / 20,744 / 22,831 / 22,974 / 22,313 credits per generation (~109k for 40 red turns, ~2.7k per turn); reflection spent nothing (§4.8). Red re-weighted toward `threshold_split` and extraction rose from $19,076 to $97,734; blue's learned controls never fired on a split (hyphenate.md §4.10) |
| **P2** Recorded controller-off vs. controller-on episodes with live red, same seed. **Done:** `docs/recordings/` (#136), seed 42, 10 days | Ad | — | Done: off $10,284.61 extracted, enforce $1,824.22; 26,230 and 24,449 red credits. Not yet wired into the show, whose controller-off act is still a projection of the mock fixture (`frontend/docs/show-mode.md`) |
| **P4** Green and/or blue live on Droid on prod | M (#78) | Green: authorized acceptance matrix + guard-lift PR. Blue: CRS acceptance, guard-lift PR, three-day shadow | "Red is live; green and blue run their full logic keyless on the same harness." Blue's strict path has been proven on a real Ledger locally (#119) |
| Settle the two open Findings (OFF prompting for every MCP call; CANCEL comment delivery) | M / Ad | Green acceptance rows A-targeted + cancellation | Cite #119 for blue's tools; say CANCEL-comment delivery is untested |
| Retry `gemini-3.8-flash` for red | Ad | Time | Prod red stays on `gpt-5.4-mini` (Finding #118) |
| `NOT DOING` | | | Droid inside `/gate` (8 s synchronous budget; rules + bounded advisory instead); `PROCEED_ALWAYS*` / `PROCEED_AUTO_RUN*` (AGENTS.md §5); `model="auto"` |

---

## 6. Demo beats for this track

Mapped to `frontend/docs/pitch-script.md` and `frontend/docs/show-mode.md`.

**Key fact for the stage.** With red live, the 90-second show defaults to the **recorded** feed.
`wantLive` needs every agent keyless (`frontend/components/arena/useShow.ts:15-20`), and red is not.
The live Droid evidence is the **Launch attack** console and `/backstage/red`, not the show itself.

| When | Screen | What Factory judges should see |
|---|---|---|
| 0:00–1:28, R's show | Laptop 1 | Recorded run (say so if asked). No Droid claim here beyond "red is a Droid agent" |
| Red's minute ("red is a real agent on Factory's Droid SDK…") | Laptop 2, `/backstage/red` | Red's `agent.thinking` text and `agent.tool_call`/`tool_result` lines, each with a `tool_use_id`; tool names `inspect_books` → `run_scheme` |
| "Pick an attack. Any one." (R's close) | Laptop 1 Launch attack → laptop 2 | A live red Droid turn: the forced-scheme prompt, `inspect_books`, `run_scheme`, then `turn.ended` with `factory_credits` (~2.6k) after ~11 s. On laptop 4, blue's verdict on green's attempt (keyless gate) |
| Q&A, if a Factory judge asks | Laptop 2 / backstage battlefield | Same `tool_use_id` on the tool event and on the ledger write (`X-Tool-Use-Id`, `:2`, `:3`); `/health` shows `red dry_run=false model=gpt-5.4-mini`, green/blue `dry_run=true` |
| Evolution beat | EvolutionCard | On prod with the backend up, the card loads the newest finished lineage, now the live-red `ln_f52a3df83c8d` (`frontend/lib/arena/lineage.ts:47-57`). Factory angle: 40 live Droid turns across 5 generations, ~109k credits, red's playbook folded between generations with no model call. Offline it is the synthetic golden fixture, not a recording; R's close line "that learning card was a recording" needs the version true on the day |

**Fallbacks.** If a red turn stalls, it fails cleanly with `turn.ended ok:false` within
`TURN_TIMEOUT_SEC + 5` and the episode goes on (`contracts/agent-service.md`). Switch to a
recorded run (`?show=recorded`), or replay the live-red recordings in `docs/recordings/` (#136) after copying them into the fixtures dir. Do not change models or
DRY_RUN flags on stage; that is Ad's prod change. Say: "the attacker's live turn timed out; here's the
recording of the same code path."

---

## 7. Devpost copy, paste-ready

**Inspiration.** Finance teams are being asked to let AI agents move money. Nobody crash-tests that.
We wanted to find out whether an agent with the checkbook can be tricked, and whether a controller
agent can stop it without blocking honest work.

**What it does.** Red Ledger is an adversarial sandbox around one synthetic company's books. A red
agent commits accounts-payable fraud (ghost vendors, bank-account swaps, duplicate invoices, threshold
splits, ghost employees). A green agent does the legitimate AP work. A blue controller gates every
money-moving action and audits the books daily. Every agent works only through tools over one Ledger
API, and every action is logged and scored against hidden ground truth.

**How we built it (Factory angle).** All three agents subclass one base class, `agentkit.DroidAgent`,
on the Factory Droid SDK. Each Session gets a plain-string `system_prompt` that replaces the coding
prompt, `disable_builtin_skills=True`, an in-process MCP server of the agent's ledger tools, and
`restrict_tools` set to the exact `<agent>-ledger___<tool>` IDs, checked against `session.list_tools()`
every strict turn. Autonomy sets each agent's trust level. The attacker runs at `HIGH`. The clerk and
the controller run at `OFF`, so every tool call raises a permission request, and the clerk's handler
turns that request into a gate check before money moves. The CLI doesn't hand the `tool_use_id` to
tool handlers, so we read it from permission requests and the stream, bind it to each execution by
exact tool and canonical arguments, and send it as the ledger's idempotency key (`X-Tool-Use-Id`, with
`<id>:<n>` for later writes). A strict mode refuses to run anything it can't tie to an SDK-reported ID.
We stream partial messages into live thinking and tool events, and log `factory_credits` per turn into
a per-episode credit guard. Every bound has a timeout, and each turn runs on its own event loop so a
tool never freezes the service. Everything also runs keyless under `DRY_RUN`.

**Challenges we ran into.** In-process tools that `await` stalled the SDK, so we run each tool to
completion on a worker loop. Tool IDs are `server___tool`, and filtering `list_tools()` by `source`
silently disabled our restriction. The tool_use_id never reaches the handler, so we built a correlation
registry with a strict mode. `gemini-3.8-flash` started stalling live turns on prod with nothing else
changed; switching only the pinned model to `gpt-5.4-mini` fixed it (11 s, ~2.6k credits per turn).
We recorded each of these as a dated Finding in the repo.

**Accomplishments we're proud of.** The red attacker runs live on Droid on prod and completes full
attacks. The controller's strict-identity path ran against a real local Ledger in authorized runs:
every tool call had a permission request and exactly one event pair. Writes committed under the SDK's
ID, and a same-key replay was refused. A write killed mid-flight left an honest `unknown` receipt with
no duplicate. Gate p95 stayed at 8 ms during the live audit. A five-generation lineage ran on prod with the live attacker: 40 Droid
turns, ~109k credits, ~2.7k per turn, and red's playbook updated between generations without a model call.

**What we learned.** Autonomy plus a permission handler is a real authorization surface for non-coding
agents, as long as you can carry the call's identity end to end. Pin models, and measure credits per
turn, because fixed session overhead dominates small turns. Write down SDK behaviour you verify and
don't guess.

**What's next.** Green and blue live on Droid once their acceptance runs pass `[only if P4]` (otherwise:
"green and blue run their full logic keyless on the same harness"). Settling whether `CANCEL` comments reach the model.

**Built with.** python, fastapi, factory-droid-sdk, droid-cli, mcp, pydantic, httpx, structlog,
postgresql, docker, caddy, cloudflare, next.js, typescript, three.js, react-three-fiber, tailwindcss.

**Why this fits "Best Use of the Factory Droid SDK".** We used Droid for finance agents, not code.
We replaced the default prompt, turned off built-in skills, and restricted each session to exactly its
own MCP ledger tools. Droid's autonomy levels and permission requests are the control layer, and each
Droid `tool_use_id` is carried into the ledger as its idempotency key, with strict refusal when it
can't be verified. The attacker runs live on prod today; the clerk and controller run the same harness
keyless while their live acceptance finishes. Every SDK behaviour we depend on is recorded as a dated,
reproducible Finding in the repo.

---

## 8. Claims ledger

**Safe to say**
- Red runs live on the Factory Droid SDK on prod (`gpt-5.4-mini`, reasoning low): ~11 s and ~2.6k credits per full attack turn (Finding #118).
- All three agents share one `DroidAgent` base: string `system_prompt`, `disable_builtin_skills=True`, in-process MCP tools, exact `restrict_tools` IDs.
- Red `Autonomy.HIGH`; green and blue `Autonomy.OFF` with permission handlers; no handler ever returns `PROCEED_ALWAYS*`.
- The Droid `tool_use_id` is carried to `agent.tool_call`/`tool_result` and to the ledger's `X-Tool-Use-Id` (`<id>:<n>` for later writes); battlefield refuses a reused key on a different action.
- Strict identity refuses tool calls and writes not tied to an SDK-reported ID (#84).
- Credits are logged per turn and feed a credit guard that pauses episodes and lineages.
- Everything runs keyless under DRY_RUN; green and blue do so on prod.
- We recorded our SDK findings with dates and commands (§4.9).

**Say with this caveat**
- "Green's permission handler gates payments through blue" → the handler is on main and tested, but green's live Droid turn is hard-guarded off. On prod, green runs keyless and the ledger gates its writes inline.
- "Blue's Droid audit is proven on a real Ledger" → in authorized **local** runs (#119), not on prod; blue is keyless on prod.
- "Gate p95 8 ms" → measured on the local stack during a live blue audit (#119); the gate itself is rules, not Droid.
- "OFF asks for every MCP call" → static binary read (provisional Finding) plus blue's 6/6 observation; not yet confirmed for green's tools.
- "Red learns between rounds" → red's playbook update is a deterministic fold of its own disclosed outcomes; the Droid model reads it as data. With live red on prod (`ln_f52a3df83c8d`) it re-weighted toward the scheme that paid (`threshold_split`); it invented no new schemes.
- Red's tool IDs → exact and checked against `list_tools()`, but derived from the tool list rather than pinned like green's and blue's.
- Earlier gemini cost → ~6.7k credits/turn per the PR #9 Finding.

**Do NOT say (and why)**
- "Three live Droid agents on prod": green and blue are `dry_run=true` (§4.11).
- "Droid decides allow/block" or "the gate is a Droid agent": `/gate` is rules plus an optional bounded advisory (`blue/gate/`).
- "The Droid model rewrites its own playbook" / "learns via an LLM reflection": all `/reflect` hooks are deterministic, with no model call.
- "CANCEL reasons reach the model": untested (open question).
- "We pinned the Droid CLI version": the installer hardcodes whatever it fetches, `droid-sdk[mcp]>=0.2.0` is a floor, and 0.5.0 is what resolved (Findings).
- "Hard credit cap": the guard counts after each turn and can overshoot by one turn in flight.
- Any per-agent credit figure for green or blue on prod: they spend nothing there.

---

## 9. Likely judge questions → answers

1. **Why Droid for non-coding agents?** It gives us sessions, streaming, MCP tool hosting, autonomy levels, a permission callback and usage metering in one runtime. We replace the coding prompt with a string `system_prompt` and turn off built-in skills (`droid_agent.py:624-633`).
2. **How do you keep the agent from using Droid's built-ins?** `disable_builtin_skills=True` and `restrict_tools` with exact `<agent>-ledger___<tool>` IDs. We learned the hard way that `list_tools()` gives `source=None` for in-process tools, so a source filter silently restricts nothing (Finding, PR #9). Strict agents fail the turn before streaming if the IDs drift.
3. **How do you get the tool_use_id when the handler doesn't receive it?** From the permission request (`McpToolAction.tool_use.id`) and the stream (`ToolCall`/`ToolCallDelta`). We register those, then link each execution by exact tool and canonical arguments (validated through the SDK's own pydantic model), approved entries first, with no "last seen" fallback (`invocation.py`). We confirmed the CLI sends only `_meta:{assemblySessionId, caller}` by reading the 0.249.0 binary.
4. **What happens with two identical calls in one turn?** Best-effort: oldest approved first, which is safe because identical approved calls are the same action. Strict: refused as `ambiguous`, both IDs closed `not_run`, nothing executes (D8).
5. **Why HIGH for red but OFF for green/blue?** Per the CLI's rule, a call asks for permission iff its impact level exceeds autonomy. Red's actions are what we want to test, so it never waits. Green moves money, so every call asks first and the handler gates it. Blue answers `PROCEED_ONCE`, but at OFF every call's ID is registered from its permission request before it runs, which strict identity needs (`invocation.py` docstring; #119 saw 6 calls with 6 requests).
6. **Why not `PROCEED_ALWAYS`?** It would turn off the per-call gate for the rest of the session (AGENTS.md §5). Only `PROCEED_ONCE` or `CANCEL`.
7. **Your tools are async, but the SDK stalls on await?** Yes, on 0.5.0 (Finding). The handler we give the SDK is sync and runs the coroutine to completion on a worker loop with its own HTTP client. Because that blocks the Session's loop, each turn gets its own thread and loop (#79), so `/health` and `/gate` stay responsive.
8. **What bounds a hung turn?** Stream 170 s; per-tool 160 s plus a turn-wide window and 2 s grace; turn-loop ceiling 180 s; battlefield waits 185 s and records `ok:false`; the episode continues (§4.7).
9. **How much does a turn cost?** Red on `gpt-5.4-mini`: ~2,635 credits, 11.2 s (Finding #118). Earlier on `gemini-3.8-flash`: ~6.7k (PR #9). A trivial one-tool turn was ~10k credits, mostly ~31k input tokens of tool/system context. Blue's authorized runs: 9,834 (6-call audit), 2,317 (interrupted run).
10. **What happened with gemini?** On prod it began stalling with nothing else changed: one `ToolSearch` after 80–140 s, no ledger calls, timeout at 170 s. Changing only the pinned model fixed it. It's recorded as a Finding (#118), and blue's local runs saw the same kind of stall (2 of 7 sessions).
11. **Is green actually gated by Droid permission today?** Not live. Green's live turn is hard-guarded pending an acceptance matrix (`green/SDK-ACCEPTANCE.md`). On prod green runs keyless, and battlefield gates its writes inline. Battlefield is the enforcement point either way; the handler is a pre-check (AGENTS.md §3.3).
12. **Can a model fake an idempotency key?** No. The ID comes from the SDK, not from tool arguments. Blue's tools reject extra `_tool_use_id`/`invocation` arguments at SDK validation (`blue/SDK-READINESS.md`). Strict mode refuses explicit IDs, and `LedgerClient` refuses keys that aren't `<id>`/`<id>:<n>` of the current call.
13. **How do you track spend?** `result.usage.factory_credits` → `turn.ended` → per-episode `MAX_CREDITS_PER_EPISODE` and per-lineage `max_credits` guards, plus `make prod-credits`.
14. **What would you ask Factory for?** The `tool_use_id` in the MCP tool handler (or `_meta`); awaiting in-process tools not stalling; `list_tools()` giving a source for SDK MCP tools; a pinnable installer. These are observations from our Findings, not complaints.

---

## 10. Numbers sheet

| Number | Meaning | Source | Date |
|---|---|---|---|
| $2,000 + credits + swag | Prize | Team research; confirm on Devpost | 2026-10-24 |
| 11.2 s / 2,635 credits | Red full attack turn, `gpt-5.4-mini` low, ep_568aef023d7c | Finding (Ad), #118 | 2026-10-24 ~21:05Z |
| 80–140 s, 170 s | gemini stall: `ToolSearch` delay, then `RunTimeoutError` (ep_1961aa7021ec, ep_9a15474fb8e7) | Finding #118 | 2026-10-24 ~20:30Z on |
| 20–38 s | Same gemini setup working at the 16:04Z deploy | Finding #118 | 2026-10-24 |
| ~6.7k credits; 14 s / 79 s | Early live red turns, gemini-3.8-flash low | Finding (Al), PR #9, DEVLOG 02:51Z | 2026-10-24 |
| ~10k credits, ~31k input tokens | Trivial one-tool turn | Finding (Al) | 2026-10-24 |
| ~60 models; 0.3 / 0.3 / 0.4 | `list_models` count; multipliers gemini-3.8-flash / gpt-5.4-mini / claude-haiku-4-5 | Finding (Al) | 2026-10-24 |
| ~34 | Built-ins exposed when `restrict_tools` silently fails | Finding (Al) | 2026-10-24 |
| 8 / 9 / 7 | Tool IDs red / green / blue | `red/tools.py`; `green/agent.py:21-31`; `blue/audit/agent.py:28-36` | main @ 119fbf6 |
| 0.5.0 / 1.30.0 | droid-sdk / mcp versions observed | Findings; `blue/SDK-READINESS.md` | 2026-10-24 |
| 0.248.0 / 0.249.0 | Droid CLI installed in deploy / binary read and used in blue runs | Findings | 2026-10-23/24 |
| 180 / 170 / 160 / 185 s | `TURN_TIMEOUT_SEC` / stream / tool cap / battlefield wait | `.env.example:22`; `droid_agent.py` | main |
| 90 s / 8 s / 15 s / 113 s | Escalation hold / gate timeout / HTTP timeout / ledger read timeout | `agentkit/agentkit/config.py`; `ledger_client.py:76-81` | main |
| 2 s / 2 s / 5 s | Tool grace / teardown & cancel join / end-of-turn flush | `droid_agent.py:81`; `sync.py`; #20 | main |
| ≤ 50 ms | Service-loop gap and `/health` latency during a 2 s tool freeze | #79 | 2026-10-24 |
| 9,834 credits; 6/6; p95 8.04 ms; max 56.6 ms; 1,817 samples | Blue real-Ledger happy path, ep_edd0d922b9a5 (local) | #119; `blue/SDK-READINESS.md` | 2026-10-24 |
| 2,317 credits; 18.4 s; max 69.19 ms / 275 samples | Blue interrupted path, `gpt-5.4-mini`, ep_677e52f4197f (local) | `blue/SDK-READINESS.md` | 2026-10-24 |
| 2 of 7; 1 of 5; 15–40 s | Blue gemini sessions stalled; non-stalled audits in budget; per tool round-trip | `blue/SDK-READINESS.md` | 2026-10-24 |
| 2,989 credits; 3.284 ms | Blue controlled authenticated probe | Finding (M) | 2026-10-24 |
| 1,850 credits; 3.437 ms; ~13 s | Blue portable authorized replay | `blue/SDK-READINESS.md`; devlog 17:22Z | 2026-10-24 |
| 5,825 / 3,308 credits | One-word probes (metering overhead) | `blue/SDK-READINESS.md` | 2026-10-24 |
| 16 sessions / 50,000 credits | Green acceptance proposal ceiling (not run) | `green/SDK-ACCEPTANCE.md` | 2026-10-24 |
| 375,000 | `MAX_CREDITS_PER_EPISODE` on prod (the `deploy/PROD-OPS.md:145` recommendation) | prod config | 2026-10-24 |
| 20,402 / 20,744 / 22,831 / 22,974 / 22,313 (~109k); ~2.7k/turn | Red credits per generation, live-red lineage `ln_f52a3df83c8d` (5 × 8 days = 40 turns) | lineage report (operator export, not committed) | 2026-10-24 |
| 26,230 / 24,449 | Red credits, live-red off / enforce recordings (10 turns each) | `docs/recordings/README.md` (#136) | 2026-10-24 |
| 136 | agentkit tests passed with droid-sdk installed | #84 | 2026-10-24 |
| 0:00–1:28 | Show beats | `frontend/docs/show-mode.md` | main |
