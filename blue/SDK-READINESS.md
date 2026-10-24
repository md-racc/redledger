# Blue SDK readiness checkpoint — 2026-10-24

Invocation/receipt integration refreshed against main `c28e58d` (#64 CRS, #63 runtime, #61 docs);
controller and receipt/compatibility work landed in #19/#24. **Live audit remains disabled,
with no environment bypass.** `/health` retains its shape: `ok=true` means the service responds;
`droid_ok=false` truthfully reports the
unavailable live audit, including when SDK imports succeed. Health never runs diagnostics.

## Shared adapter / D14 prerequisite checkpoint after #79

Blue delegates deterministic narration to `ledger_tool(redact=...)`, retaining the outer
verified, one-time invocation guard. Live outcomes use constant shared summaries; keyless
summaries use the first 300 characters of the already sanitized tool result. Argument binding
rejects model metadata before adding the private deterministic UUID. Nonconfirmed results use
a sanitized internal exception so the shared narrator emits `ok=false`; callers still receive
the original sanitized JSON result. There is no Blue-owned event pair.

Audit and tool locks use `agentkit.sync.TurnLock`. The fake polls its release flag with a
bounded wait instead of awaiting an Event owned by another loop. `tests/test_shared_adapter.py`
opts canned turns into the shared turn loop per instance and checks contended lock handoff,
cancellation, UUID/receipt identity, replay, unknown-write retention, context restoration, and
all three overlapping `/audit`/`/turn` combinations with the existing 409 and <50 ms gate
assertions unchanged. All seven tool names/signatures and the original 27 invocation tests remain.

`UV_OFFLINE=1 UV_NO_SYNC=1 UV_NO_ENV_FILE=1 make lint test-blue TOKEN=test-operator` passed:
**284 tests**. A full-suite test-only `AuditAgent.turn_loop_dry_run=True` fixture override also
passed **284 tests**. Shared defaults, autonomy, live guards and readiness were not changed.
These are in-memory/mocked-HTTP tests, not Docker, authenticated SDK, real ledger/provider or
live gate-latency proof. Strict identity subsequently landed in #84/#90; no live enablement is claimed.

## Invocation/receipt integration covered offline — not live qualification

`tests/test_shared_invocation.py` uses the real shared `Invocation`, `bind_invocation`,
`InvocationRegistry`, `_offload` and LedgerClient, controlled registrations, mocked HTTP and an
in-memory EventEmitter sink (no sender/pump). No optional SDK is needed:

```sh
cd blue
UV_OFFLINE=1 UV_NO_ENV_FILE=1 uv sync --extra dev --python 3.11
UV_NO_SYNC=1 UV_NO_ENV_FILE=1 uv run pytest -q tests/test_shared_invocation.py
cd ..
UV_OFFLINE=1 UV_NO_SYNC=1 UV_NO_ENV_FILE=1 make lint test-blue TOKEN=test-operator
```

Covered integration behavior:
- The six original tools and CRS audit-to-gate flow require verified shared identity before
  provider/read/write work. Only `permission`, `stream` and `mcp_meta` sources qualify.
  Private-only markers, local/explicit fallbacks, wrong tools and reused invocations are refused.
  Invocation metadata remains absent from model-visible signatures and is not accepted as args.
- For flag, freeze and report writes, the controlled SDK-style ID equals the single shared event
  pair's ID, the exact first-write `X-Tool-Use-Id` and the retained `ConfirmedEffect.tool_use_id`.
  Shared offload alone narrates; Blue records only a bounded, service-defined completed/not-confirmed
  outcome, never raw provider responses, exceptions or source prose.
- JSON failure and shared result failure agree for rejected, malformed and unknown write receipts.
  Unknown receipts are retained without blind retries. Body errors, write cancellation/deadlines
  and cancellation waiting for the lock restore private invocation context and retain receipts;
  direct binding tests also restore the enclosing shared context.
- Key-free deterministic dispatch still uses fresh UUID4 IDs for the shared decorator's pair,
  writes and receipts. The full Blue suite continues to cover same-day replay and cross-day
  suppression/unknown handling.

Controlled registrations demonstrate **API integration only**, not authenticated live identity.
No Session, `session.list_tools()`, CLI, listener, model/provider, external HTTP, production or CRS
call was run for this integration. Shared offload still blocks its calling turn loop while a
private worker runs; #79 isolates that turn loop from the service loop. The controlled lock and
fake-client tests above do not qualify actual SDK/client/event-pump ownership or live safety.
Neither `AuditAgent._droid_turn` nor readiness/health guards were changed: readiness is always false.

## Session tool-ID discovery

A separate list-only probe on CRS PR #64, with droid-sdk 0.5.0 / mcp 1.30.0, opened a real
Session and matched all seven IDs below. No stream, agent tool, ledger write or CRS request
ran. This settles the IDs for that tool set, not SDK invocation delivery or live audit safety.
PR #64 is incorporated. The CLI must already be authenticated. No `.env` is loaded and no
credential values or raw SDK errors are printed:

```sh
cd blue
UV_OFFLINE=1 UV_NO_ENV_FILE=1 uv run --extra dev --extra droid python - <<'PY'
import asyncio, contextlib, io, json, tempfile
from pathlib import Path
from droid_sdk import Autonomy, InteractionHandlers, Session, SessionConfig, ToolConfirmationOutcome
from audit.readiness import _offline_agent

EXPECTED = {
    "blue-ledger___benford_check",
    "blue-ledger___crs_identity_check",
    "blue-ledger___day_activity",
    "blue-ledger___freeze_vendor",
    "blue-ledger___post_report",
    "blue-ledger___raise_flag",
    "blue-ledger___vendor_dedupe",
}

async def cancel(request):
    return request.respond(ToolConfirmationOutcome.CANCEL)

async def probe():
    try:
        server = _offline_agent()._mcp_server()
        config = SessionConfig(autonomy=Autonomy.OFF, disable_builtin_skills=True,
            system_prompt="Tool registry discovery only.", mcp_servers=[server], restrict_tools=EXPECTED)
        with tempfile.TemporaryDirectory(prefix="blue-sdk-discovery-") as cwd:
            async with asyncio.timeout(25):
                async with Session(cwd=Path(cwd), config=config,
                        interactions=InteractionHandlers(on_permission=cancel)) as session:
                    ids = sorted(t.id for t in await session.list_tools() if t.id.startswith("blue-ledger___"))
                    return {"matched": set(ids) == EXPECTED, "tool_ids": ids}
    except Exception as exc:
        return {"matched": False, "error_type": type(exc).__name__}

with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    result = asyncio.run(probe())
print(json.dumps(result, sort_keys=True))
raise SystemExit(0 if result["matched"] else 2)
PY
```

Expected: `matched:true` and exactly the pinned seven IDs. The offline readiness helper still
returns `ready:false` because it does not run this Session probe or qualify the remaining blockers.

## Earlier optional-SDK diagnostic evidence (not rerun for this integration)

From the repository root:
```sh
cd blue
UV_NO_ENV_FILE=1 UV_OFFLINE=1 DRY_RUN=true FACTORY_API_KEY= uv run --extra dev --extra droid python -m audit.readiness
```

Dependencies were already cached; `UV_OFFLINE=1` prevents dependency-resolution network calls.
Observed Python 3.11.15, **droid-sdk 0.5.0 / mcp 1.30.0**:
- Real shared `_mcp_server()` and public SDK registry construction registered six local names:
  `benford_check`, `day_activity`, `freeze_vendor`, `post_report`, `raise_flag`, `vendor_dedupe`.
  All argument schemas matched; `finding_ids` is an array of strings. No invocation metadata
  parameter is exposed. Actual SDK handler validation rejected both `_tool_use_id` and
  `invocation` as forbidden extra arguments, before executing a Blue tool.
- Three repeated probes of unchanged shared `_offload` bound shared turn, fresh ledger and
  emitter, and now **propagate Blue SESSION and INVOCATION** through copied contextvars.
  `blue_tool_lock_shared=true` but `worker_on_owner_loop=false`: propagation is not proof of
  cross-loop lock/client/receipt safety. The harmless probe never acquires Blue's lock or writes.
- `ctx.invocation()` is bound with `source=local`, `verified=false`, and an ID distinct from
  the copied synthetic Blue invocation marker. No `_tool_use_id` keyword is injected anymore.
  The local fallback is **not authenticated SDK metadata**; copying our marker cannot verify it.
  Shared narration records one pair in an in-memory sink, with no EventEmitter or outbound event.
- During a bounded 50 ms worker-loop await, the owner-loop heartbeat scheduled for 10 ms did
  not run until the synchronous bridge returned. This demonstrates loop blocking, not a
  production gate latency benchmark.
- Output: `ready=false`, `session_tool_ids_verified=false`,
  `authenticated_invocation_verified=false`. Local registration is **not** `session.list_tools()`.
  No Session, stream, CLI subprocess, listener, ledger/event request or provider/model call ran.
  Dummy settings disable `.env` loading and override ambient credentials/URLs.

Missing optional SDK/MCP imports produce `sdk_unavailable`, not an import-time failure.
Exit zero means the diagnostic completed, **not readiness**. Normal `--extra dev` tests use
unit registry doubles and exercise the real shared bridge; no skipped SDK-dependent tests.
The readiness helper always returns false; none of these offline observations can unlock it.

## Ad handoff: shared bridge prerequisites, not a Blue-local adapter

1. Blue's private invocation/write/narration integration is now covered by the offline tests above.
   The earlier diagnostic still exercises only the unverified local fallback. Under authorized live
   validation, prove an actual SDK-reported ID reaches the registry in time, binds the exact write
   and receipt, and produces exactly one shared pair. Copied private markers, model args and
   generated/explicit IDs cannot authorize live tools. Installing SDK does not settle this.
2. TurnLock contention and canned turn-loop ownership are now covered offline above. Still
   qualify actual SDK, worker client, event pump and receipt/snapshot access under cancellation.
   Retain same-day replay, partial/unknown receipts, cross-day suppression and no blind retries.
3. #79 supplies service/turn-loop isolation. Qualify its bounded deadlines, event draining and
   cancellation with actual SDK traffic; prove concurrent `/gate` stays within its 8-second budget.
   Do not fork shared lifecycle/offload inside Blue.
4. The list-only probe above observed the exact seven IDs with CRS present; retain that
   restriction before the first live event and revalidate after tool/SDK changes.
   Actual streaming/invocation behavior remains unqualified. Keep DRY_RUN key-free and Green-only audit-log reads;
   no scoreboard, event-stream, attack or other-agent internals may enter the audit.

Ad already recorded SDK/CLI metadata and permission findings in
[`contracts/CHANGELOG.md`](../contracts/CHANGELOG.md); the earlier proposed context-loss entry
is superseded, not requested again. No shared file was changed here. Contract #33 binds a key
to its first action (GL posted fields for `gl.post`), with battlefield 409 on different-action
reuse; shared LedgerClient uses the invocation ID for write one and `<id>:<n>` thereafter.
This readiness checkpoint does not claim independent validation of Blue gate compatibility.

## Strict-policy opt-in prerequisite (#84)

Blue explicitly selects `autonomy="off"` and `identity="strict"` and answers permission
requests only with `PROCEED_ONCE` (lazy SDK import). The immutable seven-ID allowlist above,
including CRS, seeds a fresh per-agent list before the first SessionConfig. Blue overrides
only the expected IDs; shared `_learn_tool_ids` validates every strict-live turn before
streaming and rejects missing/extra/lookalike IDs or listing failures.

`tests/test_strict_adapter.py` exercises that policy with controlled module/session doubles
and synthetic ledger context, not an authenticated SDK or provider. This is not a live
adapter: the real `_droid_turn` hard stop and false readiness/health remain unchanged.
Shared owner-loop/narration code from #85 is also merged. Runtime qualification remains separate.

### Controlled authenticated SDK checkpoint

A local combined snapshot (`7889fba`, #85 + strict policy, shared #84) passed **299 tests**.
A bounded real CLI-authenticated SDK turn with `gemini-3.8-flash` / low reasoning then
observed one OFF permission callback, one `PROCEED_ONCE` approval, one verified invocation
whose ID matched the intercepted report header and confirmed receipt, and exactly one
shared narration pair. Session discovery matched all seven pinned IDs. A concurrent local
ASGI `/gate` returned allow in **3.284 ms** during the report's two-second intercepted HTTP
delay. Reported usage was **2,989 Factory credits**. An earlier attempt was inconclusive;
successful model discovery after removing an empty `FACTORY_API_KEY` justified the retry.

`tests/sdk_authenticated_probe.py` preserves a portable, explicitly opt-in form of that
temporary probe; it is not collected by pytest. With the merged prerequisites, the existing
CLI authenticated and the `dev` + `droid` extras installed:

```sh
cd blue
UV_NO_ENV_FILE=1 uv run --no-sync python tests/sdk_authenticated_probe.py --allow-model-call
```

An earlier portable replay matched all Session IDs but ended without a permission callback,
tool event, write or reported usage. That run was inconclusive; its cause remains unknown.
The authorized result below is a separate attempt, not a diagnosis of that earlier failure.

### Portable probe diagnostics, not another live result

The probe now preserves fixed failure codes and completed stages, including a shared-SDK
failure before the audit wrapper replaces its summary. Raw model text and exception prose
are not printed. Missing receipts are inconclusive rather than an `IndexError`; qualification
requires exactly one approved call, intercepted report write, successful narration pair and
confirmed report receipt with matching verified identity. Duplicate/unknown evidence fails.
Concurrent gate qualification also requires HTTP 200, allow, overlap, finite latency below
8 seconds, reported finite usage and no unfinished turn cleanup.

The JSON includes `failure_codes`, `controlled_probe_passed` and `ready:false`. Exit 0 means
only that the isolated, intercepted probe passed; exit 2 means incomplete or failed evidence.
The earlier replay's cause is still unknown. Offline regression tests are not a reproduction
of that authenticated run, and do not authorize another model call.

This command is billable. It uses an empty temporary cwd, disables dotenv, clears sponsor
credentials in its child process, forbids CRS construction and intercepts all Ledger HTTP.
Only its test subclass bypasses the guard. This proves controlled SDK identity delivery,
not a real Ledger commit, production gate latency, CRS access or the three-day shadow
checkpoint. The real live hard stop and false readiness/health remain unchanged.

See [ACCEPTANCE.md](ACCEPTANCE.md) for ownership and the remaining runtime-dependent checks.

### Authorized portable replay, 2026-10-24

At source `f8b27829a7bb61b13e8b06b83f15c41c9f1170c8`, the user approved exactly one
session capped at 60 seconds. The portable command above, additionally using `UV_OFFLINE=1`,
returned exit 0 in about 13 seconds. There was no retry. Versions were CLI `0.249.0`,
Python `3.11.15`, SDK `0.5.0` and MCP `1.30.0`; model was `gemini-3.8-flash`, low reasoning.

Sanitized qualification fields from that run:

```json
{
  "controlled_probe_passed": true,
  "failure_codes": [],
  "ready": false,
  "turn_ok": true,
  "error_type": null,
  "cleanup_pending": false,
  "autonomy": "off",
  "identity": "strict",
  "factory_credits": 1850.0,
  "permission_count": 1,
  "intercepted_report_writes": 1,
  "tool_calls": 1,
  "tool_results": 1,
  "authenticated_id_binding": true,
  "invocation_source": "stream",
  "gate_http_status": 200,
  "gate_verdict": "allow",
  "gate_ms": 3.437,
  "gate_during_intercepted_write": true,
  "runtime_guard_changed": false,
  "real_ledger_or_crs_access": false,
  "stages": [
    "shared_sdk_entry",
    "synthetic_prompt_ready",
    "checking_actual_session_ids",
    "actual_session_ids_matched",
    "permission_callback",
    "turn_returned"
  ]
}
```

This qualifies that single controlled, intercepted run, including the confirmed report receipt
and exact shared event pair. The gate timing is local ASGI overlap with a two-second intercepted
write, not a real Ledger or production-latency result. All runtime guards and false readiness
remain unchanged. Real-Ledger, interrupted/unknown-receipt, CRS, #83 seeded and all-real shadow
acceptance are still outstanding; the one-session spending authorization is exhausted.

## Real-Ledger acceptance harness and authorized live results, 2026-10-24

`tests/sdk_real_ledger_acceptance.py` (not pytest-collected; requires `--allow-model-call`)
serves the real `AuditAgent` through a test-only `_droid_turn` subclass on `:8013`, points a
local battlefield (Postgres, mock red/green) at it, and runs a full 1-day enforce episode.
It verifies, with operator reads only: permission requests at `Autonomy.OFF` for the pinned
seven tool IDs; exactly one `agent.tool_call`/`agent.tool_result` pair per permission ID;
every blue `audit_log` execution (sub-300) bound to a permission ID with no duplicate
`(action, tool_use_id)` commits; the report committed and fetchable; receipt states per write;
a same-key replay refused (4xx) with no second execution; and `/gate` latency sampled every
50 ms during the live audit turn. The interrupted scenario SIGKILLs battlefield as the first
write of any kind (flag, freeze, or report) is sent, restarts it, and requires an `unknown`
receipt, zero-or-one execution for that key, and a refused replay. Output is a sanitized JSON
with fixed failure codes; `ready:false`, `runtime_guard_changed:false` and
`crs_or_provider_access:false` are constant. No raw model text or exception prose is printed.
CRS credentials are empty; CRS construction is monkeypatched to raise (no provider access).

Eight billable sessions ran against the local stack under the ad-authorized budget
(own dev key, local only), each diagnosed before any retry:

| # | Scenario | Result |
|---|----------|--------|
| 1 | happy | Deadline at 140 s (`TURN_TIMEOUT_SEC=150` too tight); harness timeouts raised |
| 2 | happy | **Full evidence captured** (below); original verification had two false positives, since corrected |
| 3 | happy | SDK stall: zero stream events for the whole 170 s budget |
| 4 | happy | 4 reads, deadline before any write |
| 5 | interrupted | SDK stall again; kill never triggered |
| 6 | interrupted | Kill triggered on first write; a harness bug (`lsof tcp:8000` without `-sTCP:LISTEN`) matched the harness's own client connections and self-killed. Fixed; reaper now LISTEN-scoped and self-excluding |
| 7 | interrupted | 4 reads, deadline before any write |
| 8 | interrupted | 3 reads, deadline before any write |

### Happy path: proven live (session 2, `ep_edd0d922b9a5`, 9,834 Factory credits)

- 6 tool calls, 6 permission requests, exact one-to-one event pairs, all SDK-reported IDs.
- Real Ledger commits: `flags.raise` 201 (`tc-wc3db0ypxqj`) and `reports.post` 201
  (`tc-wwblp0bn3q`); receipts `flag:confirmed`, `report:confirmed`; report fetchable.
- Same-key replay of the report write returned an **audited 409** (the rejection itself writes
  an audit row sharing the key, with no sub-300 execution) and no second commit — exactly one
  execution per `(action, tool_use_id)`; duplicate counting must consider sub-300 rows only.
- `/gate` under the live audit: 1,817 samples, max **56.6 ms**, p95 8.04 ms, zero errors.
- Turn summary: "Partial audit: 1 confirmed flags, 0 confirmed freezes; report confirmed;
  0 unknown writes. crs_identity_check: verification unavailable" — the sole deficit is the
  deliberately credential-less CRS check (separate acceptance), so acceptance keys on
  turn-returned + zero unknown/failed writes + confirmed report, not raw `turn.ok`.

### Interrupted path: not captured live; offline coverage stands

Three attempts never reached a write inside the audit budget; the one triggered kill was lost
to the harness bug above. The receipt semantics it would prove (cancel/timeout/5xx ->
`unknown` + "do not blindly retry", no duplicate execution, audited replay refusal) remain
covered by the offline invocation/receipt suite (`tests/test_shared_invocation.py` and
friends). A live interrupted capture is still outstanding.

### Readiness-relevant findings for M/Ad

1. **Audit budget cap vs model latency.** `audit/agent.py` computes
   `budget = min(170.0, turn_timeout_sec - 10)`, so raising `TURN_TIMEOUT_SEC` cannot extend an
   audit. At observed `gemini-3.8-flash` latency (~15-40 s per tool round-trip), the 6-7 call
   audit finished in time in only 1 of 5 non-stalled sessions; the rest ended truthfully with
   "Audit deadline reached" (partial audit, gaps recorded, no blind writes — the designed safe
   degradation). Whether to raise the cap, reorder writes earlier, or accept deadline-partial
   audits is a product decision; the env knob alone does nothing today.
2. **Intermittent SDK startup stalls.** 2 of 7 sessions produced zero stream events (not even
   thinking deltas) for the entire 170 s budget. Minimal probes (bare session, and session with
   an in-process MCP server + `restrict_tools`) both completed in under 7 s, so it is not
   account-, model- or MCP-attach-wide; the trigger under the full 7-tool audit configuration
   is undiagnosed. The bounded budget converts a stall into a truthful partial audit, not a hang.
3. Reported per-turn `factory_credits` varies widely (9,834 for a 6-call audit; 5,825 and 3,308
   for one-word probes), suggesting a large fixed session overhead in metering; worth knowing
   for budget planning.

All runtime guards, the live `_droid_turn` hard stop outside the test subclass, and
readiness/health remain unchanged: `ready:false`. CRS fixture acceptance and the interrupted
live capture are still outstanding.
