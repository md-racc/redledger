# Blue SDK readiness checkpoint — 2026-10-24

Refreshed after plain-merging main `78a3b25` (#34 shared bridge) and `f349b47` (#33 contract);
controller and receipt/compatibility work landed in #19/#24. **Live audit remains disabled,
with no environment bypass.** `/health` retains its shape: `ok=true` means the service responds;
`droid_ok=false` truthfully reports the
unavailable live audit, including when SDK imports succeed. Health never runs diagnostics.

## Repeatable offline evidence

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

1. Integrate Blue's private invocation handling with the new shared Invocation/Registry API.
   Shared `verified` accepts permission/stream/mcp_meta sources only, not explicit/local IDs.
   This probe exercises the unverified local fallback, not a genuine SDK registration. Do not
   treat the copied private Blue marker as identity, trust model args, or accept generated UUIDs
   for live SDK writes. Prove one actual ID binds exact writes and receipts; reconcile narration
   ownership because shared offload now emits a pair and Blue's private wrapper also emits one.
2. Prove owner-loop safety for Blue's asyncio lock, private worker client and receipt/snapshot
   access. Copied session/invocation objects do not make cross-loop use safe by themselves.
   Retain same-day replay, partial/unknown receipts, cross-day suppression and no blind retries.
3. Make the bridge nonblocking for the service loop while retaining bounded deadlines, event
   draining and cancellation safety. Prove concurrent `/gate` stays within its 8-second budget.
   Do not fork shared lifecycle/offload inside Blue.
4. When humans authorize coordinated SDK validation, verify the exact six Blue IDs with
   `session.list_tools()` and restrict before the first live event. No actual Blue session IDs
   or live SDK behavior were verified here. Keep DRY_RUN key-free and Green-only audit-log reads;
   no scoreboard, event-stream, attack or other-agent internals may enter the audit.

Ad already recorded SDK/CLI metadata and permission findings in
[`contracts/CHANGELOG.md`](../contracts/CHANGELOG.md); the earlier proposed context-loss entry
is superseded, not requested again. No shared file was changed here. Contract #33 binds a key
to its first action (GL posted fields for `gl.post`), with battlefield 409 on different-action
reuse; shared LedgerClient uses the invocation ID for write one and `<id>:<n>` thereafter.
This readiness checkpoint does not claim independent validation of Blue gate compatibility.
