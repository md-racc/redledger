# Blue SDK readiness checkpoint — 2026-10-24

Invocation/receipt integration refreshed against main `c28e58d` (#64 CRS, #63 runtime, #61 docs);
controller and receipt/compatibility work landed in #19/#24. **Live audit remains disabled,
with no environment bypass.** `/health` retains its shape: `ok=true` means the service responds;
`droid_ok=false` truthfully reports the
unavailable live audit, including when SDK imports succeed. Health never runs diagnostics.

## Strict-policy opt-in prerequisite (#84)

Blue explicitly selects `autonomy="off"` and `identity="strict"` and answers permission
requests only with `PROCEED_ONCE` (lazy SDK import). The immutable seven-ID allowlist below,
including CRS, seeds a fresh per-agent list before the first SessionConfig. Blue overrides
only the expected IDs; shared `_learn_tool_ids` validates every strict-live turn before
streaming and rejects missing/extra/lookalike IDs or listing failures.

`tests/test_strict_adapter.py` exercises that policy with controlled module/session doubles
and synthetic ledger context, not an authenticated SDK or provider. This is not a live
adapter: the real `_droid_turn` hard stop and false readiness/health remain unchanged.
Owner-loop/narration work in #85 is separate; no authenticated invocation proof or guard lift
is claimed here.

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
- Key-free deterministic dispatch still uses fresh UUID4 IDs for its own safe narration pair,
  writes and receipts. The full Blue suite continues to cover same-day replay and cross-day
  suppression/unknown handling.

Controlled registrations demonstrate **API integration only**, not authenticated live identity.
No Session, `session.list_tools()`, CLI, listener, model/provider, external HTTP, production or CRS
call was run for this integration. The shared bridge is still synchronous/blocking on a separate
worker loop. Uncontended unit-test locks and mocked HTTP do not qualify owner-loop safety.
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
2. Prove owner-loop safety for Blue's asyncio lock, private worker client and receipt/snapshot
   access. Copied session/invocation objects do not make cross-loop use safe by themselves.
   Retain same-day replay, partial/unknown receipts, cross-day suppression and no blind retries.
3. Make the bridge nonblocking for the service loop while retaining bounded deadlines, event
   draining and cancellation safety. Prove concurrent `/gate` stays within its 8-second budget.
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
