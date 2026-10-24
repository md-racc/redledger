# Blue SDK readiness checkpoint — 2026-10-24

Based on merged main `899c133`; controller and receipt/compatibility work already landed in
#19/#24. **Live audit is still disabled, with no environment bypass.** `/health` remains the
same shape: `ok=true` means the service responds; `droid_ok=false` truthfully reports the
unavailable live audit, including when SDK imports succeed. Health never runs diagnostics.

## Repeatable offline evidence

From the repository root:
```sh
cd blue
UV_NO_ENV_FILE=1 DRY_RUN=true FACTORY_API_KEY= uv run --extra dev --extra droid python -m audit.readiness
```

Observed Python 3.11.15, **droid-sdk 0.5.0 / mcp 1.30.0**:
- Real shared `_mcp_server()` and public SDK registry construction registered six local names:
  `benford_check`, `day_activity`, `freeze_vendor`, `post_report`, `raise_flag`, `vendor_dedupe`.
  All argument schemas matched; `finding_ids` is an array of strings. No invocation metadata
  parameter is exposed. Actual SDK handler validation rejected both `_tool_use_id` and
  `invocation` as forbidden extra arguments, before executing a Blue tool.
- A separate harmless tool exercised unchanged shared `_offload`: shared turn, fresh ledger
  and emitter were bound; Blue `SESSION` and `INVOCATION` were **not propagated**.
  Shared offload injected a fallback ID, unrelated to the diagnostic invocation marker.
  This ID is generated locally, **not authenticated SDK invocation metadata**.
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

1. Supply authenticated SDK invocation metadata out of band; never trust model arguments or
   replace a missing SDK ID with UUID4. Bind that same actual ID to narration, exact ledger
   mutations and receipts. The public registry handler tested here accepts argument mappings;
   no authenticated SDK-ID transport was established. Shared `_tool_use_id` injection is not
   such a transport and must not leak into Blue's public implementation arguments.
2. Preserve Blue session/invocation context with owner-loop execution of its asyncio lock and
   receipt/snapshot mutations. Copying contextvars alone into another event loop is insufficient.
   Retain same-day replay, partial/unknown receipts, cross-day suppression and no blind retries.
3. Make the bridge nonblocking for the service loop while retaining bounded deadlines, event
   draining and cancellation safety. Prove concurrent `/gate` stays within its 8-second budget.
   Do not fork shared lifecycle/offload inside Blue.
4. When humans authorize coordinated SDK validation, verify the exact six Blue IDs with
   `session.list_tools()` and restrict before the first live event. No actual Blue session IDs
   or live SDK behavior were verified here. Keep DRY_RUN key-free and Green-only audit-log reads;
   no scoreboard, event-stream, attack or other-agent internals may enter the audit.

Proposed **Ad-owned** `contracts/CHANGELOG.md` Findings entry (not written on this branch):
> 2026-10-24: `cd blue && UV_NO_ENV_FILE=1 DRY_RUN=true FACTORY_API_KEY= uv run --extra dev --extra droid python -m audit.readiness` with droid-sdk 0.5.0/mcp 1.30.0 registered six local Blue tools and rejected metadata extras; unchanged shared offload lost Blue context, injected a fallback ID and blocked the owner-loop heartbeat; no session IDs, authenticated invocation binding or live readiness proven.
