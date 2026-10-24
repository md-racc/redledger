# INTEGRATIONS.md — sponsor integration runbook

This is a working coordination file for Cal Hacks 13.0 weekend, not permanent repo
documentation. `AGENTS.md` and `GIT.md` govern and win any conflict. It reads top to bottom:
§0 is the file's own lifecycle, §1–§4 is everything you need before acting, §5–§7 is the work
in the order it happens, §8–§10 is reference.

An agent assigned a step reads §1 (files it may touch), §2 (invariants that must stay true),
§3 (is its key present), then its own numbered step. Nothing else.

## §0 Lifecycle

This file deletes itself when the work is done.

- **Deletion condition:** every §5 row submitted, every §6 item merged, every §7 item either
  merged or marked DROPPED.
- **Before deleting, migrate anything durable:** new environment variables into
  `.env.example` and `README.md` §11 (should already be true — `AGENTS.md` §7 requires it per
  PR); architecture that outlives the hackathon into the owning directory's `AGENTS.md`;
  Droid-SDK or sponsor-API findings into `contracts/CHANGELOG.md` under Findings.
- **Deletion PR:** branch `chore/retire-integrations`, one commit
  `chore: retire INTEGRATIONS.md after submission`, one devlog fragment.
- Each phase below ends with a "done when" line so this condition is checkable, not a
  judgement call.

## §1 Ownership and boundaries

Same shape as `AGENTS.md` §2, keyed by integration. Find your row; it names your branch,
owner, and exact file list.

| Step | Integration | Owner | Branch | May create / modify | Cross-area dependency |
|---|---|---|---|---|---|
| B1 | Tiger Data / Timescale | Ad | `battlefield/timescale` | `docker-compose.yml`, battlefield's startup schema-apply path, `battlefield/app/scoring/score.py` | none |
| B2 | CRS Credit API | M | `blue/crs-verification` | `blue/audit/{crs,evidence,tools,snapshot,agent,readiness}.py`, approved fictional fixtures, Blue docs/tests, `battlefield/extensions/blue_crs.py`, `contracts/ext/blue/` | **yes** — runtime/CI wiring in `battlefield/crs-runtime`, root docs in `docs/crs-runbook`; live credentials/profile setup by humans |
| C1 | Atlassian Forge | unassigned | needs Ad's ruling first | new top-level `forge/**`, `battlefield/extensions/fe_*.py` | **yes** — `forge/` is not in `GIT.md` §2's table |
| C2 | Cartesia voice | R | `frontend/voice-escalation` | `frontend/**`, `battlefield/extensions/fe_voice.py`, `contracts/ext/fe/` | none |
| C3 | Bright Data | M | `blue/web-diligence` | `blue/audit/webcheck.py` (new), `blue/audit/evidence.py` | none |
| C4 | Capital One Nessie | Ad | `battlefield/nessie` | `battlefield/seed/company.py`, payment + bank-feed path | none, but it is Ad's critical path |
| C5 | Auth0 | R | `frontend/auth` | `frontend/**` | none |
| C6 | Elastic | M | `blue/search` | `blue/audit/` | none |

An agent on one step does not edit another step's files or another owner's directory. If the
task needs it, stop and hand it to the human — B2's credential/profile setup (P3/P4 below) is the known
instance.

## §2 Invariants (non-negotiable)

Additive to `AGENTS.md` §3.

1. **Absent key = degraded, never broken.** Every integration reads its key from the
   environment and returns a neutral result when it is empty, so `AGENTS.md` §3 invariant 8
   (whole stack runs under `DRY_RUN=true` with no keys) survives, or the integration does not
   merge.
2. **Nothing external on the gate hot path.** `blue/gate/` has a `GATE_TIMEOUT_SEC` budget.
   External HTTP belongs in the once-per-day audit path (`blue/audit/`), which already raises
   flags the next gate reads.
3. **Integrations are evidence, not verdicts.** An external service produces a finding a rule
   consumes; it never returns `block` directly. Keeps `AGENTS.md` §3 invariant 3 true.
4. **No secrets outside the environment.** `AGENTS.md` §3 invariant 9. Each key gets an empty
   `.env.example` entry and a `README.md` §11 row, never a `NEXT_PUBLIC_*` var.
