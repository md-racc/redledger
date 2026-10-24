# CRS employee identity integration

This replaces B2's unsupported EIN/vendor lookup with approved fictional employee checks.
It is **not a completed live demo**. Blue's live audit still refuses to stream or write until
its SDK tool IDs, owner-loop safety, and invocation binding are verified. That safeguard is
unchanged. DRY_RUN never calls CRS, even with credentials present.

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

- Merge the companion `battlefield/crs-runtime` and `docs/crs-runbook` PRs before this
  implementation: they provide credential plumbing, the documented extension CI carve-out,
  and corrected root environment/runbook guidance. Draft publication is not completion.
  A human must still supply `CRS_USERNAME` / `CRS_PASSWORD` locally or as production secrets.
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
- Check `/users/logs` as an operator after the demo: the requests must be `billable:false`.
  Use matching public episode setups, not agent-visible provenance, to compare controls.
  Keep HR records valid and payment accounts distinct so CRS, not existing ghost-employee
  heuristics, supplies the hold. A later expense gate, not the check itself, must block.

Tests mock all CRS I/O. Docker/Postgres episode smoke and authenticated sandbox verification
remain separate acceptance steps; mocked audit-to-gate tests are not evidence of a live demo.
