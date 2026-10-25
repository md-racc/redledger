# Red Ledger for the CRS Financial Intelligence Challenge

Status as of 2026-10-25 ~04:45Z, main @ 53adcb7; prod @ fb829e6. Issue #102 is closed (acceptance passed, M, 00:09Z).

Status legend: `LIVE` = running on prod (app.redledger.us) with a real model today. `ON MAIN` = merged and tested, runs keyless, not exercised live on prod. `PLANNED` = not done yet. `NOT DOING` = out of scope. Track-specific tag: `SANDBOX-PROVEN (local)` = exercised against the real CRS sandbox from a team member's local stack, with evidence in a PR or issue, not on prod. `UNVERIFIED` = could not confirm.

---

## 0. Verdict first (read before using anything below)

**CRS live-evidence verdict: GO, conditional only on a live laptop demo at the CRS table.** The end-to-end
acceptance passed against the real CRS sandbox from a local stack (M, #102, 2026-10-25 00:09Z): in episode
**ep_0181eda1c921** (2-day enforce, main 34fdbdf, real blue code), blue's audit flagged P12 on a provider identity
mismatch, and **P12's day-1 expense was blocked at the gate with `already_flagged_high`**. P01's and P16's expenses
paid on both days (no false positives). 19 identity checks, all `billable:false`; `acceptance_passed: true`, exit 0.
That run rests on #139 (the expense gate context carries employee and expense flags). Nothing CRS-related has run on
prod, so the live demo is a laptop on the local stack.

What is proven, and where:

| Claim | Proven? | Where | Evidence |
|---|---|---|---|
| Authenticated login to the CRS sandbox (username/password → bearer) | Yes, local | M's machine | `blue/CRS.md:88-100`; #125; #102 |
| Identity-verification calls for exactly P01, P12, P16 | Yes, local | M's machine | same |
| Live outcome ladder: P01 verified (after the #125 parser fix), P12 mismatch, P16 review | Yes, local | M's machine | #125; `blue/CRS.md:92-95` |
| `billable:false` on the provider's `/users/logs` | Yes: 4/4 (probe), 13/13 (first episode run), 19/19 (acceptance run) | provider logs, operator read | `blue/CRS.md:96-97`; #134; #102 |
| CRS inside a real episode flags only the mismatch persona | Yes, local, twice: ep_e1d35dfb24b1 (#134) and ep_0181eda1c921 | local stack | `blue/CRS.md` "Episode acceptance evidence"; #102 |
| **CRS finding causally blocks a later gated action** (P12's next expense) | **Yes, local**, ep_0181eda1c921: P12's day-1 expense blocked, `already_flagged_high` in `rules_fired`; P01/P16 day-1 paid | local stack, main 34fdbdf + real blue | #102 (M, 00:09Z); #78; the fix it needed is #139 (`battlefield/app/api/green_writes.py` `_expense_context`) |
| Which blue path made the call | Blue's **keyless deterministic audit** with `CRS_LIVE=true`. Inferred from code: at 34fdbdf the live audit still raised before any stream, and the lift (#157) came 2.5 h later | — | `git log 34fdbdf..fb829e6` contains #157 |
| Anything CRS on prod | **No call recorded.** Since #157 blue's audit runs live on prod, so the check is reachable without `CRS_LIVE`, and the CRS credentials are wired to blue from production secrets (whether they are set there is UNVERIFIED here). But it calls CRS only for an active employee onboarded in the last 7 days, bound by an operator to P01/P12/P16, whose name equals the persona's. Seeded employees never qualify (they start 30-2000 days before day 0, have random names and no binding); the fixtures route plus a manual bind would add them, and that hasn't been done on prod | — | `blue/audit/tools.py:229-245`; `blue/audit/crs.py:67-76`; `battlefield/seed/company.py:73-84`; `docker-compose.yml:136-137`; `deploy/render-env.sh:119-120`; `.github/workflows/deploy.yml:63-64` |
| Episode acceptance driver on main | **Yes** (`blue/tests/crs_episode_acceptance.py`, opt-in `--allow-provider-call`, `--blue-external`; not collected by pytest). #150 keeps episode evidence when the provider check fails, and adds a driver-side login retry for the sandbox's 401 windows | — | #134; #150 |
| Frontend or pitch shows CRS | **No** | — | no CRS references in `frontend/` (grep); `frontend/docs/pitch-script.md` |

**Recommendation on whether to submit to CRS** (the challenge's only rule: "Make meaningful use of the CRS sandbox and show it working live in your demo", calhacks.crscreditapi.com):
- **GO** (submit to Best Identity / Fraud Innovation; optionally Most Unexpected Use) **if someone can run the
  acceptance driver live at the CRS judging table** from a laptop with the local stack and the team's sandbox
  credentials exported in the shell (never `.env`). The two earlier conditions are done: the battlefield fix (#139)
  and the end-to-end re-run (ep_0181eda1c921).
- **NO-GO** (nobody can run it live at a table): don't submit to CRS. A recorded-only CRS demo breaks the challenge's
  only rule, even with a passing recorded acceptance run.
- **Rehearse once before the table** on the same laptop: M saw the sandbox login flap (401 windows of a few minutes
  after heavy use, #78). Use the #150 driver, and keep the recorded ep_0181eda1c921 output ready as the fallback.
- **Best Financial AI Agent:** still not recommended. The CRS call that's proven runs in blue's deterministic keyless
  audit, with no LLM on it. Blue's live Droid audit has the CRS tool and its prompt asks it to call
  `crs_identity_check`, but no run has shown the live audit calling CRS with a bound persona. Honest only if someone
  runs the acceptance with blue's live audit and it passes. Even then, the model only sees status counts and
  service-defined finding ids, so its judgment on identity is limited to calling the tool and raising the finding.
  **Best Overall CRS Hack:** don't target it; one endpoint
  and three personas is not "the most impressive product built on CRS".

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
| **Originality** | Credit-bureau identity verification as an internal-control signal inside an adversarial agent range: an identity check becomes a gate hold on money movement, not a credit decision | ON MAIN (design); SANDBOX-PROVEN (local) for the call | `blue/CRS.md`; INTEGRATIONS.md §6 B2 |
| **Usefulness** | Targets a real AP/payroll fraud: an employee with a valid-looking HR record whose identity doesn't check out. CRS supplies the hold that the existing heuristics (`no_hr_record`, shared bank account) can't, because fixtures keep HR valid and accounts distinct on purpose | ON MAIN | `battlefield/fixtures/crs-personas.json`; `blue/CRS.md:61-63` |
| **CRS at the core** | One CRS product: `POST /transunion/identity-manager-verification/basic` after `POST /users/login`. Response codes 2201/2202/2301 → mismatch (hold), 2101/2401 → review (human), empty messages → verified. In this scenario CRS is the only source of the hold | SANDBOX-PROVEN (local) for the call, the flag and the gate block | `blue/audit/crs.py:15-54`; #125; #134; #102 (ep_0181eda1c921) |
| **It really works (live demo, end to end)** | Probe ladder live; acceptance episode live end to end: CRS mismatch → high flag → P12's next expense blocked, P01/P16 paid, `billable:false` ×19. Not on prod; no frontend view. The table demo is the driver run live from a laptop | **SANDBOX-PROVEN (local)**; GO needs the live table run, see §0 | #102 (ep_0181eda1c921), #125, #134, #139 |
| **Responsible** | Pinned fictional personas only; operator-only immutable bindings; name must match persona; unknown on any failure; one login attempt, never retried; ≤10 checks per audit with hard timeouts; no raw identity in model input, events or logs; DRY_RUN never calls CRS; `billable:false` verified | ON MAIN; verified in code (§4.4) | `blue/audit/crs.py`, `blue/audit/tools.py:220-260`, `blue/audit/evidence.py:299-328`, `battlefield/extensions/blue_crs.py`, `contracts/ext/blue/01_crs_profiles.sql` |
| Best Identity / Fraud fit | Fraud and identity-theft protection for a business, inside an attacker-vs-controller sandbox | ON MAIN | above |
| Best Financial AI Agent fit | The CRS tool is in blue's Droid tool list (`blue-ledger___crs_identity_check`), and blue's live Droid audit runs on prod since #157, with a prompt that asks for the CRS check. But the proven CRS run used the keyless deterministic audit, and no live-audit CRS run exists | Keyless path SANDBOX-PROVEN; live-audit path ON MAIN, not exercised with CRS | `blue/audit/agent.py:28-37,141-155`; CHANGELOG Finding (blue's seven tool IDs) |

## 4. What we have, in detail

### 4.1 Why employees, not vendors `ON MAIN`

The original plan (B2) was EIN/vendor verification. The published CalHacks OpenAPI exposes personal identity checks, not an EIN business-verification endpoint, so B2 was redesigned on 2026-10-24 to check synthetic **employee** identities (INTEGRATIONS.md §6 B2; `blue/CRS.md:3`). It fits the ghost-employee threat in the range: red's `ghost_employee` scheme adds a never-onboarded contractor who files expenses (`red/schemes/ghost_employee.py`).

**Honesty point:** the live red attacker does **not** drive the CRS scenario. Red's ghost employees get random plausible names that aren't sponsor personas, and the policy forbids sending arbitrary identities ("Unmatched identities can reach real vendors, even in the sandbox", `blue/CRS.md:36-37`). Red's ghost employees are caught by `no_hr_record` instead (`blue/gate/rules.py:377-385`; `red_writes.py:214`). The CRS scenario is **operator-seeded**: three employees named exactly after the sponsor personas, with valid HR records and distinct accounts, so CRS, not an existing heuristic, supplies the hold.

### 4.2 Data flow, step by step `ON MAIN` (SANDBOX-PROVEN locally end to end, ep_0181eda1c921)

1. **Seed (operator).** Create an episode but don't start it. `make fixtures EP=<ep> FILE=battlefield/fixtures/crs-personas.json` calls the operator-only `POST /api/episodes/{id}/fixtures` (#124 contract, #130 route; `battlefield/app/api/fixtures.py`). That writes MARGARET OKAFOR, VICTOR ANAND and SAMUEL OYELARAN as `origin='sim'` employees (`hr_record: true`, `active`, `start_day: 0`, distinct accounts `CRS-P01-…`, `CRS-P12-…`, `CRS-P16-…`) plus one expense each (day 2). The route refuses agents, refuses a running episode (409), and refuses any bank-account collision (409, nothing written).
2. **Bind (operator).** `PUT /api/x/blue/crs/episodes/{episode_id}/employees/{employee_id}` with `{"persona_id":"P01"}` and the operator token, no `X-Agent` (`battlefield/extensions/blue_crs.py:22-39`). `persona_id` is `Literal["P01","P12","P16"]` (line 19) and the table has `CHECK (persona_id IN ('P01','P12','P16'))` (`contracts/ext/blue/01_crs_profiles.sql`). A binding is immutable: re-binding to a different persona returns 409 (line 36). The bind emits `x.blue.crs_profile_bound` with only `employee_id` (line 38). Nothing is assigned automatically from provenance, scoring or expected results (`blue/CRS.md:17`).
3. **Audit (blue, end of day).** Blue's audit calls `crs_identity_check` (`blue/audit/tools.py:220-260`). It takes active employees onboarded in the last 7 days (`0 <= day - start_day < 7`). It checks at most 10 per audit, and only while enough deadline is left for the check plus the report (`CHECK_TIMEOUT + 2 + REPORT_RESERVE`). Results are cached per snapshot, so repeated tool calls don't re-query.
4. **Profile read.** Blue reads its own episode's binding: `GET /api/x/blue/crs/employees/{id}` via `LedgerClient.get_extension("blue", …)` with a 2 s timeout (`tools.py:242-243`; route `blue_crs.py:42-45`, `allow("blue", operator=False)`, scoped to the caller's `X-Episode`).
5. **Name gate.** `CRSClient.verify` returns `unknown` unless DRY_RUN is off (or `CRS_LIVE` is set), credentials are configured, the persona exists, and the employee's name equals the persona's full name case-insensitively (`blue/audit/crs.py:67-76`).
6. **Call.** One login per client lifetime (`POST {BASE}/users/login`), latched **before** I/O, then `POST {BASE}/transunion/identity-manager-verification/basic` with the **pinned persona body**, never ledger data (`crs.py:77-97`). Base is `https://api-sandbox.stitchcredit.com/api` (`crs.py:15`). Timeouts: 7 s overall (`asyncio.timeout(CHECK_TIMEOUT)`), 3 s per HTTP call, `follow_redirects=False`, `trust_env=False`.
7. **Normalize** (`parse_identity`, `crs.py:27-54`). Evidence counts only from exactly one `idManagerVerification` product with `status == "DELIVERED"` and `searchStatus` in {CLEAR, HIT} and well-formed `messages`. Any code outside {2101, 2201, 2202, 2301, 2401} → unknown. 2401, or 2101 alone → `review`. Any of 2201/2202/2301 → `mismatch`. No messages → `verified` (sponsor note "messages: empty = verified"; the live P01 probe returned HIT + empty, and #125 fixed the parser, which had required CLEAR).
8. **Finding.** Only `mismatch` creates `crs_employee_identity_mismatch`, severity **high**, family `identity`, fixed text "CRS reports an employee identity inconsistency; independent HR review is required." (`blue/audit/evidence.py:314-328`). `review`, `verified` and `unknown` create nothing. The audit report counts "CRS unknown/step-up" (`tools.py:341`).
9. **Flag.** The audit raises the finding through `raise_flag(finding_id)`. That tool takes only a service-defined finding id: "No arbitrary entity, severity or reason" (`tools.py:262-280`).
10. **Hold on the next gated action.** Blue's existing `already_flagged_high` rule blocks an expense approve/pay when a high-severity flag sits on the expense or its employee (`blue/gate/rules.py:388-401`). `/gate` makes no CRS call and gains no latency (`blue/CRS.md:31-32`). **Gap found and fixed:** in the #134 run battlefield's `_expense_context` sent no `flags`, so `req.context.get("flags", [])` was empty and step 10 never fired. #139 (ae822a1) adds the employee + expense flags query, the same pattern `_invoice_context` uses (`battlefield/app/api/green_writes.py` `_expense_context`, `"flags": flags`). **Re-proven end to end with real CRS** in ep_0181eda1c921: P12's day-1 expense blocked with `already_flagged_high` (#102).

### 4.3 Modes and switches `ON MAIN`

| Setting | Effect | Source |
|---|---|---|
| `DRY_RUN=true` (blue keyless) | keyless audit runs; CRS is **not** called even with credentials | `tools.py:235`; `blue/CRS.md:6-8` |
| `CRS_LIVE=true` (shell export only, acceptance-only, default off) | lets the keyless audit call the sandbox; DRY_RUN semantics and `/gate` unchanged. This is how ep_0181eda1c921 ran | `crs.py:103-105`; #120; README §11 (#128) |
| `DRY_RUN=false` (blue's live Droid audit, prod since #157) | the audit is a live Droid turn; `crs_identity_check` would call CRS for bound personas if credentials are set. Not exercised with CRS anywhere | `blue/audit/agent.py:141-155`; `crs.py:67-76` |
| `CRS_USERNAME` / `CRS_PASSWORD` | sandbox login; empty → `unknown`. Passed only to blue | `docker-compose.yml:136-138`; `deploy/ENVIRONMENT.md:95` |
| `CRS_API_KEY` | legacy placeholder, unused | README §11 |
| Blue live Droid audit | **enabled** since #157 (prod `DRY_RUN_BLUE=false`, `gpt-5.4-mini`) | `blue/audit/agent.py:150-155`; #78 |

`CRS_LIVE` appears in no compose file, and prod no longer needs it: the live audit opens the check by itself. The
credentials reach blue on prod (production secrets → `deploy.yml:63-64` → `render-env.sh:119-120` →
`docker-compose.yml:136-137`). What prod lacks is the operator setup of §4.2 steps 1-2 on an unstarted episode
(`make prod-fixtures` exists; there is no make target for the bind, so it's a manual operator `PUT`). Without it the
tool returns all-unknown and calls nobody.

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

### 4.5 Live evidence log `SANDBOX-PROVEN (local)`

- **Probe, 2026-10-24 ~21:49Z** (M, own credentials, approved scope P01/P12/P16 only; Ad's approval on #102 at 20:32Z): one latched login, one identity POST per persona. P01 MARGARET OKAFOR: DELIVERED, HIT, zero messages. P12 VICTOR ANAND: mismatch (2201/2202/2301 family). P16 SAMUEL OYELARAN: review (2101/2401 family). A P01 re-request came back `CACHED`. `/users/logs`: all 4 entries `billable:false`. That run found the parser bug fixed in #125 (`blue/CRS.md:88-100`).
- **Episode, ep_e1d35dfb24b1, ~22:27Z** (M; `make local-stack BLUE=real`, keyless audit, `CRS_LIVE=true`, fixtures + operator binds, 2-day enforce, stepped): day-0 expenses for all three paid ("the check itself blocks nothing"). The day-0 audit raised exactly one high-severity employee flag, on P12. P01 and P16 stayed flag-free through day 1, with no duplicate flags. Two audit reports posted. `/users/logs`: 13 identity entries, all `billable:false`. **P12's day-1 expense paid**, so the hold didn't fire (#134; #102). That finding led to #139.
- **Acceptance, ep_0181eda1c921, 2026-10-25 ~00:09Z** (M; driver `crs_episode_acceptance.py --allow-provider-call --blue-external`, stack at main 34fdbdf, real blue, live CRS sandbox, 2-day enforce): day-0 expenses for P01/P12/P16 paid (flags not raised yet, as designed). Blue's audit flagged P12 (provider mismatch); P01/P16 stayed flag-free. **P12's day-1 expense blocked with `already_flagged_high` in `rules_fired`.** P01/P16 day-1 expenses paid (no false positives). Two audit reports posted. `/users/logs`: 19 identity checks, all `billable:false`. `acceptance_passed: true`, exit 0, no failure codes (#102; #78).
- Not run: anything on prod; a CRS call from blue's live Droid audit; the driver run live in front of a judge.

## 5. In flight / planned

| Item | Owner | Status | If it doesn't land, say |
|---|---|---|---|
| **P6 CRS live demo** | M | Acceptance PASSED locally (ep_0181eda1c921); the table demo from a laptop is pending | "Recorded acceptance run ep_0181eda1c921; live at the table on request". Without a live table run, NO-GO (§0) |
| ~~Flags in `_expense_context`~~ | Ad | Done: #139 | — |
| ~~End-to-end re-run~~ | M | Done: ep_0181eda1c921 (#102) | — |
| CRS on prod (seed and bind personas on prod, confirm the CRS secrets in the production environment) | Ad / M | NOT DOING for the hackathon | "CRS runs on a local stack of the same code; nothing CRS runs on prod" |
| CRS through blue's live Droid audit (would make "Best Financial AI Agent" honest) | M | not run | Don't enter Best Financial AI Agent |
| CRS beat in the pitch / a CRS view in the frontend | R | not planned | Demo at the CRS table from a terminal, not in the four-laptop show |
| P4 / P7 (context) | M / Ad | Blue audit LIVE; green keyless by decision. Public read-only site LIVE (P7) | See docs/devpost/README.md |

## 6. Demo beats for this track

R's pitch (`frontend/docs/pitch-script.md`) has **no CRS beat**, and the four laptops point at prod, where no CRS personas are seeded or bound, so no CRS call happens there. Treat CRS as a **separate 60-90 s table demo for CRS judges**, plus at most one sentence in Blue's minute (only at GO).

**Table demo (laptop with `make local-stack BLUE=real`, credentials and `CRS_LIVE=true` exported in the shell, never `.env`). This is the run the GO depends on:**

| t | On screen | Say |
|---|---|---|
| 0:00 | `battlefield/fixtures/crs-personas.json` | "Three new hires with valid HR records and their own bank accounts. Nothing a rules engine would flag. The names are CRS's fictional test personas. We never send anyone else." |
| 0:15 | run the driver (`blue/tests/crs_episode_acceptance.py --allow-provider-call --blue-external`): seeds, binds, steps day 0 | "Blue's daily audit calls TransUnion identity verification through the CRS sandbox for each new hire." |
| 0:35 | sanitized JSON: P01 verified, P12 mismatch → one high flag, P16 review → no flag | "Clean identity passes. An SSN/name inconsistency becomes a hold. A fraud alert or address issue goes to a human. We don't accuse on uncertainty." |
| 0:55 | day-1 result: P12's expense blocked, `already_flagged_high` in `rules_fired`; P01/P16 paid | "The CRS finding stopped the money: the next reimbursement to that identity is blocked at the gate." |
| 1:10 | `/users/logs` summary: `billable:false` | "Every call is sandbox, non-billable, and the model never sees an SSN." |

**Fallback if the sandbox or the stack fails live:** show the recorded acceptance result of ep_0181eda1c921 (M's summary on #102), **labelled on screen "recorded 2026-10-25, local stack"**. Retry once: the sandbox login has flapped for a few minutes after heavy use (#78), and #150 adds a driver-side login retry. Under the challenge's only rule, a recording is a fallback, not a substitute.

**In the four-laptop pitch (Blue's minute), optional and only at GO:** one line after "Once a day I also audit the books and freeze suspicious vendors": "and I check new hires against CRS identity data. A mismatch puts a hold on their next payout." Don't click anything for it on stage.

Optional, `UNVERIFIED`: run the frontend locally against the local stack so `/backstage/blue` shows the flag and verdict. Not tested by anyone.

## 7. Devpost copy, paste-ready (CRS angle)

Use only at GO (§0: someone runs the demo live at the table). The battlefield fix and the end-to-end run are done, so the old `[only if GO]` markers are gone.

**Inspiration**
Ghost employees and synthetic identities are a classic way money leaves a company, and as AI agents take over finance back-office work, someone has to check who is actually on the payroll. We wanted the AI controller in our finance sandbox to verify identities the way a careful auditor would, with real identity data and without ever treating a person unfairly on a hunch.

**What it does**
Red Ledger is a sandbox where an AI finance clerk pays bills, an AI attacker tries to steal, and an AI controller (blue) guards the money. With CRS, blue's daily audit checks each newly onboarded employee who has an operator-assigned CRS test persona against TransUnion identity verification in the CRS sandbox. A verified identity passes. An SSN/name or DOB inconsistency raises a high-severity hold on the employee, which blocks their next expense reimbursement at the gate. A fraud alert or address-only issue is sent for human review. Anything uncertain is reported as unknown, never as fraud.

**How we built it**
Blue's audit tool `crs_identity_check` logs in to the CRS sandbox once, calls `transunion/identity-manager-verification/basic` with the sponsor's pinned fictional persona, and normalizes the response codes into verified, mismatch, review or unknown. Only a mismatch becomes a finding. The finding becomes a flag that blue's existing gate rule enforces on the next money movement, so the gate itself never calls CRS and stays fast. An operator binds personas to synthetic employees through an operator-only, immutable route. Blue reads only its own episode's bindings.

**Challenges we ran into**
The CRS API exposes personal identity checks, not business EIN lookups, so we redesigned the control from vendors to employees. Our first live probe showed the clean persona returns HIT with no messages, which our parser treated as unknown. We fixed it to match the sponsor's "messages: empty = verified" semantics. Our first end-to-end run then showed the flag landing correctly but not reaching the expense gate's evidence. We fixed the gate context, re-ran it against the live sandbox, and the mismatched identity's next expense was blocked while the other two paid.

**Accomplishments we're proud of**
A responsible-by-construction integration: only sponsor-pinned fictional identities ever leave the service, one login attempt with no retry loop, hard timeouts, at most ten checks per audit, unknown on any failure, and no identity data in the model's input, our events or our logs. Every sandbox call we made was verified `billable:false`.

**What we learned**
An identity signal is only useful as a control if you are strict about what it does not mean. A fraud alert is a reason to ask, not to accuse.

**What's next**
Running the CRS check from blue's live Droid audit (blue's audit is live on our production deployment now, but we haven't run CRS through it), on the production deployment, and adding CRS evidence to vendor onboarding if a business-verification product becomes available in the sandbox.

**Built with:** crs-api, transunion, python, fastapi, httpx, pydantic, postgresql, docker, factory-droid-sdk, next.js (`crs-api` matches the main Devpost list; if Devpost suggests a sponsor tag, use that)

**Why this fits Best Identity / Fraud Innovation (prize opt-in box)**
Red Ledger protects a business from ghost-employee and synthetic-identity fraud inside an AI-run finance team. CRS identity verification is the evidence that turns a new hire with a clean HR record into a hold on their next payout, and we showed that hold blocking the payment end to end against the live sandbox. The integration is built to be fair and private: fictional sponsor personas only, uncertain results never become accusations, and no identity data reaches the AI model.

## 8. Claims ledger

**Safe to say**
- Blue authenticates to the CRS sandbox and calls TransUnion identity-manager verification for the three sponsor personas P01/P12/P16 (`crs.py`; #125).
- Live results were verified / mismatch / review for P01 / P12 / P16 (#125; `blue/CRS.md:92-95`).
- Every sandbox call we checked was `billable:false` (4 + 13 + 19 entries; `blue/CRS.md:96-97`; #134; #102).
- In real episodes on our local stack, the CRS mismatch raised exactly one high-severity flag on the right employee and none on the others (#134; #102).
- "The CRS finding stopped the money": in ep_0181eda1c921, P12's next expense was blocked with `already_flagged_high`, and P01's and P16's paid (#102).
- "End to end against the live CRS sandbox", with "on our local stack".
- Only pinned fictional personas are sent; one login attempt, never retried; unknown on failure; no identity data in model input, events or logs (§4.4).
- The gate never calls CRS (`blue/CRS.md:31-32`).

**Say with this caveat**
- "Live": "live against the CRS sandbox from our local stack", not "on our production deployment". "Live at the table" only if it happened.
- "Agent": blue's keyless audit service made the proven call. Blue's Droid audit is live on prod and has the CRS tool, but hasn't been run with CRS.
- "Acceptance passed": a 2-day episode with 3 pinned personas, one run (ep_0181eda1c921), plus the earlier ep_e1d35dfb24b1 that found the gap.
- "Catches ghost employees": operator-seeded persona employees. Red's own ghost employees are caught by `no_hr_record`, not CRS.

**Do NOT say**
- "CRS blocks fraudulent payments" in general: it blocked one bound persona's next expense in a 2-day acceptance episode. Say that.
- "Running on app.redledger.us": nothing CRS runs on prod (no seeded or bound personas).
- "Our AI agent queries CRS": the proven path has no LLM on it; the live Droid audit hasn't been run with CRS.
- "We demoed it live" in the Devpost text before the table demo has happened.
- "Verifies vendors / EINs" (dropped, no such endpoint).
- "Checks every employee" (only bound personas onboarded within 7 days, ≤10 per audit).
- Any credential, token, or provider response body.

## 9. Likely judge questions → answers

1. **Which CRS endpoint?** `POST /users/login`, then `POST /transunion/identity-manager-verification/basic` on `https://api-sandbox.stitchcredit.com/api` (`crs.py:15-16,85-93`).
2. **Why only three identities?** They're the sponsor's fictional test personas. The sandbox can route unmatched identities to real vendors, so sending anything else would be irresponsible (`blue/CRS.md:36-37`).
3. **What happens on a mismatch?** A high-severity `crs_employee_identity_mismatch` finding and flag on the employee. The gate's `already_flagged_high` then blocks their next expense (ep_0181eda1c921).
4. **And on a fraud alert?** Review, no hold. 2401, or 2101 alone, maps to `review` (`crs.py:45-46`).
5. **What if CRS is down or credentials are missing?** `unknown`. No finding, and the audit still completes; the report counts unknowns (`crs.py:98-100`; `tools.py:341`).
6. **Does the model see SSNs?** No. The tool returns counts by status, and the model's view excludes names and identity fields (`tools.py:259-260`; `evidence.py:299-311`).
7. **Do you retry login?** No. One attempt, latched before the request. A failed or expired token needs a human and a restart (`crs.py:80-84`; `blue/CRS.md:55-57`).
8. **Is it live on your deployed site?** No. Blue's audit is live on prod, but no CRS personas are seeded or bound there. The CRS demo runs the same code on a local stack, live against the CRS sandbox.
9. **Did CRS change a decision?** Yes: P12's next expense was blocked with `already_flagged_high`, and the other two paid (ep_0181eda1c921). Our first acceptance run (#134) found the expense gate wasn't reading flags; we fixed that in #139 and re-ran it.
10. **Why not just use the HR record?** Fakes can have HR records. In our scenario HR is valid and accounts are distinct on purpose, so only CRS can catch it.
11. **Billing?** All sandbox entries we checked were `billable:false` via `/users/logs`.
12. **What's AI about it?** The surrounding system is three agents; the attacker and the controller's audit run live on Factory's Droid SDK. The CRS check sits in the controller's audit, and its tool is registered in blue's Droid session (`blue-ledger___crs_identity_check`). The run we proved used the deterministic audit path, so the model never saw the CRS step.
13. **What if the sandbox is down right now?** Unknown, never fraud: no finding, the audit completes and counts it. For the demo we retry once (the login has flapped after heavy use) and otherwise show the recorded acceptance run, labelled.

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
| 7 | blue Droid audit tool IDs incl. `crs_identity_check` | contracts/CHANGELOG.md Finding; `blue/audit/agent.py:28-37` | 2026-10-24 |
