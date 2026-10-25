# CRS employee identity integration

This replaces B2's unsupported EIN/vendor lookup with approved fictional employee checks.
End-to-end acceptance **passed locally** against the live CRS sandbox on 2026-10-25
(ep_0181eda1c921, keyless audit with `CRS_LIVE=true`, see "Episode acceptance re-run" below).
Blue's live-audit guard was lifted on merged evidence (#157; `SDK-READINESS.md`, "Live audit
readiness lift"), and the audit runs on Droid on prod since 2026-10-25 (`DRY_RUN_BLUE=false`), so a
live audit calls the provider under the binding, name and seven-day rules below. The live audit's
CRS path **passed on prod** on 2026-10-25 (ep_9cbc3362d44e, `make prod-crs-episode`, see "Prod
live-audit acceptance" below): one recorded 2-day run with persona-bound employees.
DRY_RUN never calls CRS, even with credentials present, with one explicit exception:
exporting `CRS_LIVE=true` in the shell (acceptance-only, default off, never committed anywhere)
lets the keyless audit call the sandbox provider.

## Data flow and safety

The operator binds a synthetic employee to `P01`, `P12`, or `P16` using
`PUT /api/x/blue/crs/episodes/{episode_id}/employees/{employee_id}` with
`{"persona_id":"P01"}`, an operator bearer token, and **no** `X-Agent`.
Bindings are immutable within an episode. Blue alone reads
`GET /api/x/blue/crs/employees/{employee_id}` using its normal LedgerClient headers.
There is no automatic assignment based on provenance, scoring, input leads, or expected results.
The employee's name must match the bound persona's full name, otherwise the check is unknown.

`crs_identity_check` considers active employees onboarded within seven days. It checks at most
ten profiles per audit, reserves reporting time, and reuses the snapshot results on repeated
tool calls. Existing audit episode/day caching prevents same-process same-day turn replays.
No durable exactly-once sponsor-call guarantee is claimed across process restarts.

Only an explicitly DELIVERED product with CLEAR/HIT search status and well-formed messages
supplies evidence. SSN/name, issuance/DOB, or deceased-identity inconsistencies create a
high-severity employee finding. Address-only mismatches and fraud alerts require human review,
not fraud allegations or automatic holds. Unknown data produces no finding. Reports include
unknown/step-up counts; optional CRS failures do not fail an otherwise complete audit.
Only sanitized statuses and service-authored findings reach events or the model.
The existing `already_flagged_high` gate rule consumes employee flags on later expenses.
CRS adds no network call, new rule, or latency to `/gate`.

Pinned fictional bodies: `audit/crs_personas.json`, copied exactly from
[`@crscreditapi/crs-calhacks-mcp-server@1.1.2/dist/test-data/personas.json`](https://unpkg.com/@crscreditapi/crs-calhacks-mcp-server@1.1.2/dist/test-data/personas.json).
No expected decisions are shipped to the client. Unmatched identities can reach real vendors,
even in the sandbox, so arbitrary names, EINs, SSNs, addresses, and modified requests are forbidden.

## Prerequisite PRs and remaining live setup

- The companion documentation PR #61 and runtime/CI PR #63 merged on 2026-10-24.
  This branch incorporates them: credential plumbing and the documented extension CI
  carve-out are available. Their merge is not live acceptance.
  A human supplies `CRS_USERNAME` / `CRS_PASSWORD` locally or as production environment secrets;
  setting GitHub secrets does not export them into a developer's local process.
  Do not send secrets here or put them in a browser variable. The legacy `CRS_API_KEY` is not
  a username/password substitute.
- Apply the normal additive extension schema, `contracts/ext/blue/01_crs_profiles.sql`.
  Create synthetic employees with the exact sponsor names (P01 MARGARET OKAFOR,
  P12 VICTOR ANAND, P16 SAMUEL OYELARAN) and bind them explicitly. Do not change core columns.
- Blue's live-audit readiness blockers are resolved (#157). The verified tool-ID list includes
  `blue-ledger___crs_identity_check`; any new tool must be added from an observed listing, not guessed.
- With sponsor-confirmed credentials and ROLE_TU_TV, perform the live demo only after readiness
  is proven. The fixed base is `https://api-sandbox.stitchcredit.com/api`; login is
  `POST /users/login`, then `POST /transunion/identity-manager-verification/basic`.
  Login is attempted once per client lifetime, with no retries or automatic refresh. A failed,
  malformed, or expired token requires human review and a Blue restart, not a retry loop.
- Acceptance may use the `CRS_LIVE=true` switch to exercise the keyless audit against the
  sandbox; P01/P12/P16 persona binding and `billable:false` verification still apply.
- Check `/users/logs` as an operator after the demo: the requests must be `billable:false`.
  Use matching public episode setups, not agent-visible provenance, to compare controls.
  Keep HR records valid and payment accounts distinct so CRS, not existing ghost-employee
  heuristics, supplies the hold. A later expense gate, not the check itself, must block.

Tests mock all CRS I/O. Docker/Postgres episode smoke and authenticated sandbox verification
remain separate acceptance steps; mocked audit-to-gate tests are not evidence of a live demo.

## M-owned acceptance and Ad handoff

The historical droid-sdk 0.5.0 / mcp 1.30.0 probe matched seven schemas and rejected metadata
arguments, but blocked its owner-loop heartbeat and used a local, unverified invocation. A
separate real, list-only Session matched all seven IDs without streaming. #79 now isolates the
turn loop; Blue's shared narration, TurnLock and canned cross-loop tests are covered in
`SDK-READINESS.md`. These offline checks do not qualify authenticated SDK traffic or CRS access.
(Since then the live evidence in `SDK-READINESS.md` led #157 to lift the live guard.)

| Remaining check | Owner |
|---|---|
| Strict identity, exact-ID restriction and authenticated SDK-to-write receipts | Ad supplies shared strict identity; M adopts it and proves real receipts using the observed seven IDs |
| Actual SDK cancellation/ownership and concurrent gate budget | Ad + M; #79 and canned cross-loop tests are prerequisites, not live proof |
| Apply schema, prepare valid-HR employees with distinct accounts, bind P01/P12/P16 (P4) | Ad/operator prepares; M binds through the operator extension, never core-table writes |
| Clean/mismatch/step-up episodes, a later CRS-caused expense hold, and `billable:false` logs | M/operator with an authorized environment; unknown and step-up remain neutral |

See `blue/SDK-READINESS.md` for the pinned IDs, list-only command, receipt tests and Ad handoff.
CRS PR #64 and its prerequisites have merged; episode acceptance passed on 2026-10-25 (below).
Bright Data C3 was **DROPPED** on 2026-10-25 (M, #78 closed): the real-agent shadow checkpoint it
required will not run, and no Bright Data code or credentials are on main.

## Sandbox probe evidence, 2026-10-24 (approved scope: P01/P12/P16 only)

With operator-supplied local credentials, blue's own `CRSClient` made exactly one login
(latched, no retries) and one `identity-manager-verification/basic` POST per pinned persona.
Sanitized statuses: **P01 MARGARET OKAFOR — DELIVERED, searchStatus HIT, zero messages**
(sponsor note: "messages: empty = verified"; the earlier parser required CLEAR and returned
unknown — fixed in this PR), **P12 VICTOR ANAND — mismatch** (2201/2202/2301 family),
**P16 SAMUEL OYELARAN — review** (2101/2401 family). A structural re-request for P01 was
returned `CACHED` by the sandbox. Operator follow-up `GET /users/logs` (`{content, count,
hasMore}` shape): all four entries `billable:false`. No credentials, tokens, bodies, or
provider prose were logged or printed. Episode-level clean/mismatch/step-up cases still need
Ad's operator fixture route (employee + one expense each with distinct accounts, `hr_record`)
before the end-to-end audit-to-gate hold can be demonstrated.

## Episode acceptance evidence, 2026-10-24 (approved scope: P01/P12/P16 only)

`blue/tests/crs_episode_acceptance.py` (opt-in, `--allow-provider-call`) drove a two-day
enforce episode on the merged operator fixtures route with the keyless audit and
`CRS_LIVE=true`: three fixture employees (exact persona names, distinct accounts,
`hr_record`, active, `start_day` 0) bound to P01/P12/P16 through the operator extension, one
expense per employee before day 0 and a second per employee while paused between days, the
episode advanced by `/step` only. Result (episode ep_e1d35dfb24b1): all three day-0 expenses
paid — the check itself blocks nothing — and the day-0 audit produced **exactly one
high-severity employee flag, on P12 (mismatch)**; P01 (verified) and P16 (review) stayed
flag-free through day 1. Two audit reports posted; the provider's `/users/logs` then showed
13 identity-verification entries, **all `billable:false`**. No credentials, tokens, bodies,
or provider prose were logged or printed.

**Finding (battlefield, reported on #102):** the hold did not fire — P12's day-1 expense
paid. `already_flagged_high` is correct, but `_expense_context` (used by both the gated
routes and `/api/preparations`) never includes `flags`; only `_invoice_context` does
(vendor + invoice flags). Employee flags therefore never reach the gate on expense actions.
Proposed fix is one symmetric query in `battlefield/app/api/green_writes.py`
(`(entity_type='employee' AND entity_id=<employee>) OR (entity_type='expense' AND
entity_id=<expense>)`). Once it lands, re-run the driver: P12's day-1 expense must block on
`already_flagged_high` while P01's and P16's pay. **Landed as #139** (`_expense_context` now
carries employee and expense flags, for the gated routes and `/api/preparations`).

## Episode acceptance re-run, 2026-10-25 (approved scope: P01/P12/P16 only)

M re-ran the driver against #139 (`crs_episode_acceptance.py --allow-provider-call
--blue-external`; local stack at main `34fdbdf`, real blue, live CRS sandbox; #102). Episode
ep_0181eda1c921, two-day enforce: P01/P12/P16 day-0 expenses paid (no flags yet); blue's audit
flagged P12 (provider mismatch), P01/P16 flag-free; **P12's day-1 expense blocked with
`already_flagged_high`** in `rules_fired`; P01/P16 day-1 expenses paid (no false positives); two
audit reports posted; provider `/users/logs` showed 19 identity checks, **all `billable:false`**;
`acceptance_passed: true`, exit 0. That completes the #102 sequence. The 3-day all-real shadow
checkpoint is separate (#78).

## Prod live-audit acceptance, 2026-10-25 (approved scope: P01/P12/P16 only)

`make prod-crs-episode SEED=42 DAYS=2` (#197; `deploy/PROD-OPS.md`) ran the same scenario on prod
with blue's **live Droid audit** (`gpt-5.4-mini`, `DRY_RUN_BLUE=false`, no `CRS_LIVE`). The command
created an unstarted enforce episode, seeded the three persona employees through the operator
fixtures route, bound them to P01/P12/P16 through the operator extension, added the day-1 expenses
while paused between days, and advanced the episode by `/step` only. Episode ep_9cbc3362d44e,
seed 42, two days, result **PASS**:

- The live audit called `crs_identity_check` on day 0 and on day 1.
- The CRS sandbox reported an identity mismatch for P12. The model raised the HIGH employee flag
  through `raise_flag` with the service-defined finding ("CRS reports an employee identity
  inconsistency; independent HR review is required.").
- On day 1 the gate blocked P12's expense: `expenses.approve` → block, `rules_fired`
  `["already_flagged_high"]`, enforced. P01's and P16's expenses all paid.
- Two audit reports posted. Blue's audit credits: 3,985 (day 0) and 5,318 (day 1).
- Recording (operator event stream, no identity data or provider prose):
  `docs/recordings/crs-live-ep_9cbc3362d44e.jsonl`.

The first prod attempt, ep_c2c98b2da583, failed: blue's live `raise_flag` calls were refused by
agentkit's strict identity check, because `gpt-5.4-mini` streams tool arguments and the first
event carries `{}`. #195 (let streamed tool arguments complete before identity binding) fixed it.
This is the first CRS run on prod and the first driven by the live agent; the earlier acceptance
(ep_0181eda1c921) was local with the keyless audit. The provider's `/users/logs` was not part of
this run's evidence, so the `billable:false` checks above remain the local ones. One run: it shows
the path works, not that every run will.
