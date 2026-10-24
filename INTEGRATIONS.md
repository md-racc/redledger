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
| B2 | CRS Credit API | M | `blue/crs-verification` | `blue/audit/crs.py` (new), `blue/audit/evidence.py`, `blue/audit/tools.py`, `blue/gate/rules.py`, `blue/tests/` | **yes** — EIN seeding in `battlefield/seed/company.py` is Ad's |
| C1 | Atlassian Forge | unassigned | needs Ad's ruling first | new top-level `forge/**`, `battlefield/extensions/fe_*.py` | **yes** — `forge/` is not in `GIT.md` §2's table |
| C2 | Cartesia voice | R | `frontend/voice-escalation` | `frontend/**`, `battlefield/extensions/fe_voice.py`, `contracts/ext/fe/` | none |
| C3 | Bright Data | M | `blue/web-diligence` | `blue/audit/webcheck.py` (new), `blue/audit/evidence.py` | none |
| C4 | Capital One Nessie | Ad | `battlefield/nessie` | `battlefield/seed/company.py`, payment + bank-feed path | none, but it is Ad's critical path |
| C5 | Auth0 | R | `frontend/auth` | `frontend/**` | none |
| C6 | Elastic | M | `blue/search` | `blue/audit/` | none |

An agent on one step does not edit another step's files or another owner's directory. If the
task needs it, stop and hand it to the human — B2's EIN seeding (P4 below) is the known
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
| P3 | CRS sandbox key | M | CRS sponsor signup; sandbox base `https://calhacks.crscreditapi.com` | `CRS_API_KEY` + the list of test identities | each dev's local `.env`; prod per `deploy/ENVIRONMENT.md` | 15m |
| P4 | CRS test EINs chosen | M → Ad | pick which test identities map to seeded legit vendors | an EIN list | handed to Ad for `battlefield/seed/company.py` | 15m |
| P5 | Atlassian account + demo site | whoever takes C1 | `forge login`, `forge site provision`, `forge register` | site URL, app id | `forge/manifest.yml`; `api.<domain>` added to its external-fetch permissions | 30m |
| P6 | Node 22 or 24 + `@forge/cli@latest` (v14+) | same | local install | working `forge` CLI | — | 15m |
| P7 | Cartesia key | R | Cartesia dashboard | `CARTESIA_API_KEY` | local `.env` | 10m |
| P8 | Figma criteria re-read | R | sponsor criteria doc | verdict: free claim or needs a build | moves the row between §5 and §7 | 10m |
| P9 | Armadin criteria re-check | Ad | prize page (currently "Coming soon!") | criteria | may change §5 wording | 5m |

- Secrets arrive via the shared vault, never Slack, never a commit (`AGENTS.md` §3 inv. 9).
- A prerequisite is done when the key is in the holder's local `.env` **and** the variable
  exists empty in `.env.example`, so `DRY_RUN=true` still boots for everyone else.
- An agent that finds its key absent does not go get one. It implements the neutral-result
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
| A1 | **Hyphenate** — Autonomous Systems for Finance | $8k / $5k / $3k | "realistic data" → `battlefield/seed/company.py` (90 seeded days); "limited access, a clean record of its work, knowing when to ask" → `AGENTS.md` §3 invariants 1, 5, 11 plus the `escalate` verdict; "something new" → the red agent; "the moment" → a `gate.verdict` block on a live bank swap | Answer "would you hire it, for which seats" with the gate, the audit log, the escalation path — in that order |
| A2 | **Factory** — Droid SDK | $2000 + credits | Three `agentkit.DroidAgent` subclasses doing the product's real work; `restrict_tools` + `Autonomy.OFF` on green; `agent.thinking`/`tool_call`/`tool_result` rendered live | A README section naming where Droid runs and which tools each session holds; lead with a live episode, not a feature tour |
| A3 | **Microsoft** — Grand Prize + Customer Impact | Surface laptops + FDE sessions | CI, `.github/workflows/deploy.yml`, DRY_RUN, replayable fixtures, a real VM | Lead with the deploy pipeline and replay, not the agents |
| A4 | **Armadin** — Best Security Hack | AirPods | Criteria "Coming soon!" (P9) | Submit regardless |
| A5 | **MLH Vultr** | M5Stack Tab5 | Already the deploy target (`README.md` §13; `VULTR_HOST`/`VULTR_SSH_KEY`) | One line |
| A6 | **MLH Gemini** | Swag kit | `blue/gate/llm.py` ships Gemini as default provider | One line |
| A7 | **MLH Best Use of Gen AI** | Assorted | Same code path | One line, same evidence |
| A8 | **Figma** | Gift cards + recruiter session | R's deck and design work | Blocked on P8 |
| A9 | **MLH Tiger Data** | Stream Deck Mini | True once B1 merges | Written after B1 |

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

