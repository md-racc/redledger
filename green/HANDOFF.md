# Green AP protocol checkpoint

Prepared for Dev Ad and the parallel Blue session, 2026-10-23. This is a review
proposal, not a merged contract or an implemented HTTP endpoint. No cross-owner
implementation is included in this Green branch.

## Delivery boundary

The first milestone is the existing-contract, keyless AP clerk foundation.
Live Droid execution must remain disabled until the dependencies below land and
SDK behavior is measured. In particular, Green must not send an incomplete
permission-time request that can seed Blue's authoritative verdict cache.
DRY_RUN uses the existing ledger routes and their Battlefield-owned enforcement.

Balanced general-ledger accounting, mutation exactly-once guarantees, integrated
permission mirroring, and coordinated multi-seed episodes are not claimed by this
milestone. Existing shared tool decoration does not propagate one identity from
events into ledger writes; event presence is not proof of identity parity.

## Response to integration review on #13 and #14

Ad's review on #13 holds both PRs for a live Green demo. The minimal shared
handoff is now in [INTEGRATION.md](INTEGRATION.md); Green can integrate once that
reviewed support is merged. There is no confirmed merge date or live-release ETA.

Main `68ef4eb` includes `9736639`: shared Droid tools now run on worker loops,
and the first executable session has a restricted allowlist built using the
observed `<server>___<tool>` IDs. Those fixes do not propagate the SDK invocation
identity into permission callbacks, tool events and ledger headers, and do not
add authoritative preflight or replay-only cache semantics. Reinstating the old
mirror with only a different key would still risk priming the cache with
incomplete context. The live guard therefore remains, and the review hold is not
claimed resolved.

The unsupported-action regression is addressed in the preceding workflow PR:
unsupported action/entity pairs must fail before any ledger I/O, not escape via
`AttributeError` from a nonexistent `pay_vendor_change` method.

## Dev Ad: requested contract review and shared implementation

Choose and review the HTTP, models, storage, freshness, and `LedgerClient` design.
No endpoint name or new response shape is assumed by Green. Proposed additions
to the **semantics** of `contracts/agent-service.md` and the Ledger API:

```diff
+ Battlefield prepares an action before Green mirrors a permission decision.
+ Preparation receives the verified invocation ID and normalized action arguments.
+ Battlefield validates the action and builds full, provenance-stripped context.
+ Preparation binds ID to episode, day, controller mode, action, entity,
+ normalized arguments, and relevant ledger state.
+ Preparation evaluates controls and records the canonical decision, but never
+ performs the requested approval, payment, rejection, or journal posting.
+ Enforced blocks are recorded even if CANCEL prevents the later ledger request.
+ Escalations are resolved by Battlefield; their effective result is reused by
+ execution without opening a second human approval flow.
+ Green receives the canonical gate envelope and effective preparation outcome.
+ A later mutation consumes only a still-valid matching preparation and remains
+ independently guarded by Battlefield.
+ State changes, mode changes, conflicting arguments/IDs, expiry, or mismatched
+ bindings reject execution, without an automatic mutation retry.
+ Validity and replay behavior explicitly account for the 120-second verdict
+ cache and up to 90 seconds of human-resolution waiting.
```

Additional shared plumbing prerequisites:

- Expose the SDK's verified real tool-use ID to the permission callback, tool
  execution, event accounting, and `LedgerClient`. Generate UUID4 only for
  non-Droid calls. Reject absent, model-provided, or invalid identities.
- Emit exactly one correlated tool-call/result pair for a canceled invocation,
  even when its tool body never runs. Approved invocations must not duplicate
  that pair. Do not confuse cached verdicts with deduplicated mutations.
- Verify the merged first-session restriction against Green's exact MCP allowlist.
  Never authorize unknown tools using suffixes, argument matching or a last-ID fallback.
- Propagate turn-local clerk state into the merged SDK worker-loop adapter.
  Rebinding only `agentkit.ctx` does not carry Green's `ContextVar` state.
- Pass the existing `APPROVAL_THRESHOLD` into Green's Compose environment.
- Record empirical SDK Findings through Ad's authorized contracts path. The
  ownership guard currently excludes `contracts/CHANGELOG.md` on Green branches;
  Green will not bypass it.

### Independently reproduced event-delivery blocker

**P1, Ad-owned baseline:** `agentkit/agentkit/events.py` calls `flush()` once
during `EventEmitter.__aexit__`, then cancels its pump. `_drain()` processes at
most `max_batch` events (default 50), leaving the rest undelivered.

Reproduction: use a mocked event endpoint, queue 55 events without yielding
inside an `EventEmitter` context, exit, and count posted events. Expected 55;
observed 50. A standalone emitter probe reproduces this without Green. A fast
12-invoice Green turn likewise confirmed 24 mutations and $14,400 paid, but sent
only 50 of 55 expected events, including an unmatched received tool-call.

The independent verifier's two temporary regression probes both fail on this
same unchanged shared behavior. Ad must drain all remaining batches at shutdown
and test event-pair completeness. Green does not patch or wrap shared event
delivery to hide it. Full event-pair acceptance remains blocked.
Ad reports the fix is in `battlefield/agentkit-hardening`; it is not present in
the checked main `68ef4eb`. This is a handoff, not a Green-owned workaround.

## Blue session: requested replay contract and cache changes

Agree the protocol with Ad before Green integrates it:

- Distinguish authoritative evaluation from **replay-only** mirroring. A missing
  replay must never trigger a fresh evaluation or cache an incomplete allowance.
