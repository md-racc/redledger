# Current Blue controller integration handoff

Controller and receipt/compatibility work are merged via #19/#24. This checkpoint includes
main `78a3b25` (#34 bridge) and `f349b47` (#33 contract) via plain merge; legacy worktrees remain untouched.
See [SDK-READINESS.md](SDK-READINESS.md) for the offline evidence and remaining Ad handoff.

## Behavior and deliberate costs

- Gate uses only supplied context, finite `Decimal` amounts and typed effects; never hit counts,
  Droid or ledger reads. Verdicts are identical in off/shadow/enforce; battlefield alone enforces.
- Approve/pay blocks paid invoice identity duplicates (same vendor/number, or one-letter suffix,
  same PO and at most $0.05 difference), PO vendor mismatch or >10% overage, relevant high holds,
  frozen vendors, and explicitly missing HR/inactive employees. Reject is safe; matching runs PO
  controls only; valid individual GL entries need not balance themselves.
- New vendor age 0–6, explicit empty paid history, no associated PO, and exposure >=95% of the
  approval threshold blocks. **Legitimate expedited onboarding with exactly these facts also
  blocks.** This is an authorization tradeoff, not proof of a fictitious vendor; obtain a PO or
  independent onboarding verification. Newness/threshold/history drift alone remain notes.
- Actual destination changes overlapping exposure and account collisions require verification,
  not fraud allegations. Benign recent bank rotations before material payment also escalate.
  Recurring equal amounts are not duplicates; drift needs a stable baseline and is diagnostic.
  Missing/malformed critical evidence and applicable control failures escalate verification unavailable.
- Advisory supports only existing Gemini/Anthropic/OpenAI settings: derived facts only, 8 active
  calls, no retries, 2.4-second total deadline, small response cap, keys in headers, sanitized logs.
  Three validated neutral suggestions may appear in operational logs; they never alter the
  contractual verdict/reason/confidence/rule IDs. DRY_RUN and the app's dry-run setting disable calls.

## Audit bounds and receipts

One shared lifecycle (`DroidAgent.run_turn`), one Blue lock for `/audit` and `/turn` (overlap 409);
gate is unlocked. Snapshot reads use only public LedgerClient methods: vendors, employees,
invoices, POs, today's payments, vendor changes, flags and allowlisted Green activity.
At most four concurrent reads, 10 seconds/read, 25 seconds collection, 2,000 examined rows/dataset,
20 prioritized findings; dropped/invalid/truncated/unavailable coverage is explicit. Public API
responses are decoded upstream **before** this row cap; HTTP response bytes and upstream
completeness are not guaranteed bounded. Raw names, invoice numbers, bank details, actors,
provenance, free prose, nested logs and input instructions never enter model/tool projections.
Today's payment references keep earlier-received invoices in audit scope. Audited unbacked
exposure cannot count as its own independent paid history after Green pays it.

Tools: `day_activity()`, `vendor_dedupe()`, `benford_check()`, `raise_flag(finding_id)`,
`freeze_vendor(vendor_id, finding_ids)`, `post_report()`. Service fixes entity/severity/reason.
Freeze requires two independent families, at least one substantive integrity/identity fact, and a
fresh unchanged vendor read; newness/threshold/splitting/name/Benford hints never suffice alone.
Four freeze writes/turn maximum. Dry-run executes these same guarded tools and report path,
binding one UUID4 to each tool event and its exact mutation. No flag-every-new-vendor path.

Default whole-turn budget 170 seconds (180 configured); writes 4 seconds, with reporting reserve.
Reports have Reviewed/Flagged/Needs a human tomorrow, <200 words, gaps and failed/unknown effects.
Counts mean confirmed receipts, not successful model completion. Same episode/day replays the
completed response, including partial failures. Confirmed flags are suppressed across days;
unknown commits are retained and never blindly retried on later days. Exact effect receipts are
available on `AuditAgent.receipts`; no automatic reconciliation is claimed.

All state is **single-process, in-memory**, not distributed or restart-safe exactly-once.
Gate namespaces episode/key, shields shared work from caller cancellation, retains the complete
first response for 120 seconds despite richer later context and >5,000 entries. Sharded unchanged
VerdictCache storage avoids its destructive capacity clear. At 100,000 retained entries or 256
in-flight keys, new admissions receive 503 rather than premature eviction. Audit retains up to
512 day-results/receipt sets, then refuses new admission; humans must reconcile before restart.

## Shared compatibility and required follow-ups

Merged and validated shared baseline is `78a3b25`. Already resolved upstream:
- Root uv workspace removal (`fff29f0`) restores normal per-service sync.
- Explicit attack linkage/scoring fixes are merged (#17/#18); the prior heuristic-only
  scoring handoff is superseded. Red audit rows are hidden server-side (#28); Blue still
  restricts its own audit-log query to Green activity.
- `AGENT_TOKEN` wins over legacy `INTERNAL_TOKEN`; `AgentSettings.internal_token` remains the
  resolved agent credential. Blue uses shared constant-time bearer auth, not `OPERATOR_TOKEN`.
- Shared EventEmitter now supplies UUID4 `X-Tool-Use-Id` on `/events` batches. Shared first-session
  restrictions use `<server>___<tool>` IDs, with prefix-based discovery; they are no longer None.
  Shared synchronous MCP offload creates a fresh LedgerClient, copies Blue contextvars and binds
  shared ctx/Invocation in its private worker loop. No internal ID keyword is injected now.
  The registry can correlate SDK permission/stream metadata; the offline probe has no such
  registration, so its shared invocation is local/unverified. These are not proof of Blue readiness.
- Contract #33 binds each key to its first action tuple (posted fields for `gl.post`);
  battlefield returns 409 for different-action reuse. Richer context alone is not another action.
  Shared multi-write keys use the invocation ID first, then `<id>:<n>`. Blue gate compatibility
  is an independent review track, not changed or certified by this readiness checkpoint.

Still required:
1. Offline SDK 0.5.0/MCP 1.30.0 checks match all six schemas and reject metadata extras.
   Shared offload now copies Blue SESSION/INVOCATION, but runs off the owner loop and still
   blocks its heartbeat. Blue lock/client/receipt safety and integration with shared verified
   Invocation identity remain unproven. Shared/Blue narration ownership also needs reconciliation.
   Exact Blue session IDs remain unverified; the copied synthetic marker is not authenticated.
   Live audit collects bounded facts then returns unsuccessful readiness, with **no stream or
   write**, regardless of environment settings. Health reports `droid_ok=false` without probing.
   Keep the guard until Ad resolves the shared bridge and coordinated validation establishes
   all prerequisites in [SDK-READINESS.md](SDK-READINESS.md). No lifecycle fork or guessed IDs.
2. Green's mirror needs battlefield-equivalent context before the first gate request. The first
   response wins for 120 seconds; a richer later request cannot repair incomplete mirror data.
   Gate lacks pending siblings, so established-vendor splitting is detected post-hoc, not prevented
   before pay. Paid-history context is backend-windowed; older duplicates can be missed.
3. Human owners must perform future E2E/SDK validation when authorized. No Docker, seeded stack,
   live provider/model call, deployment, push or PR was performed in this refresh.
   The orchestrator plain-merged upstream before the readiness refresh; no author integration merge occurred.
   `REVIEW-STACK.md` is historical publication context, not the current SDK-readiness plan.

Collection lives in `audit/snapshot.py`; `audit/evidence.py` derives findings in a worker thread.
This split is structural: normalization and finding controls match the `78eb287` source; bounded
lead counting occurs before derivation and remains independent of mutation authority.

## Current protocol and validation

Each incremental branch adds exactly one new one-line M `devlog/` fragment. `DEVLOG.md` is
frozen and unchanged. Ad alone integrates after green CI and a PR-steward READY assessment
pinned to the head SHA; owner routing is not an approval gate. Published dependent PRs must say
`stacked on #N`; Ad integrates bottom-up and may plain-merge main to resync without force/rewrite.
No author merges; this checkpoint remains local-only.

Invariant 11: the only audit-log read is `list_audit_log(agent="green", day=day)` through
LedgerClient. No event/scoreboard/attack reads, raw provenance or raw battlefield HTTP are used.
The EventEmitter path emits only; raw source prose stays outside model/tool projections.

## Validation on the current baseline

Python 3.11.15: **171 passed** (151 merged baseline + 20 readiness cases, no skips).
Readiness tests cover absent/installed SDK states, schemas/spoof refusal, copied Blue context
versus local/unverified shared invocation, owner-loop blocking, truthful
health, sanitized output and the unchanged no-stream/no-write live guard.
All current checkpoint Blue ruff checks/format checks pass. Repository Python ruff checks and
format checks pass; the frontend dependency baseline is recorded below.

Normal per-service setup and tests work, with no root-workspace workaround:
```sh
cd blue
UV_NO_ENV_FILE=1 uv sync --python 3.11 --extra dev
UV_NO_ENV_FILE=1 uv run pytest -q
```
Test settings disable env-file loading and use distinct dummy agent/operator/legacy tokens.
Generated lock/log files are ignored and uncommitted; no dependencies or service env vars added.
From the repository root, `make OPERATOR_TOKEN=validation TOKEN=validation lint test-blue`
passes Python checks but stops at the existing missing frontend `tsc`; no frontend install or
fix was attempted. Independent `make OPERATOR_TOKEN=validation TOKEN=validation test-blue`
passes all 171 tests normally. Validation used `UV_NO_ENV_FILE=1` and kept ruff cache under Blue.

Prior `9736639`-stack local benchmark (not rerun on this checkpoint), 1,000 uncached calls/case;
median/p95/max milliseconds:
clean **0.0652/0.0720/0.5300**, ghost **0.0705/0.0760/0.1115**,
new-vendor split **0.0705/0.0752/0.1071**. Mocked hung-provider complete decision:
**2,401.95 ms**, deterministic escalate, zero live calls. These are preserved prior-stack local measurements,
not HTTP/network/E2E or production latency guarantees.