**B2. CRS Credit API — owner M, branch `blue/crs-verification`, ~3h, prereq: P3 + P4**

- *Why:* `blue/gate/rules.py:217` defines a rule named `unverified_vendor_exposure`. It is
  heuristic — it infers "unverified" from vendor age and exposure, because blue has no way to
  ask whether a counterparty exists in the outside world. CRS is the missing input to a
  control the product already shipped.
- *Files:* `blue/audit/crs.py` (new client); a finding code in
  `blue/audit/evidence.py::derive_findings`; a `@blue_tool` in `blue/audit/tools.py` (`raise_flag`
  already exists at `tools.py:173`); the evidence hook in
  `blue/gate/rules.py::unverified_vendor_exposure`; `blue/tests/`.
- *Design:* one REST call per new vendor or employee, keyed on `vendors.ein`. Runs in the
  audit path per §2 invariant 2: a failed verification becomes a `flag.raised`, and the next
  gate decision reads the flag from internal state — one day of detection latency, zero gate
  latency.
- *Key:* `CRS_API_KEY`, already at `.env.example:51` and in `docker-compose.yml`. Absent →
  `unknown`, never blocks.
- *Cross-area dependency:* CRS mandates test identities only. For the signal to discriminate,
  seeded legitimate vendors need EINs that resolve in the CRS sandbox and red's fabricated
  vendors need EINs that do not — `battlefield/seed/company.py`, Ad's area (P4). Without it CRS
  returns "not found" for every vendor and the integration is decorative.
- *Acceptance:* `make lint test-blue`; two seeded episodes showing the finding fires on red's
  ghost vendor and not on `origin=sim` rows; one demo episode where the CRS flag is what
  catches the ghost vendor.

*Done when:* both PRs are squash-merged per `GIT.md` §4 and A9 is written.

## §7 Phase C — if someone goes idle

Blanket gate: the `README.md` §14 Saturday 14:00 checkpoint (full 3-day episode in `shadow`
with real agents) must be green first. Each item ends the weekend either merged or marked
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
  **Extra gate:** B2 merged — then it reuses the finding plumbing.
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
Owner dev: M. Prereqs: P3 (CRS_API_KEY + test identities) and P4 (EIN list handed to Ad) must
be cleared — if CRS_API_KEY is absent in your .env, implement the neutral "unknown" path,
report the blocked prerequisite, and stop; do not create a CRS account yourself.
Files you may create/modify: blue/audit/crs.py (new), blue/audit/evidence.py,
blue/audit/tools.py, blue/gate/rules.py (only the unverified_vendor_exposure hook),
blue/tests/. Nothing else — battlefield/seed/company.py is Ad's, flag it rather than edit it.
Contract you depend on: vendors.ein is the join key; raise_flag(finding_id) exists at
blue/audit/tools.py:173; unverified_vendor_exposure is defined at blue/gate/rules.py:217.
Requirement: the CRS call happens only in the audit path (once per day), never in blue/gate/'s
synchronous request path; must work under DRY_RUN=true with CRS_API_KEY unset (returns
"unknown", never blocks).
Done means: make lint test-blue passes; two seeded episodes show the finding fires on red's
ghost vendor and not on origin=sim rows; commit on your branch; do NOT push; reply with files
changed, tests run, open questions.
Never: force-push, reset --hard, delete tests, call CRS from the gate hot path, touch
battlefield/seed/company.py.
Task: add a CRS sandbox client, wire it into the audit Droid as a tool, and make
unverified_vendor_exposure consume its finding as evidence.
```
