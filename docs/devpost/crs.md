# Red Ledger for the CRS Financial Intelligence Challenge

Status as of 2026-10-25 ~05:45Z, main @ e440119. **Prod live-audit acceptance PASSED** at ~05:40Z (ep_9cbc3362d44e, `make prod-crs-episode`, #197). Issue #102 is closed (local acceptance passed, M, 00:09Z).

Status legend: `LIVE` = running on prod (app.redledger.us) with a real model today. `ON MAIN` = merged and tested, runs keyless, not exercised live on prod. `PLANNED` = not done yet. `NOT DOING` = out of scope. Track-specific tags: `PROD-PROVEN` = exercised on prod against the real CRS sandbox by blue's live Droid audit, in one recorded run (ep_9cbc3362d44e). `SANDBOX-PROVEN (local)` = exercised against the real CRS sandbox from a team member's local stack, with evidence in a PR or issue. `UNVERIFIED` = could not confirm.

---

## 0. Verdict first (read before using anything below)

**CRS live-evidence verdict: GO for Best Identity / Fraud Innovation, GO for Best Financial AI Agent, don't target
Best Overall.** On 2026-10-25 at ~05:40Z, `make prod-crs-episode SEED=42 DAYS=2` (#197) ran blue's CRS scenario on
prod in episode **ep_9cbc3362d44e** (enforce, seed 42, 2 days) and printed **PASS**:

- Blue's **live Droid audit** (`gpt-5.4-mini`) called `crs_identity_check` on day 0 and on day 1.
- The CRS sandbox reported an identity mismatch for persona P12. The model raised the HIGH employee flag through
  `raise_flag` ("CRS reports an employee identity inconsistency; independent HR review is required.").
- On day 1 the gate blocked P12's expense: `expenses.approve` → block, `rules_fired: ["already_flagged_high"]`,
  enforced. P01's and P16's expenses all paid.
- Two audit reports posted. Blue's audit used 3,985 credits (day 0) and 5,318 (day 1).
- The command did the persona setup itself: the operator fixtures route, then the three operator bindings.
- Recording: [`docs/recordings/crs-live-ep_9cbc3362d44e.jsonl`](../recordings/crs-live-ep_9cbc3362d44e.jsonl).

This is the first CRS run on prod and the first one driven by the live agent. The first attempt, ep_c2c98b2da583,
failed: blue's live `raise_flag` calls were refused by agentkit's strict identity check, because `gpt-5.4-mini`
streams tool arguments and the first event carries `{}`. #195 fixed that. Before it, M's acceptance
(**ep_0181eda1c921**, #102, 00:09Z) had proven the same chain on a local stack with blue's keyless deterministic audit
and `CRS_LIVE=true`: P12 flagged, P12's day-1 expense blocked with `already_flagged_high`, P01/P16 paid, 19 identity
checks all `billable:false`. The provider's `/users/logs` is not part of the prod run's evidence, so the
`billable:false` numbers below are from the local runs.

What is proven, and where:

| Claim | Proven? | Where | Evidence |
|---|---|---|---|
| Authenticated login to the CRS sandbox (username/password → bearer) | Yes, local and prod | M's machine; prod | `blue/CRS.md`; #125; #102; ep_9cbc3362d44e |
| Identity-verification calls for exactly P01, P12, P16 | Yes, local. On prod only these three could be checked (no other employee is bound) | same | same; `deploy/prod.sh` `crs_episode` |
| Live outcome ladder: P01 verified (after the #125 parser fix), P12 mismatch, P16 review | Yes, local (probe); on prod P12 mismatch → flag, P01/P16 no finding | M's machine; prod | #125; `blue/CRS.md` "Sandbox probe evidence"; ep_9cbc3362d44e |
| `billable:false` on the provider's `/users/logs` | Yes: 4/4 (probe), 13/13 (first episode run), 19/19 (acceptance run). Not checked for the prod run | provider logs, operator read | `blue/CRS.md`; #134; #102 |
| CRS inside a real episode flags only the mismatch persona | Yes: local twice (ep_e1d35dfb24b1, ep_0181eda1c921), prod once (ep_9cbc3362d44e) | local stack; prod | `blue/CRS.md`; #102; #197 |
| **CRS finding causally blocks a later gated action** (P12's next expense) | **Yes, local and prod**: P12's day-1 expense blocked, `already_flagged_high` in `rules_fired`; P01/P16 paid | local stack (ep_0181eda1c921); prod (ep_9cbc3362d44e) | #102; #197; the fix it needed is #139 (`battlefield/app/api/green_writes.py` `_expense_context`) |
| **Blue's live Droid audit calls CRS and raises the finding** | **Yes, prod, one run**: `crs_identity_check` called on day 0 and day 1, `raise_flag` on the CRS finding, `gpt-5.4-mini` | prod | ep_9cbc3362d44e; recording; #195 (the fix it needed) |
| Which blue path made the call | Local runs: the **keyless deterministic audit** with `CRS_LIVE=true`. Prod run: blue's **live Droid audit** (`DRY_RUN_BLUE=false`, no `CRS_LIVE`) | — | #102; #157; #197 |
| Anything CRS on prod | **Yes, one recorded run** (ep_9cbc3362d44e, PASS). CRS runs on prod only for a run set up by `make prod-crs-episode` (or the same manual fixtures + bind steps): blue calls CRS only for an active employee onboarded in the last 7 days, bound by an operator to P01/P12/P16, whose name equals the persona's. Seeded employees never qualify, so ordinary prod episodes make no CRS call | prod | `deploy/prod.sh` `crs_episode`; `blue/audit/tools.py:229-245`; `blue/audit/crs.py:67-76`; `battlefield/seed/company.py:73-84` |
| Episode acceptance drivers on main | **Yes**: local `blue/tests/crs_episode_acceptance.py` (opt-in `--allow-provider-call`, `--blue-external`; not collected by pytest; #150 adds a login retry and keeps evidence on failure) and prod `make prod-crs-episode SEED= [DAYS=]` (#197; `deploy/PROD-OPS.md`) | — | #134; #150; #197 |
| Frontend or pitch shows CRS | **No** dedicated view or beat. The prod run's events are in the normal stream; how `/backstage/blue` renders them is UNVERIFIED | — | no CRS references in `frontend/` (grep); `frontend/docs/pitch-script.md` |

**Recommendation on whether to submit to CRS** (the challenge's only rule: "Make meaningful use of the CRS sandbox and show it working live in your demo", calhacks.crscreditapi.com):
- **Best Identity / Fraud Innovation: GO** (optionally also Most Unexpected Use). The live part is now one command
  against prod: `make prod-crs-episode SEED=42 DAYS=2`, about a minute of wall clock in the recorded run. It needs a
  laptop set up for `deploy/prod.sh` (deploy key, `PROD_HOST`; `deploy/PROD-OPS.md`) and prod's CRS credentials.
  The local driver on a laptop stack stays the alternative. Fallback: the recording of ep_9cbc3362d44e, labelled
  "recorded on prod, 2026-10-25". A recording alone is weaker under the challenge's only rule, so run it live if
  anyone can.
- **Best Financial AI Agent: GO, supported by this recorded live-agent run.** Say exactly what it shows: one 2-day
  run with 3 approved fictional personas, in which blue's live Droid audit chose to call `crs_identity_check` on both
  days and raised the CRS finding through `raise_flag`, and the gate then held the next expense. The service picks
  which employees get checked, and the provider decides each status; the model sees only status counts and
  service-defined finding ids, never identity data. So the agent's judgment is in calling the tool and acting on
  the finding, not in deciding who is who. One run, not "always".
- **Best Overall CRS Hack:** don't target it; one endpoint and three personas is not "the most impressive product
  built on CRS".
- **Before the table:** prod takes one run at a time (the command exits 3 while another episode or lineage runs),
  so don't start it during the stage demo. The sandbox login has flapped (401 windows of a few minutes after heavy
  use, #78), and blue logs in to CRS once per process with no retry (`blue/audit/crs.py`). If a later run FAILs with
  no P12 flag and the summary's CRS result counts are all unknown, blue needs a restart before a retry
  (`blue/CRS.md`), not a loop.
  Keep the recording ready.

---

## 1. Prize snapshot

| Category | Value | What judges want (calhacks.crscreditapi.com, fetched 2026-10-24) |
|---|---|---|
| Best Overall CRS Hack | $1,000 | "The most impressive product built on CRS: useful, working, and hard to put down." |
| Best Financial AI Agent | $500 | "The best use of AI with CRS data. An agent that does real work, not a chatbot that reads JSON." |
| **Best Identity / Fraud Innovation** (primary) | Interview | "The best solution protecting consumers or businesses from fraud and identity theft." |
| Most Unexpected Use of CRS | Interview | "The 'we didn't think of this' prize. Surprise us." |

Judging: "No points formula. Judges look at the whole project, and a bold idea counts for as much as polish." Criteria: **Originality** ("Did it surprise us?"), **Usefulness** ("Would somebody actually use this?"), **CRS at the core** ("The data is what makes it work."), **It really works** ("A live demo, end to end."), **Responsible** ("Open about what it does with data."). The only rule: "Make meaningful use of the CRS sandbox" and show it working live. Confirm on Devpost.

## 2. Our angle

**One sentence:** In an AI-run accounts-payable department under attack, the controller agent uses CRS identity verification to catch a ghost or synthetic-identity employee who has a valid HR record and a clean bank account, and turns a CRS mismatch into a hold on that person's next reimbursement, using only sponsor-pinned fictional identities.

**30-second version (CRS judges):**
> Ghost employees are one of the oldest payroll and expense frauds, and HR records can be faked. Red Ledger is a sandbox where an AI controller, blue, guards an AI-run finance team. We gave blue a CRS identity check: during its daily audit it takes each newly onboarded employee who has an operator-bound CRS test persona and calls TransUnion identity verification through the CRS sandbox. A clean identity passes. An SSN/name or DOB inconsistency becomes a high-severity hold, and a fraud alert or address-only issue goes to a human, never to an automatic accusation. Missing credentials, timeouts or odd responses mean "unknown", never "fraud". Only the sponsor's fictional personas ever leave our service, and no identity data reaches the model or the event stream. Watch: the mismatched employee's next expense is blocked by the gate.

## 3. Criteria → evidence matrix

| Criterion | What we have | Status | Evidence |
|---|---|---|---|
| **Originality** | Credit-bureau identity verification as an internal-control signal inside an adversarial agent range: an identity check becomes a gate hold on money movement, not a credit decision | ON MAIN (design); PROD-PROVEN and SANDBOX-PROVEN (local) for the call | `blue/CRS.md`; INTEGRATIONS.md §6 B2 |
| **Usefulness** | Targets a real AP/payroll fraud: an employee with a valid-looking HR record whose identity doesn't check out. CRS supplies the hold that the existing heuristics (`no_hr_record`, shared bank account) can't, because fixtures keep HR valid and accounts distinct on purpose | ON MAIN | `battlefield/fixtures/crs-personas.json`; `blue/CRS.md:61-63` |
| **CRS at the core** | One CRS product: `POST /transunion/identity-manager-verification/basic` after `POST /users/login`. Response codes 2201/2202/2301 → mismatch (hold), 2101/2401 → review (human), empty messages → verified. In this scenario CRS is the only source of the hold | PROD-PROVEN (ep_9cbc3362d44e) and SANDBOX-PROVEN (local) for the call, the flag and the gate block | `blue/audit/crs.py:15-54`; #125; #134; #102 (ep_0181eda1c921); #197 (ep_9cbc3362d44e) |
| **It really works (live demo, end to end)** | On prod, with blue's live Droid audit: `make prod-crs-episode SEED=42 DAYS=2` printed PASS (ep_9cbc3362d44e): CRS mismatch → high flag raised by the model → P12's next expense blocked, P01/P16 paid. Locally, the same chain with the keyless audit and `billable:false` ×19 (ep_0181eda1c921). No frontend view. The table demo is the same prod command run live | **PROD-PROVEN** (one run); live at the table still to do, see §0 | #197 (ep_9cbc3362d44e), #195, #102 (ep_0181eda1c921), #125, #134, #139 |
| **Responsible** | Pinned fictional personas only; operator-only immutable bindings; name must match persona; unknown on any failure; one login attempt, never retried; ≤10 checks per audit with hard timeouts; no raw identity in model input, events or logs; DRY_RUN never calls CRS; `billable:false` verified | ON MAIN; verified in code (§4.4) | `blue/audit/crs.py`, `blue/audit/tools.py:220-260`, `blue/audit/evidence.py:299-328`, `battlefield/extensions/blue_crs.py`, `contracts/ext/blue/01_crs_profiles.sql` |
| Best Identity / Fraud fit | Fraud and identity-theft protection for a business, inside an attacker-vs-controller sandbox | ON MAIN | above |
| Best Financial AI Agent fit | Blue's live Droid audit (`gpt-5.4-mini`) chose to call `crs_identity_check` on both days of the prod run and raised the CRS finding through `raise_flag`; the gate then held P12's next expense. The model sees status counts and finding ids only; the service picks who is checked and the provider decides the status | PROD-PROVEN (one 2-day run, 3 personas) | ep_9cbc3362d44e; `blue/audit/agent.py:28-37,141-155`; #195; CHANGELOG Finding (blue's seven tool IDs) |

## 4. What we have, in detail

### 4.1 Why employees, not vendors `ON MAIN`

The original plan (B2) was EIN/vendor verification. The published CalHacks OpenAPI exposes personal identity checks, not an EIN business-verification endpoint, so B2 was redesigned on 2026-10-24 to check synthetic **employee** identities (INTEGRATIONS.md §6 B2; `blue/CRS.md:3`). It fits the ghost-employee threat in the range: red's `ghost_employee` scheme adds a never-onboarded contractor who files expenses (`red/schemes/ghost_employee.py`).

**Honesty point:** the live red attacker does **not** drive the CRS scenario. Red's ghost employees get random plausible names that aren't sponsor personas, and the policy forbids sending arbitrary identities ("Unmatched identities can reach real vendors, even in the sandbox", `blue/CRS.md:36-37`). Red's ghost employees are caught by `no_hr_record` instead (`blue/gate/rules.py:377-385`; `red_writes.py:214`). The CRS scenario is **operator-seeded**: three employees named exactly after the sponsor personas, with valid HR records and distinct accounts, so CRS, not an existing heuristic, supplies the hold.

### 4.2 Data flow, step by step `ON MAIN` (PROD-PROVEN end to end with the live audit, ep_9cbc3362d44e; SANDBOX-PROVEN locally, ep_0181eda1c921)

On prod, `make prod-crs-episode SEED= [DAYS=]` does steps 1-2 itself on a fresh, unstarted enforce episode, then steps the days (`deploy/PROD-OPS.md`).

1. **Seed (operator).** Create an episode but don't start it. `make fixtures EP=<ep> FILE=battlefield/fixtures/crs-personas.json` calls the operator-only `POST /api/episodes/{id}/fixtures` (#124 contract, #130 route; `battlefield/app/api/fixtures.py`). That writes MARGARET OKAFOR, VICTOR ANAND and SAMUEL OYELARAN as `origin='sim'` employees (`hr_record: true`, `active`, `start_day: 0`, distinct accounts `CRS-P01-…`, `CRS-P12-…`, `CRS-P16-…`) plus one expense each (day 2). The route refuses agents, refuses a running episode (409), and refuses any bank-account collision (409, nothing written).
2. **Bind (operator).** `PUT /api/x/blue/crs/episodes/{episode_id}/employees/{employee_id}` with `{"persona_id":"P01"}` and the operator token, no `X-Agent` (`battlefield/extensions/blue_crs.py:22-39`). `persona_id` is `Literal["P01","P12","P16"]` (line 19) and the table has `CHECK (persona_id IN ('P01','P12','P16'))` (`contracts/ext/blue/01_crs_profiles.sql`). A binding is immutable: re-binding to a different persona returns 409 (line 36). The bind emits `x.blue.crs_profile_bound` with only `employee_id` (line 38). Nothing is assigned automatically from provenance, scoring or expected results (`blue/CRS.md:17`).
3. **Audit (blue, end of day).** Blue's audit calls `crs_identity_check` (`blue/audit/tools.py:220-260`). It takes active employees onboarded in the last 7 days (`0 <= day - start_day < 7`). It checks at most 10 per audit, and only while enough deadline is left for the check plus the report (`CHECK_TIMEOUT + 2 + REPORT_RESERVE`). Results are cached per snapshot, so repeated tool calls don't re-query.
4. **Profile read.** Blue reads its own episode's binding: `GET /api/x/blue/crs/employees/{id}` via `LedgerClient.get_extension("blue", …)` with a 2 s timeout (`tools.py:242-243`; route `blue_crs.py:42-45`, `allow("blue", operator=False)`, scoped to the caller's `X-Episode`).
5. **Name gate.** `CRSClient.verify` returns `unknown` unless DRY_RUN is off (or `CRS_LIVE` is set), credentials are configured, the persona exists, and the employee's name equals the persona's full name case-insensitively (`blue/audit/crs.py:67-76`).
6. **Call.** One login per client lifetime (`POST {BASE}/users/login`), latched **before** I/O, then `POST {BASE}/transunion/identity-manager-verification/basic` with the **pinned persona body**, never ledger data (`crs.py:77-97`). Base is `https://api-sandbox.stitchcredit.com/api` (`crs.py:15`). Timeouts: 7 s overall (`asyncio.timeout(CHECK_TIMEOUT)`), 3 s per HTTP call, `follow_redirects=False`, `trust_env=False`.
7. **Normalize** (`parse_identity`, `crs.py:27-54`). Evidence counts only from exactly one `idManagerVerification` product with `status == "DELIVERED"` and `searchStatus` in {CLEAR, HIT} and well-formed `messages`. Any code outside {2101, 2201, 2202, 2301, 2401} → unknown. 2401, or 2101 alone → `review`. Any of 2201/2202/2301 → `mismatch`. No messages → `verified` (sponsor note "messages: empty = verified"; the live P01 probe returned HIT + empty, and #125 fixed the parser, which had required CLEAR).
8. **Finding.** Only `mismatch` creates `crs_employee_identity_mismatch`, severity **high**, family `identity`, fixed text "CRS reports an employee identity inconsistency; independent HR review is required." (`blue/audit/evidence.py:314-328`). `review`, `verified` and `unknown` create nothing. The audit report counts "CRS unknown/step-up" (`tools.py:341`).
9. **Flag.** The audit raises the finding through `raise_flag(finding_id)`. On prod the live model did this itself (ep_9cbc3362d44e); its streamed arguments first needed #195, which lets them complete before agentkit's strict identity check binds the call. That tool takes only a service-defined finding id: "No arbitrary entity, severity or reason" (`tools.py:262-280`).
10. **Hold on the next gated action.** Blue's existing `already_flagged_high` rule blocks an expense approve/pay when a high-severity flag sits on the expense or its employee (`blue/gate/rules.py:388-401`). `/gate` makes no CRS call and gains no latency (`blue/CRS.md:31-32`). **Gap found and fixed:** in the #134 run battlefield's `_expense_context` sent no `flags`, so `req.context.get("flags", [])` was empty and step 10 never fired. #139 (ae822a1) adds the employee + expense flags query, the same pattern `_invoice_context` uses (`battlefield/app/api/green_writes.py` `_expense_context`, `"flags": flags`). **Re-proven end to end with real CRS** in ep_0181eda1c921: P12's day-1 expense blocked with `already_flagged_high` (#102), and again on prod with the live audit in ep_9cbc3362d44e (#197).

### 4.3 Modes and switches `ON MAIN`

| Setting | Effect | Source |
|---|---|---|
| `DRY_RUN=true` (blue keyless) | keyless audit runs; CRS is **not** called even with credentials | `tools.py:235`; `blue/CRS.md:6-8` |
| `CRS_LIVE=true` (shell export only, acceptance-only, default off) | lets the keyless audit call the sandbox; DRY_RUN semantics and `/gate` unchanged. This is how ep_0181eda1c921 ran | `crs.py:103-105`; #120; README §11 (#128) |
| `DRY_RUN=false` (blue's live Droid audit, prod since #157) | the audit is a live Droid turn; `crs_identity_check` calls CRS for bound personas when credentials are set. Exercised on prod in ep_9cbc3362d44e (no `CRS_LIVE`) | `blue/audit/agent.py:141-155`; `crs.py:67-76`; #197 |
| `CRS_USERNAME` / `CRS_PASSWORD` | sandbox login; empty → `unknown`. Passed only to blue | `docker-compose.yml:136-138`; `deploy/ENVIRONMENT.md:95` |
| `CRS_API_KEY` | legacy placeholder, unused | README §11 |
| Blue live Droid audit | **enabled** since #157 (prod `DRY_RUN_BLUE=false`, `gpt-5.4-mini`) | `blue/audit/agent.py:150-155`; #78 |

`CRS_LIVE` appears in no compose file, and prod doesn't need it: the live audit opens the check by itself. The
credentials reach blue on prod (production secrets → `deploy.yml:63-64` → `render-env.sh:119-120` →
`docker-compose.yml:136-137`), and the prod run shows they are set there. The operator setup of §4.2 steps 1-2 is
what `make prod-crs-episode` adds (#197). Without it, as in every ordinary prod episode, the tool returns all-unknown
and calls nobody.

### 4.4 Responsibility, verified in code `ON MAIN`

| Commitment | Verified at |
|---|---|
| Only sponsor-pinned fictional personas leave the service. The request body is the exact persona JSON from `@crscreditapi/crs-calhacks-mcp-server@1.1.2` test data, without expected decisions. Test SSNs are 666-prefixed (an SSN area never issued) | `blue/audit/crs.py:18-19,91-93`; `blue/audit/crs_personas.json` (3 keys); `blue/CRS.md:34-36` |
| Never arbitrary identities: binding limited to P01/P12/P16 at the API and the DB; the name must equal the persona or the result is unknown | `blue_crs.py:19`; `01_crs_profiles.sql`; `crs.py:69-76` |
| Operator-only, immutable bindings; blue reads only its own episode; no assignment from hidden provenance or expected outcomes | `blue_crs.py:22-45`; `blue/CRS.md:12-17` |
| Unknown on missing credentials, timeouts, malformed or unexpected responses, unknown codes | `crs.py:30-54,69-76,98-100`; `tools.py:232-247` |
| Unknown and step-up are never allegations: only `mismatch` creates a finding; review means human review | `evidence.py:314-328`; tool description at `tools.py:220` |
| No retries on login failure: login attempted once, latched before I/O; a 401 clears the token, and later calls return unknown instead of logging in again | `crs.py:80-90,94-95` |
| Bounded calls: ≤10 checks per audit, 2 s profile read, 7 s check, deadline reserve for the report | `tools.py:233-243`; `crs.py:17,78-79` |
| No raw identity in model input: the tool returns only status counts; the model sees `model_view` (counts, coverage, findings with entity ids and fixed service text), and "No source prose, names, invoice numbers, bank details" | `tools.py:259-260`; `evidence.py:299-311` |
| No raw identity in events or logs: exceptions are swallowed with no body, credential or provider prose logged; the bind event carries only `employee_id`; tool-result narration is the sanitized tool output (#85) | `crs.py:98-100`; `blue_crs.py:38`; #85 |
| No credentials in the repo, images or browser vars; secrets only at runtime | AGENTS.md §3 inv. 9; #63 (verifier: "CRS creds are empty-default, Blue-only in compose, production-environment secrets only, never NEXT_PUBLIC/build args") |
| Sandbox use is non-billable, checked after every run | `blue/CRS.md:60,96-97`; #134 |
| Tests mock all CRS I/O | `blue/tests/test_crs.py`, `test_crs_live.py` (15 tests, #120), `test_crs_profiles.py`; `battlefield/tests/test_crs_runtime.py`, `test_fixtures_db.py` |

### 4.5 Live evidence log `PROD-PROVEN` / `SANDBOX-PROVEN (local)`

- **Probe, 2026-10-24 ~21:49Z** (M, own credentials, approved scope P01/P12/P16 only; Ad's approval on #102 at 20:32Z): one latched login, one identity POST per persona. P01 MARGARET OKAFOR: DELIVERED, HIT, zero messages. P12 VICTOR ANAND: mismatch (2201/2202/2301 family). P16 SAMUEL OYELARAN: review (2101/2401 family). A P01 re-request came back `CACHED`. `/users/logs`: all 4 entries `billable:false`. That run found the parser bug fixed in #125 (`blue/CRS.md:88-100`).
- **Episode, ep_e1d35dfb24b1, ~22:27Z** (M; `make local-stack BLUE=real`, keyless audit, `CRS_LIVE=true`, fixtures + operator binds, 2-day enforce, stepped): day-0 expenses for all three paid ("the check itself blocks nothing"). The day-0 audit raised exactly one high-severity employee flag, on P12. P01 and P16 stayed flag-free through day 1, with no duplicate flags. Two audit reports posted. `/users/logs`: 13 identity entries, all `billable:false`. **P12's day-1 expense paid**, so the hold didn't fire (#134; #102). That finding led to #139.
- **Acceptance, ep_0181eda1c921, 2026-10-25 ~00:09Z** (M; driver `crs_episode_acceptance.py --allow-provider-call --blue-external`, stack at main 34fdbdf, real blue, live CRS sandbox, 2-day enforce): day-0 expenses for P01/P12/P16 paid (flags not raised yet, as designed). Blue's audit flagged P12 (provider mismatch); P01/P16 stayed flag-free. **P12's day-1 expense blocked with `already_flagged_high` in `rules_fired`.** P01/P16 day-1 expenses paid (no false positives). Two audit reports posted. `/users/logs`: 19 identity checks, all `billable:false`. `acceptance_passed: true`, exit 0, no failure codes (#102; #78).
- **First prod attempt, ep_c2c98b2da583, 2026-10-25** (`make prod-crs-episode`): FAILED. Blue's live `raise_flag` calls were refused by agentkit's strict identity check: `gpt-5.4-mini` streams tool arguments and the first event carries `{}`, so the call was bound before its arguments arrived. Fixed in #195 (streamed arguments complete before identity binding).
- **Prod live-audit acceptance, ep_9cbc3362d44e, 2026-10-25 ~05:40Z** (`make prod-crs-episode SEED=42 DAYS=2`, #197; enforce, seed 42, 2 days, blue's live Droid audit on `gpt-5.4-mini`): the command seeded the persona employees through the operator fixtures route and bound them, then stepped both days. Blue's audit called `crs_identity_check` on day 0 and day 1. The sandbox reported an identity mismatch for P12, and the model raised the HIGH employee flag through `raise_flag`. On day 1 the gate blocked P12's expense (`expenses.approve` → block, `rules_fired: ["already_flagged_high"]`, enforced). P01's and P16's expenses all paid. Two audit reports posted; blue's audit credits 3,985 (day 0) and 5,318 (day 1). Result **PASS**. Recording: `docs/recordings/crs-live-ep_9cbc3362d44e.jsonl`. The provider's `/users/logs` was not part of this run's evidence.
- Not run yet: the demo live in front of a judge.

## 5. In flight / planned

| Item | Owner | Status | If it doesn't land, say |
|---|---|---|---|
| **P6 CRS live demo** | M / Ad | PASSED on prod with the live audit (ep_9cbc3362d44e, #197); local acceptance PASSED earlier (ep_0181eda1c921). The demo live at the table is still to do | "Recorded on prod 2026-10-25 (ep_9cbc3362d44e); live at the table on request" |
| ~~Flags in `_expense_context`~~ | Ad | Done: #139 | — |
| ~~End-to-end re-run~~ | M | Done: ep_0181eda1c921 (#102) | — |
| ~~CRS on prod~~ | Ad | Done: `make prod-crs-episode` (#197) seeds and binds the personas itself; PASS in ep_9cbc3362d44e | — |
| ~~CRS through blue's live Droid audit~~ | Ad / M | Done: ep_9cbc3362d44e, after the #195 fix | — |
| CRS beat in the pitch / a CRS view in the frontend | R | not planned | Demo at the CRS table from a terminal, not in the four-laptop show |
| P4 / P7 (context) | M / Ad | Blue audit LIVE; green keyless by decision. Public read-only site LIVE (P7) | See docs/devpost/README.md |

## 6. Demo beats for this track

R's pitch (`frontend/docs/pitch-script.md`) has **no CRS beat**, and ordinary prod episodes have no bound personas, so no CRS call happens in the four-laptop show. Treat CRS as a **separate 60-90 s table demo for CRS judges**, plus at most one sentence in Blue's minute.

**Table demo (a laptop set up for `deploy/prod.sh`, per `deploy/PROD-OPS.md`; nothing else running on prod).** The same command that produced ep_9cbc3362d44e:

| t | On screen | Say |
|---|---|---|
| 0:00 | `battlefield/fixtures/crs-personas.json` | "Three new hires with valid HR records and their own bank accounts. Nothing a rules engine would flag. The names are CRS's fictional test personas. We never send anyone else." |
| 0:15 | `make prod-crs-episode SEED=42 DAYS=2`: creates the episode on prod, seeds and binds the personas, steps day 0 | "This is our production deployment. Blue's daily audit is a live agent, and it calls TransUnion identity verification through the CRS sandbox for each new hire." |
| 0:35 | the summary: P12 mismatch → one high flag; P01 and P16 no CRS finding; blue's `crs_identity_check` calls by day | "Clean identity passes. An SSN/name inconsistency becomes a hold. A fraud alert or address issue goes to a human. We don't accuse on uncertainty." |
| 0:55 | `day1_gate_verdicts`: P12's expense blocked, `already_flagged_high`; P01/P16 paid; `PASS` | "The CRS finding stopped the money: the next reimbursement to that identity is blocked at the gate." |
| 1:10 | (talk) | "The model never sees an SSN: the tool hands it status counts and a finding id, and it can only raise a finding the service produced." |

**Alternative:** the local driver on a laptop stack (`make local-stack BLUE=real`, credentials and `CRS_LIVE=true` exported in the shell, never `.env`; `blue/tests/crs_episode_acceptance.py --allow-provider-call --blue-external`). That path also reads `/users/logs` for `billable:false`, but its audit is the keyless one, so it doesn't show the live agent.

**Fallback if the sandbox or prod fails live:** show the recording of ep_9cbc3362d44e (`docs/recordings/crs-live-ep_9cbc3362d44e.jsonl`, or replay it with `POST /replays/{id}/play` per `docs/recordings/README.md`), **labelled on screen "recorded on prod, 2026-10-25"**. Retry once at most: the sandbox login has flapped for a few minutes after heavy use (#78), and blue logs in once per process with no retry, so a lapsed login means a blue restart (§0). Under the challenge's only rule, a recording is a fallback, not a substitute.

**In the four-laptop pitch (Blue's minute), optional:** one line after "Once a day I also audit the books and freeze suspicious vendors": "and I check new hires against CRS identity data. A mismatch puts a hold on their next payout." Don't click anything for it on stage.

Optional, `UNVERIFIED`: open `/backstage/blue` on app.redledger.us while the table run steps, to show the flag and the verdict. Nobody has checked how it renders this run.

## 7. Devpost copy, paste-ready (CRS angle)

Paste-ready at GO (§0). It says "on our production deployment" and "live AI agent" because ep_9cbc3362d44e showed both; don't write "we demoed it live" until the table demo has happened.

**Inspiration**
Ghost employees and synthetic identities are a classic way money leaves a company, and as AI agents take over finance back-office work, someone has to check who is actually on the payroll. We wanted the AI controller in our finance sandbox to verify identities the way a careful auditor would, with real identity data and without ever treating a person unfairly on a hunch.

**What it does**
Red Ledger is a sandbox where an AI finance clerk pays bills, an AI attacker tries to steal, and an AI controller (blue) guards the money. With CRS, blue's daily audit, a live AI agent, checks each newly onboarded employee who has an operator-assigned CRS test persona against TransUnion identity verification in the CRS sandbox. A verified identity passes. An SSN/name or DOB inconsistency raises a high-severity hold on the employee, which blocks their next expense reimbursement at the gate. A fraud alert or address-only issue is sent for human review. Anything uncertain is reported as unknown, never as fraud. On our production deployment, in a recorded two-day run with three fictional test personas, the controller's agent called the CRS check, raised a hold on the mismatched identity, and that person's next expense was blocked at the gate while the other two were paid.

**How we built it**
Blue's daily audit is an agent on Factory's Droid SDK. Its tool `crs_identity_check` logs in to the CRS sandbox once, calls `transunion/identity-manager-verification/basic` with the sponsor's pinned fictional persona, and normalizes the response codes into verified, mismatch, review or unknown. Only a mismatch becomes a finding. The agent sees status counts and a finding id, never identity data, and can raise only a finding the service produced. The finding becomes a flag that blue's existing gate rule enforces on the next money movement, so the gate itself never calls CRS and stays fast. An operator binds personas to synthetic employees through an operator-only, immutable route. Blue reads only its own episode's bindings.

**Challenges we ran into**
The CRS API exposes personal identity checks, not business EIN lookups, so we redesigned the control from vendors to employees. Our first live probe showed the clean persona returns HIT with no messages, which our parser treated as unknown. We fixed it to match the sponsor's "messages: empty = verified" semantics. Our first end-to-end run then showed the flag landing correctly but not reaching the expense gate's evidence. We fixed the gate context, re-ran it against the live sandbox, and the mismatched identity's next expense was blocked while the other two paid. When we moved it to the live agent on production, our first run failed: the model streams its tool arguments, and our strict tool-call identity check bound the call before they arrived. We fixed that, and the next production run passed.

**Accomplishments we're proud of**
A responsible-by-construction integration: only sponsor-pinned fictional identities ever leave the service, one login attempt with no retry loop, hard timeouts, at most ten checks per audit, unknown on any failure, and no identity data in the model's input, our events or our logs. Every sandbox call we checked was `billable:false`.

**What we learned**
An identity signal is only useful as a control if you are strict about what it does not mean. A fraud alert is a reason to ask, not to accuse.

**What's next**
More test identities and longer runs, a CRS view in our dashboard, and CRS evidence for vendor onboarding if a business-verification product becomes available in the sandbox.

**Built with:** crs-api, transunion, python, fastapi, httpx, pydantic, postgresql, docker, factory-droid-sdk, next.js (`crs-api` matches the main Devpost list; if Devpost suggests a sponsor tag, use that)

**Why this fits Best Identity / Fraud Innovation (prize opt-in box)**
Red Ledger protects a business from ghost-employee and synthetic-identity fraud inside an AI-run finance team. CRS identity verification is the evidence that turns a new hire with a clean HR record into a hold on their next payout, and we showed that hold blocking the payment end to end against the live sandbox, on our production deployment, driven by the controller's live agent. The integration is built to be fair and private: fictional sponsor personas only, uncertain results never become accusations, and no identity data reaches the AI model.

**Why this fits Best Financial AI Agent (prize opt-in box)**
Blue, our controller, is an AI agent that does real audit work on a live finance ledger: each day it reviews the books, calls its tools, raises holds and posts a report. CRS identity verification is one of those tools. In a recorded two-day run on our production deployment with three fictional test personas, the agent called the CRS check on both days, raised the hold the service derived from the CRS mismatch, and the gate blocked that person's next expense while the other two were paid. The agent decides to check and acts on the result; CRS decides the identity status, and the agent never sees identity data.

## 8. Claims ledger

**Safe to say**
- Blue authenticates to the CRS sandbox and calls TransUnion identity-manager verification for the three sponsor personas P01/P12/P16 (`crs.py`; #125).
- Live probe results were verified / mismatch / review for P01 / P12 / P16 (#125; `blue/CRS.md` "Sandbox probe evidence").
- "On our production deployment, blue's live AI agent called the CRS check and raised the hold": ep_9cbc3362d44e, one 2-day run, PASS (#197).
- "The CRS finding stopped the money": P12's next expense was blocked with `already_flagged_high`, and P01's and P16's paid, on prod (ep_9cbc3362d44e) and on the local stack (ep_0181eda1c921).
- In every recorded episode, the CRS mismatch flagged the right employee and none of the others (ep_e1d35dfb24b1, ep_0181eda1c921, ep_9cbc3362d44e).
- Every sandbox call we checked was `billable:false` (4 + 13 + 19 entries, local runs; #125; #134; #102).
- Only pinned fictional personas are sent; one login attempt, never retried; unknown on failure; no identity data in model input, events or logs (§4.4).
- The gate never calls CRS (`blue/CRS.md`).

**Say with this caveat**
- "Live on prod": one recorded 2-day run (ep_9cbc3362d44e), set up by an operator command. Ordinary prod episodes have no bound personas and make no CRS call. "Live at the table" only if it happened.
- "Our AI agent uses CRS": the model chooses to call `crs_identity_check` and raises the resulting finding by id. The service decides who is checked and CRS decides the status; the model never sees identity data.
- "Acceptance passed": one prod run (ep_9cbc3362d44e) and one local run (ep_0181eda1c921), each 2 days with 3 pinned personas, plus the earlier local ep_e1d35dfb24b1 that found the gate gap.
- "Non-billable": checked on the local runs; the prod run's `/users/logs` wasn't part of its evidence.
- "Catches ghost employees": operator-seeded persona employees. Red's own ghost employees are caught by `no_hr_record`, not CRS.

**Do NOT say**
- "CRS blocks fraudulent payments" in general: it blocked one bound persona's next expense in 2-day acceptance episodes. Say that.
- "The agent always catches it" or "every run": one prod run passed (and the first prod attempt failed before #195).
- "Every prod episode checks identities": only runs with operator-bound personas do.
- "The AI verifies identities" / "the AI decides who is fraudulent": CRS supplies the status, the service turns it into a finding.
- "We demoed it live" in the Devpost text before the table demo has happened.
- "Verifies vendors / EINs" (dropped, no such endpoint).
- "Checks every employee" (only bound personas onboarded within 7 days, ≤10 per audit).
- Any credential, token, or provider response body.

## 9. Likely judge questions → answers

1. **Which CRS endpoint?** `POST /users/login`, then `POST /transunion/identity-manager-verification/basic` on `https://api-sandbox.stitchcredit.com/api` (`crs.py:15-16,85-93`).
2. **Why only three identities?** They're the sponsor's fictional test personas. The sandbox can route unmatched identities to real vendors, so sending anything else would be irresponsible (`blue/CRS.md:36-37`).
3. **What happens on a mismatch?** A high-severity `crs_employee_identity_mismatch` finding, which the audit agent raises as a flag on the employee. The gate's `already_flagged_high` then blocks their next expense (ep_9cbc3362d44e on prod; ep_0181eda1c921 locally).
4. **And on a fraud alert?** Review, no hold. 2401, or 2101 alone, maps to `review` (`crs.py:45-46`).
5. **What if CRS is down or credentials are missing?** `unknown`. No finding, and the audit still completes; the report counts unknowns (`crs.py:98-100`; `tools.py:341`).
6. **Does the model see SSNs?** No. The tool returns counts by status, and the model's view excludes names and identity fields (`tools.py:259-260`; `evidence.py:299-311`).
7. **Do you retry login?** No. One attempt, latched before the request. A failed or expired token needs a human and a restart (`crs.py:80-84`; `blue/CRS.md:55-57`).
8. **Is it live on your deployed site?** Yes, for runs set up with bound personas: `make prod-crs-episode` passed on prod with blue's live audit (ep_9cbc3362d44e, 2026-10-25). Ordinary prod episodes have no bound personas, so they make no CRS call.
9. **Did CRS change a decision?** Yes: P12's next expense was blocked with `already_flagged_high`, and the other two paid (ep_9cbc3362d44e on prod, ep_0181eda1c921 locally). Our first local acceptance run (#134) found the expense gate wasn't reading flags; we fixed that in #139 and re-ran it.
10. **Why not just use the HR record?** Fakes can have HR records. In our scenario HR is valid and accounts are distinct on purpose, so only CRS can catch it.
11. **Billing?** All sandbox entries we checked were `billable:false` via `/users/logs` (the local runs; the prod run's logs weren't part of its evidence).
12. **What's AI about it?** The surrounding system is three agents; the attacker and the controller's audit run live on Factory's Droid SDK. The CRS check sits in the controller's audit, and its tool is registered in blue's Droid session (`blue-ledger___crs_identity_check`). On prod (ep_9cbc3362d44e) the live model called it on both days and raised the CRS finding; it sees status counts and a finding id, not identities. The earlier local runs used the deterministic audit path.
13. **What if the sandbox is down right now?** Unknown, never fraud: no finding, the audit completes and counts it. For the demo we retry once (the login has flapped after heavy use) and otherwise show the recorded prod run, labelled.

## 10. Numbers sheet

| Number | Meaning | Source | Date |
|---|---|---|---|
| $1,000 / $500 / interview / interview | CRS prize values | calhacks.crscreditapi.com | fetched 2026-10-24 |
| 3 (P01, P12, P16) | pinned fictional personas | `blue/audit/crs_personas.json`; `contracts/ext/blue/01_crs_profiles.sql` | — |
| v1.1.2 | sponsor persona package version | `blue/CRS.md:34-35`; `crs.py:18` | — |
| 1 | login attempts per client lifetime | `crs.py:80-84` | — |
| 7 s / 3 s / 2 s | check timeout / per-HTTP timeout / profile-read timeout | `crs.py:17,79`; `tools.py:242` | — |
| ≤10 | CRS checks per audit | `tools.py:237` | — |
| 7 days | onboarding window checked | `tools.py:230`; `blue/CRS.md:20` | — |
| 2201/2202/2301 → mismatch; 2101/2401 → review | response-code mapping | `crs.py:43-48` | — |
| 4 of 4 `billable:false` | probe log entries | `blue/CRS.md:96-97`; #125 | 2026-10-24 ~21:49Z |
| 13 of 13 `billable:false` | first episode-run log entries (ep_e1d35dfb24b1) | #134; #102 | 2026-10-24 ~22:27Z |
| 1 | high flags raised in ep_e1d35dfb24b1 (on P12) | #134 | 2026-10-24 |
| 0 | later expenses blocked in ep_e1d35dfb24b1 (the gap #139 fixed) | #134 | 2026-10-24 |
| 19 of 19 `billable:false` | acceptance-run identity checks (ep_0181eda1c921) | #102 (M, 00:09Z); #78 | 2026-10-25 |
| 1 / 2 | P12 expenses blocked by `already_flagged_high` / P01+P16 day-1 expenses paid, ep_0181eda1c921 | #102 | 2026-10-25 |
| 2 days, enforce, main 34fdbdf | ep_0181eda1c921 configuration | #102 | 2026-10-25 |
| 15 | new CRS_LIVE tests; 394 blue tests passing | #120 | 2026-10-24 |
| PASS; enforce, seed 42, 2 days | prod live-audit acceptance, ep_9cbc3362d44e (`make prod-crs-episode SEED=42 DAYS=2`) | #197; `docs/recordings/crs-live-ep_9cbc3362d44e.jsonl` | 2026-10-25 ~05:40Z |
| 2 (day 0, day 1) | blue live-audit `crs_identity_check` calls, ep_9cbc3362d44e | recording | 2026-10-25 |
| 1 / all paid | P12 expenses blocked by `already_flagged_high` / P01+P16 expenses, ep_9cbc3362d44e | #197; recording | 2026-10-25 |
| 3,985 / 5,318 | blue live-audit credits, day 0 / day 1, ep_9cbc3362d44e (`gpt-5.4-mini`) | #197; recording (`turn.ended`) | 2026-10-25 |
| 2 | audit reports posted, ep_9cbc3362d44e | recording | 2026-10-25 |
| 7 | blue Droid audit tool IDs incl. `crs_identity_check` | contracts/CHANGELOG.md Finding; `blue/audit/agent.py:28-37` | 2026-10-24 |
