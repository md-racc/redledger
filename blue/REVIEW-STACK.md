# Current local Blue review stack

Pinned upstream baseline: `68ef4ebe621e4caa5e69114c3c8f18ff8f35620c` (`origin/main` when created).
Only `blue/review-current-*` below are submission candidates.
Writable worktree: `/Users/mateootero-diaz/projects/Hack/Calhacks/redledger-blue-review-current`.

**PRESERVED, NOT SUBMISSION TARGETS:** `blue/controller` at
`78eb287d7c653ddf7f3bfaf076f9abf96e0d3616`, and the prior non-current `blue/review-*` stack.
Their worktrees and branch refs are untouched, including the old staged final handoff.
The first seven current checkpoints replay exactly their previously reviewed Blue-only diffs.

Each row has one commit and exactly one **new M fragment** under `devlog/`, holding one line.
`DEVLOG.md` is frozen and unchanged. Existing fragments are never edited.
Lines count added + deleted, including tests/docs/the new fragment, against the immediate predecessor.
Every checkpoint passed Blue `ruff check .`, `ruff format --check .` and `uv run pytest -q`.

| # | Current branch | Local base | Tip | Lines | Tests | Purpose |
|---|---|---|---|---:|---:|---|
| 1 | `blue/review-current-gate-policy-1` | `68ef4eb` | `4791bc9` | 556 | 4 | Deterministic policy/retention; disconnect raw advisory and hold audit writes |
| 2 | `blue/review-current-gate-advisory-2` | `blue/review-current-gate-policy-1` | `2dd32af` | 511 | 24 | Privacy-bounded advisory, cache concurrency and isolated dummy settings |
| 3 | `blue/review-current-gate-regressions-3` | `blue/review-current-gate-advisory-2` | `6465f99` | 342 | 94 | Full positive/benign gate matrix |
| 4 | `blue/review-current-audit-snapshot-4` | `blue/review-current-gate-regressions-3` | `25aaa2e` | 506 | 98 | Typed receipts and bounded public collection, not yet activated |
| 5 | `blue/review-current-audit-findings-5` | `blue/review-current-audit-snapshot-4` | `95d305e` | 489 | 108 | Corroborated controls, private projections and nonblocking CPU work |
| 6 | `blue/review-current-audit-tools-6` | `blue/review-current-audit-findings-5` | `7eb9b45` | 344 | 113 | Invocation-bound writes, fresh freeze checks and service report |
| 7 | `blue/review-current-audit-service-7` | `blue/review-current-audit-tools-6` | `022d8f5` | 508 | 132 | Guarded dry-run/shared lifecycle and unchanged routes; live stays closed |
| 8 | `blue/review-current-validation-handoff-8` | `blue/review-current-audit-service-7` | this commit | 429 | 151 | Receipt/cancellation, offline auth/events checks and current-protocol handoff |

Resolve the final SHA with `git rev-parse blue/review-current-validation-handoff-8`.
All incremental reviews are below 600 lines. Only Blue and eight new M fragments differ from
`68ef4eb`; shared code, dependency definitions and `blue/gate/cache.py` are unchanged.

## Publication and integration order

Local-only authorization remains in force: no push, PR, owner contact, approval or merge occurred.
Only #1 is main-ready in dependency terms now; later rows remain dependent drafts.
When publication is authorized, every dependent PR must explicitly say **`stacked on #N`**
using its actual predecessor PR number. Integration merges bottom-up.

**Ad is the sole integration merge authority. Authors never merge their own PRs.**
A merge requires green CI and the read-only PR steward's **READY assessment pinned to the head SHA**;
a later push voids that assessment. Core/shared or multi-area changes additionally need the
independent verifier required by current GIT.md; this stack changes only Blue plus its fragments.
CODEOWNER routing/notification is welcome, **not an approval or self-review blocking gate**.
Owner routing remains M (`moterodiaz`), with Ad (`md-racc`) as integration authority.

After each predecessor lands, integration may plain-merge `origin/main` into an open successor
to resync/resolve conflicts. Do not force-push or rewrite published history. Pull integration's
updates, remeasure the main-relative diff, rerun checks and obtain a new steward assessment
before readiness. Do not submit the cumulative stack as one oversized review.

## Safety, coverage and no peeking

Audit writes remain held through #6; #7 replaces the scaffold's flag-every-new-vendor path.
Live remains unconditionally closed: exact Blue tool IDs, worker-thread Blue context and verified
invocation-to-write binding are unverified. Shared first-session restriction/event-header fixes
are acknowledged, not falsely listed as unresolved by themselves.

All 144 source cases are retained in focused modules; the live-path test is strengthened, not
skipped. Seven added cases give 151: outcome counting, four auth endpoints, fallback and event headers.
The public audit-log read is explicitly `agent="green"`; no unfiltered/red audit-log tool, event
reads, scoreboard, attack reads, raw provenance or raw battlefield HTTP enter the controller.
Public writes remain through LedgerClient; EventEmitter only emits events.

## Current validation and follow-ups

Normal per-service Python 3.11 sync and all 151 tests pass, without a workspace workaround.
Env-file loading is disabled; tests use distinct dummy agent/operator/legacy credentials.
Blue and repository Python ruff checks/format checks pass.
`make OPERATOR_TOKEN=validation TOKEN=validation lint test-blue` stops only at the known absent
frontend `tsc`; no frontend install/fix was attempted. Independent
`make OPERATOR_TOKEN=validation TOKEN=validation test-blue` passes 151.
Ignored logs: `blue/.review-make.log`, `blue/.review-test-blue.log`; generated locks are uncommitted.

See `CONTROLLER.md` for deliberate onboarding holds, memory-only retention, unknown-write
reconciliation, limited upstream completeness and corrected bank-swap scoring heuristics.
Its latency numbers are labeled prior-stack measurements, not fresh current-base measurements.
Required follow-ups: independent orchestrator verification; authorized publication; Ad's ordered
CI/steward integration; Blue-specific SDK binding verification before live unlock; later authorized E2E.
No cross-owner fix, Docker, external model call, new dependency or service env variable was introduced.
