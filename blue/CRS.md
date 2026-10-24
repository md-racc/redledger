# CRS employee identity integration

This replaces B2's unsupported EIN/vendor lookup with approved fictional employee checks.
It is **not a completed live demo**. Blue's live audit still refuses to stream or write until
its owner-loop safety and authenticated invocation binding are verified. That safeguard is
unchanged. DRY_RUN never calls CRS, even with credentials present, with one explicit exception:
exporting `CRS_LIVE=true` in the shell (acceptance-only, default off, never committed anywhere)
lets the keyless audit call the sandbox provider. The live SDK audit guard is unchanged.

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
- Resolve Blue's existing live-audit readiness blockers separately. Adding a new tool means
  the verified tool-ID list must include `crs_identity_check`; do not guess its SDK-qualified ID.
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
Readiness remains false and the live guard remains intact.

| Remaining check | Owner |
|---|---|
| Strict identity, exact-ID restriction and authenticated SDK-to-write receipts | Ad supplies shared strict identity; M adopts it and proves real receipts using the observed seven IDs |
| Actual SDK cancellation/ownership and concurrent gate budget | Ad + M; #79 and canned cross-loop tests are prerequisites, not live proof |
| Apply schema, prepare valid-HR employees with distinct accounts, bind P01/P12/P16 (P4) | Ad/operator prepares; M binds through the operator extension, never core-table writes |
| Clean/mismatch/step-up episodes, a later CRS-caused expense hold, and `billable:false` logs | M/operator with an authorized environment; unknown and step-up remain neutral |

See `blue/SDK-READINESS.md` for the pinned IDs, list-only command, receipt tests and Ad handoff.
CRS PR #64 and its prerequisites have merged, but live acceptance remains incomplete.
Bright Data C3 also requires the real-agent three-day shadow checkpoint in `INTEGRATIONS.md`.

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