- Bind the cache entry to the canonical request. Reject conflicting key reuse.
- Specify missing-cache, expiry, and canonical-envelope validation behavior,
  including an escalation resolved near the end of the cache lifetime.
- Return the cached verdict for a valid replay. Green must forward the canonical
  envelope returned by Battlefield rather than reconstruct evidence.
- Add complete-context, conflicting-key, replay-miss, and expiry regressions.
- Preserve the eight-second gate budget and the no-ledger-I/O gate rule. Daily
  audit stays independent and uses the normal agent-turn timeout.

## Green integration acceptance after shared changes merge

1. Off mode skips Blue entirely.
2. Shadow records decisions and permits execution despite a Blue block, outage,
   or mirror failure, subject to normal ledger validation.
3. Enforce follows Battlefield's effective result. Human approval/block/timeout
   comes from Battlefield, not a Green-owned escalation flow.
4. Mirror failure after authoritative allowance cancels in enforce and is an
   integration failure, not a fraud block. Green reports failures separately.
5. Stale or mismatched preparation never authorizes a write. No silent retries.
6. IDs match across permission, events, ledger headers, and decisions, including
   exactly one event pair for canceled calls.
7. Unknown tools, missing IDs, malformed responses, replay misses, state/mode
   changes, and expiry fail safely. No incomplete mirror can prime the cache.
8. Require a pinned, non-`auto` live model and retain keyless DRY_RUN.

## SDK evidence still required

No live SDK experiments are authorized or claimed by this checkpoint. With
separately authorized credentials and an isolated disposable session, measure:

- Whether `Autonomy.OFF` invokes permission callbacks for Green MCP tools.
- Green's exact MCP allowlist and first-turn restrictions, using the merged
  `<server>___<tool>` finding rather than guessing a different ID format.
- Invocation identity and metadata available to callback and execution contexts.
- Whether a CANCEL comment reaches the model.

Use small probes, sanitize evidence, and send findings to Ad. Do not guess SDK
metadata, change autonomy silently, or run paid sessions just to discover it.

## Joint runtime acceptance, not run by this checkpoint

Coordinate a single local stack and episode schedule with Blue's operator.
Worktrees isolate files, not ports, databases, or Compose services. Load the
Green worktree-built service without replacing or restarting Blue.

Run matching-seed off/shadow/enforce episodes, then repeat for a second seed.
Check legitimate completion, plausible fraud payable off, observational shadow
decisions, and enforced blocks/cancellations visible in ledger/operator views.
This does not authorize Green to tune Blue's rules or scoring.

## Separate accounting milestone

Agree recognition versus payment settlement with Ad first. Require
contract-backed atomic, deduplicated balanced posting tied to confirmed payment
references. Expense-debit/AP-credit is recognition, not payment settlement.
Do not invent cash-account conventions, treat two line writes as atomic, or
repay an invoice to repair its accounting.

## Foundation verification record

Before review fixes, the original implementation passed 42 Green tests and a fresh independent review.
Splitting the work adds eight clerk-primitive cases without removing or skipping
existing tests. Each review slice changes only Green and adds one Dev M log
fragment; `DEVLOG.md` is now frozen history.

- Green Ruff check and format check: passed.
- At the initial split, the combined Green suite passed **50 tests** on Python 3.11.
- Repository lint passes Python checks but stops at frontend `tsc: command not found`.
- The first slice passes nine tests; the activated workflow slice passes 18 tests.
- The current main base includes the root uv-workspace fix. Service imports still
  need the same `PYTHONPATH` used by CI; plain Makefile invocation omits it.
- Tests can use each service's `uv sync --extra dev` environment with its Green
  directory on `PYTHONPATH`. The existing isolated environment was also used:

  ```sh
  cd /Users/mateootero-diaz/projects/Hack/Calhacks/redledger-green-verification
  UV_NO_SYNC=true UV_PROJECT_ENVIRONMENT=/tmp/redledger-green-tests \
    PYTHONPATH="$PWD/green:$PWD/agentkit" make TOKEN=change-me test-green
  ```

- Whitespace and changed-path ownership checks: passed.
- Two temporary probes from the original independent review failed, demonstrating
  only the shared event-shutdown defect above; those are not passing tests.
- No live SDK sessions, credentials, local stacks, or coordinated episodes were
  used. Live permissions, invocation identity, canonical replay, and accounting
  acceptance remain deferred.

## Current PR and integration handoff

The original `green/ap-workflow` branch is preserved locally. The three initial
slices were created from main `3f41c4e`; #12 has since been merged. #14 remains
stacked on #13 and must not be merged before it.

| PR | Head | Dependency | Scope |
|---|---|---|---|
| #12, merged | `green/ap-foundation-1` | None | Clerk primitives, fixtures, direct tests |
| #13, held | `green/ap-workflow-2` | #12 | Activate AP, live guard, DRY_RUN and dispatch tests |
| #14, held | `green/ap-verification-3` | #13 | Failure/recovery tests and protocol handoffs |

Keep incremental review diffs below 600 lines. Use the PR template and leave
checks incomplete when their validation is blocked; no green-CI claim is made.

Current `GIT.md` allows teammates' agents to push their branches and open PRs.
Ad is the integration and merge authority: CI and the PR steward must pass before
integration squash-merges to main. Authors never merge or approve their own PRs.
Integration can resync stacked branches with plain main merges; authors pull
before continuing. Never force-push or rewrite shared review history.