5. **Every integration call emits events** (`agent.tool_call` / `agent.tool_result` via
   `EventEmitter`, per `AGENTS.md` §3 invariant 5).
6. **No integration reads ground truth.** `AGENTS.md` §3 invariant 11 in full — an enrichment
   tool handed to blue's Droid must not become a path to `origin`, `attack_id`, or unfiltered
   `audit_log`.
7. **Timeout, then neutral.** `AGENTS.md` §3 invariant 10. A timed-out integration logs,
   emits, and yields "unknown" — it never fails the turn.
8. **No sponsor API in CI.** CI has no sponsor keys and must not acquire any; every test mocks
   the external call.

## §3 Prerequisites board

Human work — agents cannot create accounts, click through dashboards, or accept terms. Every
blocked step blocks here first.

| # | Prerequisite | Who | Where / what to do | Produces | Lands in | Time |
|---|---|---|---|---|---|---|
| P1 | Devpost project created, repo linked, team joined | R | Devpost | project URL | shared with team | 10m |
| P2 | MLH prize opt-in | R | MLH submission form | eligibility for every `MLH …` row | — | 5m |
| P3 | CRS sandbox login | M | Sponsor account with ROLE_TU_TV; REST base `https://api-sandbox.stitchcredit.com/api` | `CRS_USERNAME` + `CRS_PASSWORD`; no API key required | local environment; prod secrets per `deploy/ENVIRONMENT.md` | 15m |
| P4 | CRS employee profiles bound | M → Ad | create named synthetic employees and explicitly bind approved P01/P12/P16 profiles through the Blue operator extension | episode-scoped employee/profile bindings, not EINs or expected outcomes | `blue_crs_employee_profiles`; no core schema or seed edit required | 15m |
| P5 | Atlassian account + demo site | whoever takes C1 | `forge login`, `forge site provision`, `forge register` | site URL, app id | `forge/manifest.yml`; `api.<domain>` added to its external-fetch permissions | 30m |
| P6 | Node 22 or 24 + `@forge/cli@latest` (v14+) | same | local install | working `forge` CLI | — | 15m |
| P7 | Cartesia key | R | Cartesia dashboard | `CARTESIA_API_KEY` | local `.env` | 10m |
| P8 | Figma criteria re-read | R | sponsor criteria doc | verdict: free claim or needs a build | moves the row between §5 and §7 | 10m |
| P9 | Armadin criteria re-check | Ad | prize page (currently "Coming soon!") | criteria | may change §5 wording | 5m |

- Secrets arrive via the shared vault, never Slack, never a commit (`AGENTS.md` §3 inv. 9).
- A credential prerequisite is done when the credential is in the holder's local environment **and** the variable
  exists empty in `.env.example`, so `DRY_RUN=true` still boots for everyone else.
- An agent that finds its credential absent does not go get one. It implements the neutral-result
  path (§2 invariant 1), notes the blocked prerequisite number in its report, and stops.

## §4 Submission checklist

Devpost entry (P1), 3-minute max demo video, public repo link, MLH opt-in (P2), no API keys
or secrets in the repo (`AGENTS.md` §3 invariant 9), and which README section each sponsor's
judges will look for.

## §5 Phase A — submission text only, no code

Ordered by value. Each row: the claim, the proof already in the repo, what the submission
text says. Blocked only by P1/P2.

