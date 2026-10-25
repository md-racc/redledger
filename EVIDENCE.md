# Evidence

Every claim we make about Red Ledger, with its proof. Base: a code-verified audit of `main` at `8331ee5`
(2026-10-25), updated for #217, #219, #221 and the P9 lineage. This file beats other prose; code and
`contracts/` beat this file. `#NN` is a PR; "Finding" is a dated entry in `contracts/CHANGELOG.md`.

## 1. Safe to claim

**Architecture and isolation**
- Five containers (`battlefield`, `red`, `green`, `blue`, `frontend`) plus Postgres. Only battlefield holds
  `DATABASE_URL`; agents reach the books only through the Ledger API over HTTP.
- The Ledger API is the enforcement point. Blue's verdict is applied inside battlefield, at preparation time
  and on green's gated routes. Blue `/gate` has one caller in code: battlefield
  (`battlefield/app/gate/gatekeeper.py`).
- Every gate verdict is `allow`, `block` or `escalate` (`blue/gate/engine.py`). An escalation waits 90 s for
  a human; a timeout blocks. An unreachable controller escalates, so in `enforce` money doesn't move.
- Preparations: green prepares each action, keyed by its Droid `tool_use_id`, before acting. A preparation
  lives 120 s; reusing a key for a different action → 409; a stale day or mode → 409; pending preparations are
  swept to block on restart. A stored verdict is never replayed on another day or mode (#147, #151).
- Two tokens chosen by `X-Agent`: an agent must present its own `AGENT_TOKEN_<AGENT>`; another agent's token
  or the operator token → 401 (audited); an agent token without `X-Agent` → 401; an agent on an operator-only
  route → 403 (#108–#111). Per-agent tokens are set on prod.
- Agents can't see the scoreboard: `GET /events`, `/ws`, `/fe/*` and the control plane reject them. The
  browser holds no token: REST goes through a server-side proxy, the WebSocket uses a 60 s single-use HMAC
  ticket, and no browser code sends `?token=`.
- Ground truth is hidden: `origin`, `attack_id`, `origin_of_source` and `created_by` are stripped from every
  agent read and write response. `GET /attacks` hides outcomes until the reveal day (#138, #142).
- Blue can't peek at red: its only audit-log read is `agent=green`; for agent callers battlefield returns
  green/blue rows only (never `attacks.*`, playbook or auth-refusal rows), and `agent=red` returns `[]`.
- Red learns only from the books and its own call results: no raw HTTP, no reads of reports, flags, the
  audit log, events or `GET /attacks`. Debrief reasons are reduced to coarse control categories. Red ignores
  agent-sourced `/inputs` (#221).
- Green reads only vendor changes, invoices, POs, expenses and payments; its prompt doesn't mention origin,
  attack ids, scoring or the other agents.
- Day loop: `day.started` → inject → red → green → blue audit → score → debrief → `day.ended`.
- Lineages: daily debriefs reveal only resolved red attacks within a reveal window and are stored in
  `debriefs`; legit items appear only in the after-action review; plain episodes reveal nothing.

**Agents (Factory Droid SDK)**
- Red: `Autonomy.HIGH`, best-effort identity. Green and blue: `Autonomy.OFF`, strict identity. No handler
  returns `PROCEED_ALWAYS` or `AUTO_RUN`.
- Red has 8 built-in schemes (`red/schemes/__init__.py`, #166). Every attack is declared before it executes;
  parameters are clamped to the catalog. Judge words steer scheme choice or params as quoted data only
  (#165); a non-string `closest_built_in` no longer crashes the turn, and the system prompt keeps every
  attack inside the catalog (#221).
- Green's permission handler prepares each action and proceeds only on `allow`; otherwise it cancels with a
  contract cause. It fails closed on batched requests, missing or unverified tool-use ids, and a missing
  registry.
- Blue's audit runs live on Droid on prod (`DRY_RUN_BLUE=false`, #157) with 7 pinned tools; a freeze needs
  two independent evidence families. Since #195 a live-audit flag has landed on prod and been enforced by
  the gate (ep_9cbc3362d44e).
- Blue blocks invoice threshold splitting at the gate (#206, `invoice_threshold_split`), and holds ghost-vendor
  invoices from $500, the scheme's minimum (#219).
- The gate keeps answering while a live audit runs: turns run on their own event loop (#79).
- Every session: `disable_builtin_skills=True`, `restrict_tools` set, stream timeout `TURN_TIMEOUT_SEC-10`,
  credits logged per turn.
- Every agent runs keyless under `DRY_RUN`; the frontend runs with `NEXT_PUBLIC_MOCK=true` and no backend.

**Prod configuration** (GitHub `production` variables): `DRY_RUN=false`, `DRY_RUN_GREEN=true`,
`DRY_RUN_BLUE=false`; model `gpt-5.4-mini`; credit cap 375,000 per episode; WebSocket `wss://app.redledger.us`.
The site is public and read-only; only an admin can act (#152, #159).

**Results** (figures in §4)
- Controller off vs on on prod, both with red live (#136) and with red and blue's audit live (#193).
- "Red found a gap (invoice splitting, 19/19 extracted); we shipped a control; in the next live lineage red's
  split was caught 3/3, it pivoted to other schemes, and extracted $0 across three generations." Always with
  the P9 caveat in §2.
- CRS on prod: blue's live audit flagged the mismatched persona and the gate blocked that person's next
  expense while two clean hires were paid (ep_9cbc3362d44e, #197).
- The controls report's per-scheme rows always sum to the headline loss (#217).

**Engineering hygiene**
- Branch protection on `main`: 8 required checks, squash-only, no force pushes, admins included. CI's
  ownership guard enforces area boundaries; the contracts guard requires a CHANGELOG line.
- About 1,570 Python unit tests passing at audit time (agentkit 156, battlefield 269 + 321 DB tests skipped
  without Postgres, red 138, green 522, blue 485); ruff clean in every Python area.

## 2. Do not claim

| Claim | Reality |
|---|---|
| Green evolves, or "three live agents" | Green is keyless on prod (`DRY_RUN_GREEN=true`); its live turn is hard-disabled (`green/agent.py`) until #160 (open draft). Its reflection writes a playbook nothing reads on prod |
| The agents adapt against each other / blue learned to stop red | In P1 red adapted and blue didn't keep up. In P9 the control that caught the split is one we shipped; blue added no learned controls ("Learned: none") |
| Blue writes new rules | It toggles a fixed set of four pre-written learned controls (`blue/gate/learned.py`) |
| The split gap is closed for good | One short lineage: one split, caught 3/3, then red stopped splitting |
| P9's $0 is all blue's doing | Blue caught 3 of 12 launches. The other 9 never paid: `duplicate_invoice` is held by green (the PO is already used) and `amount_drift` was only noted. Red's ranking prefers schemes that failed uncaught, so it kept choosing non-paying schemes |
| Red invents schemes (`evolved:<slug>`, or from a judge's words) | Not implemented. `/schemes` returns the 8 built-ins; evolution and judge input only pick among them or set params |
| The gate is an LLM, or its LLM decides ambiguous cases | The gate is deterministic rules. The optional LLM's output is logged only (`blue/gate/engine.py`), and prod has none configured |
| Controller-on run: "$1,824 extracted" | $0 after #207 rescoring: the decoy invoice was paid into the vendor's real account. Quote the controls report |
| Red + blue controller-on: "$20,350" | $18,526 in the controls report; $20,350.37 is the recording's pre-#207 scoreboard |
| Blue audit costs "3.4k–19k credits" | That range came from the streamed-arguments identity bug. Steady cost: median ~3,985 (3.3k–5.4k) per audit (#216) |
| Red turns cost ">2 credits" | Median ~2,790 credits per turn (#216) |
| "No CRS call has run on prod" | It has: ep_9cbc3362d44e |
| "The invoice split is still open" | Caught at the gate since #206 |
| CRS blocks fraud in general / every prod run checks identities | One recorded 2-day run, 3 operator-bound fictional personas. Ordinary episodes make no CRS call |
| Scores are never computed client-side | Three frontend files compute projected or offline scores (labelled as such). Live scores come only from `score.updated` |
| `origin` is never shown in the UI | It is shown in the operator-only confusion view; agents never see it |
| A single reducer holds all UI state / API types are generated from OpenAPI / built with shadcn/ui | Event state goes through `lib/reducer.ts`, plus two zustand stores; types are hand-written (the yaml covers 3 of ~16 `/fe/*` routes); shadcn is not a dependency |
| Runs on TimescaleDB in production | CI-proven; prod runs `postgres:16-alpine` |
| Three-way match, runs the close, reconciles the bank | Two-way invoice↔PO match only; no receiving record, no close agent |
| Production-ready, horizontally scalable, zero-downtime deploys, per-user auth | Battlefield is single-process (in-memory turn guard, escalation waiters, ticket set); a redeploy stops a running episode's loop; one shared admin key |
| MLH Gemini use | No Gemini on prod; red moved off `gemini-3.8-flash` after it stalled (#118) |

## 3. Re-check before using

- **`SUBMISSION.md` placeholder:** `⟦CRS-LIVE⟧` is still in the text. Fill it only if the table demo happened;
  otherwise delete the sentence.
- **Pitch lines** "None of blue's rules fired" and "$19k → $97k": check against the live Evolution card for
  `ln_f52a3df83c8d` ($97,734, so "$98k" when rounded). On that card red's per-attack chips use the stored
  `attacks.amount_extracted` while "Stolen" uses #207 scoring, so chips can sum to more than the total; and the
  card shows `retired_rules` as "not fired after this generation".
- **Evolution card source:** it tries `?lineage=`, then the pinned `ln_f52a3df83c8d`, then the newest finished
  lineage, then a synthetic sample. Make sure the demo isn't on the synthetic sample. P9 is
  `?lineage=ln_431bf702e8a0`.
- **Fallback blocks look like control blocks.** The frontend ignores `gate.verdict.cause`, so a block because
  blue was unreachable looks the same as a rule block. Don't narrate a fallback block as blue catching fraud.
- **Voice:** the ElevenLabs speech-to-text route (#154, #162) is tested only against a stub. Try one real
  recording on prod before relying on it on stage.
- **"14% → 85% of fraud dollars stopped"** (keyless matrix, 5 seeds × 10 days, all 8 schemes, before vs after
  #196's controls): the outputs live in Ad's session scratchpad, not the repo. Label it keyless and re-run
  before quoting.
- **Live CRS at the table:** prod takes one run at a time, and the sandbox login has flapped for minutes after
  heavy use; blue logs in once per process with no retry. Keep the recording ready.

## 4. Numbers we cite

**Controller off vs on (prod).** Headline figures are the live controls report (`/report/<episode>`,
`GET /fe/episodes/{id}/controls`), which applies #207 scoring. The recordings' own final scoreboards predate
#207.

| Run | Episode | Lost (controls report) | To attacker accounts | Caught | Blocked | FP cost | Recording's scoreboard |
|---|---|---|---|---|---|---|---|
| Red live, own schemes, seed 42, 10 days, off | `ep_7f473df2a138` | $10,285 | all, via one approved bank swap | 0 / 10 | $0 | $0 | $10,284.61 |
| same, enforce | `ep_540353ebf616` | **$0** | $0 | 1 / 10 | $0 | $100 | $1,824.22 (decoy paid to the real vendor) |
| Red + blue audit live, fixed 6-scheme plan, seed 42, 6 days, off | `ep_89d1df6b012a` | $23,681 | $23,335 | 0 / 6 | $0 | $0 | $23,681.43 |
| same, enforce | `ep_d9b561111d60` | $18,526 | $18,180 | 2 / 6 | $1,480 | $50 | $20,350.37 |

The #136 pair looks better largely because 9 of red's 10 attacks were duplicate invoices that never pay. In
the #193 enforce run, $18,526 = ghost vendor $4,380 + a $13,800 invoice split (both to red's own vendor) + an
inflated expense $346.15; it predates #206 (split control) and #195 (live flags).

**Lineages (prod; reports are operator exports from `make prod-evolution-report`, not committed)**

| Lineage | Setup | Extracted per gen | Blocked | FP cost | Caught / launched | Credits per gen |
|---|---|---|---|---|---|---|
| `ln_f52a3df83c8d` (P1) | 5 gens × 8 days, enforce, seeds 502–506; red live, green + blue keyless; before #148/#173/#206 | $19,076 / $35,423 / $86,510 / $53,619 / $97,734 | $6,214 / $4,380 / $0 / $0 / $0 | $100 / $50 / $0 / $150 / $100 | 3/7, 5/7, 2/8, 5/8, 1/8 | 20,402 / 20,744 / 22,831 / 22,974 / 22,313 (~109k, red only) |
| `ln_431bf702e8a0` (P9) | 3 gens × 4 days, enforce, base seed 501 (502–504); red + blue audit live, green keyless; deploy 15f08b4 (#195, #206, #207) | $0 / $0 / $0 | $13,800 / $2,430 / $0 | $100 / $50 / $0 | 2/4, 1/4, 0/4 | 27,877 / 29,576 / 27,525 |

P1: `threshold_split` launches 1 → 2 → 6 → 3 → 7, all 19 extracted; no new schemes; blue's four learned
controls never fired on a split. P9: g1 `bank_swap` and `threshold_split` blocked, `duplicate_invoice` ×2; g2
`po_mismatch` blocked (`over_po_amount`), `amount_drift`, `duplicate_invoice` ×2; g3 `amount_drift`,
`duplicate_invoice` ×3. `invoice_threshold_split` fired 3 times in g1, all on red.

**CRS**: prod `ep_9cbc3362d44e` (enforce, seed 42, 2 days, `make prod-crs-episode`, #197): live audit called
`crs_identity_check` on both days, P12 mismatch flagged via `raise_flag`, P12's day-1 expense blocked
(`already_flagged_high`), P01/P16 paid, blue credits 3,985 / 5,318. Local acceptance `ep_0181eda1c921` (#102):
same chain, 19 identity checks, all `billable:false`.

**Cost, limits and counts**

| Metric | Value | Source |
|---|---|---|
| Red turn cost (median) | ~2,790 credits | Finding, #216 |
| One measured red turn | 11.2 s, 2,635 credits (ep_568aef023d7c) | Finding, #118 |
| Blue audit cost (median) | ~3,985 credits (3.3k–5.4k) | Finding, #216 |
| Green prod cost | 0 (keyless) | prod variables |
| Per-episode credit cap | 375,000 | prod variables |
| Red schemes / blue audit tools / green tools | 8 / 7 / 9 | `red/schemes/__init__.py`; `blue/audit/agent.py`; `green/agent.py` |
| Preparation lifetime | 120 s | `agentkit/agentkit/models.py` |
| WebSocket ticket | 60 s, single use, HMAC | `battlefield/app/auth.py` |
| Escalation timeout / gate timeout | 90 s / 8 s | `battlefield/app/config.py` |
| FP penalty | 2% of blocked legit amount + $50 per legit item | `battlefield/app/config.py`, `score.py` |
| Approval threshold | $5,000 | `APPROVAL_THRESHOLD`; `blue/gate/rules.py` |
| Gate latency during a live audit | p95 8.04 ms, max 56.6 ms, 1,817 samples (local stack, not prod) | #119 |
| Python tests passing | ~1,570 at `8331ee5`; battlefield DB tests not run | audit §6 |

## 5. Recordings

Each file in [`recordings/`](recordings/) is one prod episode's operator event stream (`contracts/events.md`),
exported with `make prod-record` and secret-scanned. Long hex strings are Droid tool-call ids. Being operator
streams, `attack.launched` events name red's entities: never feed them to an agent. To replay, copy one into
`battlefield/fixtures/episodes/` and `POST /replays/{id}/play`. The frontend ships copies in
`frontend/public/mocks/` (a test fails if they drift).

| File | Episode | Date | Agents | Mode, seed / days | Scoreboard in file | Credits |
|---|---|---|---|---|---|---|
| `demo-off-live.jsonl` | `ep_7f473df2a138` | 2026-10-24 | red live; green, blue keyless | off, 42 / 10 | $10,284.61, 0/10 | red 26,230 |
| `demo-enforce-live.jsonl` | `ep_540353ebf616` | 2026-10-24 | same | enforce, 42 / 10 | $1,824.22 (pre-#207; report: $0), 1/10, $100 FP | red 24,449 |
| `demo-off-redblue-live.jsonl` | `ep_89d1df6b012a` | 2026-10-25 | red + blue audit live; green keyless | off, 42 / 6 | $23,681.43, 0/6 | red 16,038 / blue 66,422 |
| `demo-enforce-redblue-live.jsonl` | `ep_d9b561111d60` | 2026-10-25 | same | enforce, 42 / 6 | $20,350.37 (pre-#207; report: $18,526), 2/6, $1,480 blocked, $50 FP | red 14,206 / blue 37,446 |
| `crs-live-ep_9cbc3362d44e.jsonl` | `ep_9cbc3362d44e` | 2026-10-25 | red + blue audit live; green keyless | enforce, 42 / 2 | CRS PASS; P12's expense blocked (counted as a legit block, $51.82 FP, because the personas are operator fixtures) | blue 3,985 / 5,318 |

The #193 pair (`*-redblue-*`) follows one fixed plan: day 0 ghost_vendor, 1 bank_swap, 2 threshold_split,
3 expense_inflation, 4 amount_drift, 5 ghost_employee. Its blue credits are inflated by the pre-#195 identity
bug (refused `raise_flag` calls), so its catches come from gate rules only. The CRS stream holds no persona
names, identity fields or CRS response text; its bind events carry only `employee_id`.

## 6. Known limits we disclose

None of these leaks ground truth today.

1. **Agents can post into another agent's next turn via `POST /inputs`**, labelled with the sender's role, which
   conflicts with "agents never call each other". Mitigated on red's side by #221 (red ignores agent-sourced
   inputs); battlefield still accepts the posts. Decision pending (Ad).
2. **`BLUE_URL` is in every agent's environment** (`docker-compose.yml`), though only battlefield's code uses
   it. With per-agent tokens (prod) only battlefield can call `/gate`; under the single-token fallback any agent
   could.
3. **`GET /reports/{id}` accepts any agent**, so red could read blue's reports; only review prevents it.
4. **`GET /vendors/{id}` and `GET /invoices/{id}` don't filter by episode**: an agent holding another episode's
   id can read that row (hidden fields still stripped).
5. **Green has never run live.** Whether a `CANCEL` comment reaches the model is untested (open in CHANGELOG).
6. **No model pin is enforced in code.** `DROID_MODEL_*` defaults blank; prod relies on deploy variables.
7. **Agent-visible sim-vs-red tells** (#29): e.g. red employees always lack an HR record, legit expense memos are
   empty. A learning blue could exploit these.
8. **Agents share one Docker network**; separation is by token, not network.
9. **The credit cap is soft**: it is checked after each turn and can overshoot by one turn in flight.

## 7. Sponsor integrations

Only rows with evidence in the repo or a PR. "Track only" means no sponsor API is called; the claim is about
the product.

| Sponsor | What is true | Evidence |
|---|---|---|
| **Factory (Droid SDK)** | Red and blue's audit run live on prod (`gpt-5.4-mini`); green on the same harness, keyless. One `agentkit.DroidAgent` base: string system prompt, built-in skills off, in-process MCP tools with exact `restrict_tools` ids, Droid `tool_use_id` as the ledger idempotency key, strict identity, credit logging and caps. Dated Findings incl. the streamed-arguments fix (#195) | `agentkit/agentkit/droid_agent.py`; `contracts/CHANGELOG.md` Findings; #84, #118, #119, #157, #195, #216 |
| **Hyphenate** (track only) | An autonomous AP system with limited access, a full audit trail and knowing when to ask: preparation → gate → escalation to a human; measured in dollars both ways; the P1/P9 lineages | `battlefield/app/gate/gatekeeper.py`; `audit_log`; §4 |
| **Microsoft** (track only) | Deployed and operated: CI per service, approval-gated deploy workflow, images without secrets, public read-only site with admin-only actions, replayable recordings, `make prod-*` operations | `.github/workflows/ci.yml`, `deploy.yml`; #152, #159; `deploy/` |
| **CRS** | Blue's audit tool `crs_identity_check` logs in to the CRS sandbox and calls TransUnion identity-manager verification for three pinned fictional personas (P01/P12/P16) bound by an operator; a mismatch becomes a HIGH flag the gate enforces. One live prod run; local runs all `billable:false`. The gate never calls CRS | `blue/audit/crs.py`, `blue/CRS.md`; #102, #125, #139, #197; ep_9cbc3362d44e |
| **Armadin** (track only) | An offensive LLM agent against a defended agentic finance system, boxed in by the server (8 tools, own token, no pay/approve/read-audit routes). Self red-team fixes: red reading outcomes early (#138/#142), verdict replays across days/modes (#147/#151), origin reachable around Cloudflare (#47), public viewers reading fraud rows (#196); 14 verifier-attributed integrity and leak fixes before merge (#30, #52, #57, #59, #62, #66, #71, #130) | PR bodies; `battlefield/app/auth.py`, `api/reads.py` |
| **Tiger Data (TimescaleDB)** | `events` and `audit_log` are hypertables keyed `(id, ts)`; a `score_timeline` continuous aggregate serves score over time; local compose defaults to the Timescale image; CI runs the full battlefield suite on it. Prod runs plain Postgres 16 | `battlefield/app/timescale.py`; `ci.yml` `battlefield-timescale`; #98, #100 |
| **Vultr** | The whole stack runs on one Vultr VM: Compose, Caddy behind Cloudflare, rolled by the approval-gated deploy job over SSH | `.github/workflows/deploy.yml`; `deploy/bootstrap.sh`; `VULTR_HOST` secrets |
| **ElevenLabs** | Server-side speech-to-text for the admin-only voice attack console; typing works without it. Not yet verified against the real service (§3) | `frontend/lib/voice/`; #154, #162, #163 |

Not claimed: Atlassian (the Forge escalation inbox was never started), Gemini (see §2), Bright Data (dropped,
no code on main), Cartesia, Nessie, Auth0, Elastic (never built).