| A# | Prize | Value | Proof already in the repo | Submission must say |
|---|---|---|---|---|
| A1 | **Hyphenate** — Autonomous Systems for Finance | $8k / $5k / $3k | "realistic data" → `battlefield/seed/company.py` (90 seeded days); "limited access, a clean record of its work, knowing when to ask" → `AGENTS.md` §3 invariants 1, 5, 11, the `audit_log`, and the preparation → gate → escalation path (green prepares each money move, blue decides, a human resolves escalations; `contracts/ledger-api.yaml` `/preparations`); "something new" → the red agent plus **evolution**: lineages of episodes where agents get debriefs and after-action reviews and rewrite their playbooks (`docs/EVOLUTION-DESIGN.md`; `make evolve` / `make evolution-report`; a keyless 3-generation run shows red evading in generation 2 and blue learning rules that catch it in generation 3); "the moment" → a `gate.verdict` block on a live bank swap | Answer "would you hire it, for which seats" with the gate, the audit log, the escalation path, then how it improves across generations — in that order |
| A2 | **Factory** — Droid SDK | $2000 + credits | Three `agentkit.DroidAgent` subclasses; **red runs live on prod** (`gpt-5.4-mini`, reasoning `low`; ~11 s and ~2.6k Factory credits per turn; moved off `gemini-3.8-flash` after it stalled live red turns, Finding in #118); spend capped per episode (`MAX_CREDITS_PER_EPISODE`) and per lineage (`make prod-evolve ... MAX_CREDITS=`); `restrict_tools` with exact `<agent>-ledger___<tool>` ids, strict tool-use identity and `Autonomy.OFF` for green/blue, each turn on its own loop so the service stays responsive (#79, #84); `agent.thinking`/`tool_call`/`tool_result` rendered live. Green and blue are keyless on prod (`DRY_RUN_GREEN/BLUE`) until their live paths are accepted (#78, #102). Where each session runs and which tools it holds: `README.md` §6 "Where Droid runs" | Point judges at `README.md` §6 "Where Droid runs"; lead with a live episode, not a feature tour; don't claim green/blue run live until #78 clears |
| A3 | **Microsoft** — Grand Prize + Customer Impact | Surface laptops + FDE sessions | CI (per-service tests incl. Postgres, ownership and contracts guards), `.github/workflows/deploy.yml` with an approval gate, per-agent `DRY_RUN_RED/GREEN/BLUE` (red live, green/blue keyless), replayable fixtures, a real VM behind Cloudflare Access, `make prod-*` operations incl. recorded evolution runs | Lead with the deploy pipeline and replay, not the agents |
| A4 | **Armadin** — Best Security Hack | AirPods | Pitch hook: an AI red-team agent attacking a defended agentic finance system (offensive agents vs. a gate), matching Armadin's agent-swarm offensive-security thesis. Criteria still "Coming soon!" (P9) | Submit regardless with the hook; re-check wording once P9 lands |
| A5 | **MLH Vultr** | M5Stack Tab5 | Already the deploy target (`README.md` §13; `VULTR_HOST`/`VULTR_SSH_KEY`) | One line |
| A6 | **MLH Gemini** | Swag kit | No live Gemini use on prod. `blue/gate/llm.py` supports Gemini as one of three gate-LLM providers (gemini, anthropic, openai; `BLUE_GATE_LLM_PROVIDER`, default `gemini` in `.env.example`), but the gate LLM is not enabled on prod (blue is keyless there). Red tried `gemini-3.8-flash` live and moved to `gpt-5.4-mini` after it stalled (#118) | Drop the claim unless blue's gate LLM goes live on Gemini |
| A7 | **MLH Best Use of Gen AI** | Assorted | Live red Droid agent + evolution (`docs/EVOLUTION-DESIGN.md`) | One line, same evidence |
| A8 | **Figma** | Gift cards + recruiter session | R's deck and design work | Blocked on P8 |
| A9 | **MLH Tiger Data** | Stream Deck Mini | True (#98/#100): `events` and `audit_log` are TimescaleDB hypertables keyed `(id, ts)`, plus a `score_timeline` continuous aggregate (1-minute score buckets per episode, real-time); local compose defaults to `timescale/timescaledb:latest-pg16`; CI's `battlefield-timescale` job runs the full battlefield suite on the real image. Prod still runs plain `postgres:16-alpine` | The append-only event stream and audit log live in hypertables; score over time comes from a continuous aggregate; CI proves it on TimescaleDB |

Not submitted, and why:

- **Anthropic.** Criteria are "a named community" and "a real problem you have lived", judged
  on being usable Monday by actual people. A synthetic-company fraud sandbox has no named
  community.
- **MLH GoDaddy Registry / MLH .Tech.** Both require registering the domain through the
  sponsor's registrar. The domain is on Cloudflare.

*Done when:* A1–A7 are in the Devpost submission text; A8 resolved by P8; A9 written if B1 merged.

## §6 Phase B — integrate now, in order

B1 before B2: B1 is an hour and unblocks A9; B2 is blocked on P3 and P4.

**B1. Tiger Data / Timescale — owner Ad, branch `battlefield/timescale`, ~1h, prereq: none**

- *Why:* the product's entire output is an append-only event stream replayed on a time axis.
  `AGENTS.md` §4 already names this as "an image swap and a hypertable on `events` and
  `audit_log`".
- *Files:* `docker-compose.yml` (image → `timescale/timescaledb:latest-pg16`); battlefield's
  startup schema-apply path; `battlefield/app/scoring/score.py`.
- *Design:* `create_hypertable()` on `events` and `audit_log`, guarded so a plain
  `postgres:16` still boots — a failed call logs and continues. Then one continuous aggregate
  backing the score-over-time series `score.py` already computes.
- *Acceptance:* `make test-battlefield`; `make mock-agents` + `make episode` green on both
  images; frontend score chart still renders.
- *Unblocks:* A9.

**B2. CRS Credit API — owner M, branch `blue/crs-verification`, prereq: P3 + P4**

- *Corrected design, approved 2026-10-24:* the published CalHacks OpenAPI exposes personal
  identity checks, not an EIN business-verification endpoint. B2 therefore checks synthetic
  employee identities, not vendors. Business-related response schemas are not lookup routes.
- *Files:* Blue's client, service-defined employee finding, no-argument `crs_identity_check`
  tool, snapshot/orchestration hooks, offline registration schema, pinned fictional request
  bodies, and mocked tests; Blue-owned extension routes/table hold operator-bound persona IDs.
  No new gate rule or core contract change is required.
- *Flow:* an operator explicitly binds an employee to P01, P12, or P16. Blue checks matching
  employee names, calls `/transunion/identity-manager-verification/basic` during audit, and
  normalizes the delivered response. SSN/name, DOB/issuance, or deceased-identity inconsistencies
  produce `crs_employee_identity_mismatch`; existing flags and `already_flagged_high` stop
  later expense payments. Address-only mismatches and fraud alerts require review, not holds.
- *Credentials:* `CRS_USERNAME` / `CRS_PASSWORD` obtain a bearer token through `/users/login`.
  `CRS_API_KEY` is an unused legacy placeholder. Missing credentials, malformed responses,
  timeouts, and DRY_RUN produce `unknown`, never an allegation. Login failures are not retried.
- *Safety:* only exact pinned sponsor fictional requests may leave the service. Unmatched
  sandbox identities can reach real vendors. Never query random seeded people, infer profiles
  from hidden provenance, or substitute expected fixture decisions for a provider response.
- *Prerequisite PRs:* `battlefield/crs-runtime` supplies runtime credentials and corrects CI's
  documented team-extension carve-out; `docs/crs-runbook` updates environment/runbook guidance.
  Merge these before the Blue implementation. Publishing draft PRs does not complete B2.
- *Acceptance:* `make lint test-blue`, independent review, additive schema/profile smoke,
  and clean/mismatch/step-up episodes using valid HR records and distinct payment accounts.
  In the mismatch case, show that the CRS flag, not an existing heuristic, changes the later
  expense gate. Verify sandbox request logs say `billable:false`.
- *Live blocker:* Blue's existing SDK invocation/tool-ID/owner-loop safeguards still disable
  live audit. Do not remove them without proof. Credentials, live SDK readiness, Docker/Postgres
  smoke, and an authenticated sponsor demo remain required, not replaced by mocked tests.
  Durable setup and remaining checks live in `blue/CRS.md`.

*Done when:* both PRs are squash-merged per `GIT.md` §4 and A9 is written.

## §7 Phase C — if someone goes idle

Blanket gate: the `README.md` §14 Saturday 14:00 checkpoint (full 3-day episode in `shadow`
with real agents) must be green first. **Status: BLOCKED** — only red runs live; green's live
handler and blue's live audit are M's remaining steps (tracked in issue #78). CRS sandbox acceptance
and Bright Data live readiness are tracked separately and are not proven by that checkpoint. Each item ends the weekend either merged or marked
**DROPPED** — that is part of the §0 deletion condition.

- **C1 Atlassian Forge — escalation inbox.** Prereq P5 + P6. Design: blue returns `escalate`
  → battlefield opens a Jira issue on the demo site → approver decides in Jira → a Forge
  trigger calls back `POST /api/escalations/{id}/resolve` inside the `ESCALATION_TIMEOUT_SEC`
  window, reaching us over `api.<domain>` declared in `manifest.yml` external-fetch
  permissions. **Extra gate:** Ad rules on the `forge/` top-level directory, which `GIT.md`
  §2's table does not cover. ~4h after prereqs. AirPods Max.
- **C2 Cartesia voice escalation.** Prereq P7. Spoken summary of the pending decision; approver
  answers by voice; answer resolves the escalation. A frontend page plus
  `battlefield/extensions/fe_voice.py`, owned by R alone.
- **C3 Bright Data — web due diligence.** Does this vendor have a registration, a site, an
  address? Second evidence source beside CRS, same audit path, `blue/audit/webcheck.py`.
  **Extra gate:** B2 and its runtime/documentation prerequisites merged — then it reuses the
  finding plumbing. Draft PRs do not clear this gate. Blue's shared live-audit readiness also
  applies to a live Bright Data demo.
- **C4 Capital One Nessie.** Back `payments` and `bank_transactions` with real Nessie accounts
  so reconciliation runs against an external system instead of a self-consistent fiction.
  **Extra gate: do not start.** It rewrites battlefield's payment path, Ad's critical path,
  while core work is open.
- **C5 Auth0.** A verified human identity behind `escalations.resolved_by`.
- **C6 Elastic.** Free-text search over `audit_log` for blue's audit Droid, built from the
  same `agent=green|blue` filtered view blue is already allowed to read (§2 invariant 6).

## §8 Rejected

Coinbase x402 (crypto settlement contradicts an ACH accounts-payable narrative), Fetch.ai
(re-homing agents off the Droid SDK undercuts A2), Convex and Spacetime (we have Postgres plus
a WebSocket), Apify (duplicate of C3), Visa, Meta (off-domain), Notability / Moss / Creao /
Bitdeer / Mana / SpaceXAI-Cursor / Backboard / Snowflake / MongoDB / Solana / Presage /
DigitalOcean / Commit Fellowship.

## §9 Agent briefs

Paste-ready blocks, `AGENTS.md` §10 subagent-skeleton format, for B1, B2, and any C item that
gets started.

```
Role: implementer for B1, branch battlefield/timescale, worktree <path>.
Owner dev: Ad. Prereqs: none.
Files you may create/modify: docker-compose.yml, battlefield's startup schema-apply path,
battlefield/app/scoring/score.py. Nothing else.
Requirement: must work under DRY_RUN=true; a plain postgres:16 image must still boot if the
hypertable call fails — log and continue, never crash startup.
Done means: make test-battlefield passes; make mock-agents + make episode green on both
images; commit on your branch; do NOT push; reply with files changed, tests run, open
questions.
Never: force-push, reset --hard, delete tests, touch another directory.
Task: swap the Postgres image for timescale/timescaledb:latest-pg16, create hypertables on
events and audit_log guarded by a try/except, and add one continuous aggregate backing the
score-over-time series in score.py.
```

```
Role: implementer for B2, branch blue/crs-verification, worktree <path>.
Owner dev: M. Prereqs: P3 (CRS_USERNAME/CRS_PASSWORD) and P4 (explicit fictional employee
profile bindings). Missing credentials -> neutral unknown; report blocked prerequisites,
never read denied .env files or create an account.
Files you may create/modify: the approved B2 list in §1 only. Ad-owned runtime and CI
changes belong on battlefield/crs-runtime; root documentation belongs on docs/crs-runbook.
Contract: employee ID joins the Blue profile extension; approved persona name must match.
raise_flag accepts only service-generated finding IDs; already_flagged_high consumes flags
on later expenses. No EIN endpoint exists in the published CalHacks API.
Requirement: audit-only, exact pinned fictional requests, bounded calls, no raw identities
in model/events, no automatic login retries; DRY_RUN makes no sponsor request.
Done means: required checks/review, schema/profile smoke, authenticated sandbox demo whose
CRS finding causally changes a later gate, and all prerequisite PRs merged. Preserve existing
live SDK safeguards until empirically verified. Do not label mocks or drafts as completion.
Never: force-push, reset --hard, delete tests, call CRS from the gate, use hidden provenance,
query arbitrary consumers, edit another owner's files, deploy, or merge your own PR.
Task: safely enrich employee audit evidence and carry the finding through existing flags.
```
