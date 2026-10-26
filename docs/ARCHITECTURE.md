# Architecture

Architecture of the completed October 2026 hackathon prototype: the system, the Ledger API's
enforcement, each agent, evolution,
scoring, Droid SDK usage and the evidence behind its recorded runs. `contracts/` is the
machine-readable law; if code or prose disagrees with a contract, the contract wins. PR numbers
are citations. Production configuration below describes the October 24–25, 2026 deployment,
not a maintained hosted service; see [CLOSEOUT.md](CLOSEOUT.md).

## System overview

Five containers plus Postgres:

| Service | Role | Calls |
|---|---|---|
| `battlefield` (FastAPI, asyncpg) | Ledger API, orchestrator (clock), gatekeeper, event bus, scorekeeper, `/api/fe` read views | Postgres, red/green `/turn`, blue `/gate` + `/audit`, every agent's `/reflect` |
| `red` | fraud agent, Droid SDK | battlefield only |
| `green` | AP clerk, Droid SDK harness (keyless on prod) | battlefield only |
| `blue` | controller: rules gate + daily Droid audit | battlefield only |
| `frontend` (Next.js) | arena, consoles, reports | battlefield, through its server-side `/api/bf/*` proxy |

Only battlefield holds `DATABASE_URL`. Agents reach the books through `agentkit.LedgerClient`
over HTTP and never call each other; blue `/gate` has exactly one caller in code, battlefield
(`battlefield/app/gate/gatekeeper.py`). `BLUE_URL` is present in every agent's environment
(`docker-compose.yml`) but no red or green code uses it, and per-agent tokens stop any agent
other than battlefield's caller from authenticating to `/gate`.

**The day loop** (`battlefield/app/orchestrator/runner.py`, `run_day`): `day.started` (legit
traffic injected) → `POST red/turn` → `POST green/turn` (every mutation gated) →
`POST blue/audit` → resolve attack outcomes and score (`score.updated`) → lineage debriefs
(`debrief.delivered`, lineage episodes only) → `day.ended`. The day is idempotent across a
restart: a resumed day is not re-injected, and red and blue turns that already started are not
re-run. Controller modes are per episode and switchable mid-episode: `off` (blue never called),
`shadow` (verdicts recorded with `enforced=false`, nothing blocked), `enforce`.

**System invariants** (see `AGENTS.md` and the contracts): agents never touch Postgres; agents
never call each other; the Ledger API is the enforcement point; `origin` is secret during play;
every Ledger API call writes `audit_log` and every tool call emits an `agent.tool_call` /
`agent.tool_result` pair; idempotency keys are the SDK `tool_use_id`; everything runs under
`DRY_RUN=true` with no keys; every HTTP call and stream has a timeout; agents read the books,
never the scoreboard or each other.

## Ledger API and enforcement

### Tokens and callers

Two tokens, chosen by `X-Agent` (`battlefield/app/auth.py`):

- A request with `X-Agent: <agent>` must present that agent's own token (`AGENT_TOKEN_<AGENT>`;
  battlefield holds all three, each agent container only its own as `AGENT_TOKEN`). Another
  agent's token or the operator token → 401, and the refusal is audited when the presented token
  belongs to a known caller (#108/#109). An agent token without `X-Agent` → 401.
- A request without `X-Agent` must present `OPERATOR_TOKEN`. An authenticated agent on an
  operator-only route → 403.
- Agents cannot reach `GET /events`, `/ws`, `/fe/*` or any control-plane route. The browser holds
  no token: REST goes through the frontend server's proxy, and the WebSocket uses a 60 s
  single-use HMAC ticket.
- Any agent write outside that agent's active turn → `409 {error: "no active turn for this agent"}`
  (audited). Agents may not act in replay episodes (403).

### What agents may read

- `origin`, `attack_id`, `origin_of_source` and `created_by` are stripped from every read route
  and every write response to an agent (`battlefield/app/db.py`, `HIDDEN_COLUMNS`).
- `GET /attacks` (red) omits `outcome`, `amount_extracted`, `detected_day` and `resolved_day`
  until the attack is revealed by a lineage debrief.
- `GET /audit_log` is blue-only and, for any agent caller, returns green/blue rows only: never
  `attacks.*`, playbook or auth-refusal rows; `agent=red` returns `[]`
  (`battlefield/app/api/reads.py`). Blue's only call is `agent=green`.
- `GET /flags` is green/blue only.
- Known gaps, not leaks of ground truth: `GET /reports/{id}` accepts any agent (review keeps red's
  tools off it); `GET /vendors/{id}` and `GET /invoices/{id}` don't filter by episode; any agent
  can `POST /inputs` into another agent's next turn, stamped with the sender's name as `source`
  (red ignores agent-sourced inputs, #221).

### Preparations

Green prepares every gated action before executing it (contracts #80/#86, battlefield #87/#89):

1. `POST /preparations {action, entity_id?, args}` with `X-Tool-Use-Id` = the SDK `tool_use_id`.
   `action` is one of the nine gated actions (`invoices.match|approve|reject|pay`,
   `vendor_changes.approve|reject`, `expenses.approve|pay`, `gl.post`). Battlefield runs the
   route's own state checks (404, `409 invalid_state`), assembles the provenance-stripped gate
   context, asks blue (8 s, `GATE_TIMEOUT_SEC`), persists the verdict, marks the entity `blocked`
   on an enforced block, and holds an enforced escalation. It returns `200 Preparation` with
   `effective: allow | block | pending`; a block is a successful preparation.
2. The row binds the key to (action, entity, amount ±1¢, args), mode, day, a narrow state
   fingerprint (`state_hash`: for `invoices.pay`, the invoice's amount/vendor/PO, the vendor's
   status/bank account/routing/name, and the PO), and a fixed expiry of **120 s from creation**
   (`PREPARATION_TTL_SEC`, never extended).
3. The same key and action again returns the stored preparation: no new gate call, no second
   escalation. The same key for a different action → `409 idempotency key reused for a different
   action`.
4. The gated route called later with the same key **consumes** the preparation and does not call
   blue again. In order: binding mismatch → 409 (every mode); already consumed or still pending →
   409 `preparation_consumed|preparation_pending`; mode or day changed → 409 `preparation_stale`
   (every mode); enforce only: expired → 409 `preparation_expired`, stored block → 403. Then, in
   one transaction: the status compare-and-set, the fingerprint recomputed `FOR UPDATE` (a bank
   change since preparing → 409 stale in enforce, audited in shadow/off), the consumption claim,
   the mutation. No automatic retry anywhere.
5. Without a preparation for the key, a gated route gates inline (DRY_RUN, mock agents). An inline
   verdict replays for its key only on the same day and under the same enforcement; otherwise
   `409 stale verdict` (#147/#151).

Battlefield refuses to start unless `ESCALATION_TIMEOUT_SEC + GATE_TIMEOUT_SEC + 15 ≤ 120`
(defaults 90 + 8 + 15 = 113). On restart, `pending` preparations become `block / timeout`.

### Escalation and verdict cause

- In enforce, `escalate` opens an `escalations` row and emits `escalation.opened`; the request is
  held for `POST /escalations/{id}/resolve {decision: approve|block}`. **Timeout (90 s) = block.**
  Headless lineage generations use `headless.escalation_timeout_sec` (default 5 s).
- An escalation closes exactly once by compare-and-set on `status='open'` (human, timeout or
  orphan sweep). One flight per idempotency key: one verdict, one card, one human decision.
- After an approved hold, payment re-reads the vendor `FOR UPDATE`; a freeze during the hold
  aborts it.
- If blue is unreachable or slower than 8 s, the fallback is `escalate` in enforce and `allow`
  in shadow, with `rules_fired: ["gate_timeout"]`. `verdicts.cause` is `gate_unavailable` for that
  fallback and `control` otherwise, carried on `gate.verdict`, `escalation.opened` and the prepared
  403. The inline (unprepared) 403 does not carry `cause`, and the frontend doesn't render it, so
  a fallback block looks like a control block in the UI.

### Routes and extensions

Canonical: `contracts/ledger-api.yaml`; live docs at `/docs`. Base `http://battlefield:8000/api`. Agent
requests carry `Authorization: Bearer <own token>`, `X-Agent`, `X-Episode`, `X-Day`, and on writes
`X-Tool-Use-Id` (the idempotency key; `<id>:<n>` for a call's n-th write).

| Group | Routes | Who |
|---|---|---|
| Reads | `GET /vendors[/{id}] /vendor_changes /employees /purchase_orders /invoices[/{id}] /payments /expenses /bank/transactions /gl/entries /reports/{id}`; `/flags` (green, blue); `/audit_log` (blue, green/blue rows only); `/attacks` (red, outcomes hidden until revealed) | agents + operator |
| Red writes | `POST /attacks` (declare first), `PATCH /attacks/{id}`, `POST /vendors /vendor_changes /invoices /expenses /employees` | red |
| Green writes (gated) | `POST /preparations`, `GET /preparations/{key}`; `POST /invoices/{id}/match\|approve\|reject\|pay`, `/vendor_changes/{id}/approve\|reject`, `/expenses/{id}/approve\|pay`, `POST /gl/entries` | green |
| Blue writes | `POST /flags`, `/vendors/{id}/freeze\|unfreeze`, `/reports` | blue |
| Agent state and inputs | `GET/PUT /state/{key}`; `POST /inputs` (a message into an agent's next turn); `GET /inputs` operator-only | agents / operator |
| Playbooks | `GET /playbook`, `/playbook/history`, `PUT /playbook` (own playbook, active turn only) | red, green, blue |
| Events | `POST /events` (agents: `agent.*`, `x.*`); `GET /events`, `POST /ws/ticket`, `WS /ws` | write: agents; read: operator only |
| Control plane | `POST /episodes`, `/episodes/{id}/start\|pause\|resume\|step\|attack\|fixtures`, `PATCH /episodes/{id}/controller`, `GET /episodes/{id}/score`, `/attacks/all`, `/schemes`, `/escalations`, `POST /escalations/{id}/resolve`, `/replays`, `/lineages/*`, `/health` | operator / frontend server |
| Frontend reads | `GET /fe/episodes/{ep}/…` (snapshot, timeline, verdicts, attacks, controls, …), `/fe/compare`, `/fe/lineages/{id}/report\|timeline` | operator / frontend server |

A blocked gated call returns `403 {verdict:"block", reason, verdict_id, …}`; an escalation holds the call
until resolved, then returns 200 or 403.

**Extensions.** Teams grow the sandbox without a contracts PR through two carve-outs (`GIT.md` §2):
routes in `battlefield/extensions/<area>_*.py` (mounted under `/api/x/<area>/…`) and tables in
`contracts/ext/<area>/*.sql` (tables prefixed `<area>_`, applied at startup after `contracts/schema.sql`
in filename order).
A change to a core route, event type or column is a `contracts/` change.

## Red

`red/agent.py`, `red/tools.py`, `red/schemes/`. Droid at `Autonomy.HIGH`, best-effort identity
(SDK id when linked, UUID4 fallback otherwise), permission handler always `PROCEED_ONCE`. Live on
prod (`gpt-5.4-mini`, reasoning low).

- **Eight built-in schemes, nothing else** (`red/schemes/__init__.py`): `ghost_vendor`,
  `bank_swap`, `duplicate_invoice`, `threshold_split` (splits invoices across the approval
  threshold), `ghost_employee`, `expense_inflation`, `po_mismatch`, `amount_drift`. Each has
  `viable / plan / execute` and catalog fields (`display_name`, `story`, `params_schema`,
  `expected_impact`). `GET /schemes` returns exactly these. Composed or `evolved:<slug>` schemes
  are not implemented.
- **Catalog clamps:** each scheme clamps its parameters to its own limits (claim counts, totals,
  drift and overage percentages, split part counts).
- **Declared attacks:** `run_scheme` accepts catalog ids only and declares the attack
  (`POST /attacks`) before executing it; battlefield links the resulting rows to the attack.
- **Tools:** `list_schemes`, `inspect_books`, `run_scheme`, `create_vendor`, `submit_invoice`,
  `request_vendor_bank_change`, `submit_expense`, `add_employee`. Red can't approve, pay, freeze,
  or read reports, flags, the audit log, events or `GET /attacks` outcomes.
- **Judge input:** the frontend's attack console posts `{kind: "custom_fraud_scheme", text,
  language, closest_built_in}` to `POST /inputs`; it arrives as `options.inputs` on red's next
  turn. Only operator-side sources count (agent-sourced inputs are ignored, #221). The words are
  quoted into the prompt as data (≤ 3 requests, 500 chars each) and can steer which built-in runs,
  or a forced scheme's params; they can't add a scheme. The payload has no contract yet.
- **Forced attacks:** `POST /episodes/{id}/attack` (operator) sets `options.scheme_id` and
  `params`, which override any preference.
- **DRY_RUN:** no model; rotates through viable schemes by day.

**Playbook evolution within the catalog** (`red/evolution.py`). Only a valid `options.lineage`
enables playbook I/O. The `red_evolution` namespace keeps at most 128 typed categorical
observations (generation, day, hashed attack identity, scheme, outcome, caught, control kinds),
deduplicated across debriefs and reviews. Preference per scheme, by its most recent result:
undetected extraction, then untried, then uncaught failure, then caught; day rotation breaks
ties. Only red's own disclosures are folded; scores, raw reasons, entity ids and prose never
become instructions. `inspect_books` persists the fold with `PUT /playbook` inside the turn; a
failed playbook read or write never costs the attack. `/reflect` runs the same pure fold with no
ledger calls.

## Green

`green/agent.py`, `green/workflow.py`, `green/preparation.py`, `green/tools.py`. A competent,
deliberately trusting AP clerk; controls belong to blue.

- **Workflow** (`run_clerk`): `ap_queue` → resolve pending vendor changes procedurally → match
  invoices only to their referenced, usable open PO (a missing or unusable PO defers the invoice)
  → approve genuine no-PO invoices → pay matched/approved invoices at or below the inclusive
  `APPROVAL_THRESHOLD` ($5,000; above it, defer) → approve then pay expenses → report confirmed
  counts and dollars, with blocks, deferrals, failures and unknown outcomes separate. No automatic
  GL posting (deferred until a balanced-journal contract exists). Never retries a blocked action.
- **Nine pinned tools** (`AP_TOOL_IDS`, Finding #96): `ap_queue`, `match_invoice`,
  `approve_invoice`, `reject_invoice`, `pay_invoice`, `approve_vendor_change`,
  `reject_vendor_change`, `approve_expense`, `pay_expense`.
- **Permission handler** (`Autonomy.OFF`, strict identity, so every MCP call raises a request):
  one request → `POST /preparations` keyed by the SDK id → `PROCEED_ONCE` when `effective` is
  `allow`, otherwise `CANCEL` with a JSON comment carrying the contract cause: `control_hold`,
  `escalation_timeout`, `invalid_state` or `integration_failure`. Per mode: off/shadow proceed on
  a transport failure (the route gates inline); enforce cancels.
- **Fails closed** on batched requests (one SDK answer covers the whole batch), unknown or empty
  requests, missing or unverified tool-use ids, and a missing invocation registry.
- **Live path disabled:** `GreenAgent._droid_turn` raises before any Session opens. The
  proposed guard lift (#160) was unfinished hackathon work. The deployment ran green keyless
  (`DRY_RUN_GREEN=true`): the deterministic clerk calls the same decorated tools against the gated routes, which gate inline. Green's
  `/reflect` (`green/playbook.py`) writes deterministic procedure memory; its turn prompt reads it
  only on the live path, so nothing on prod consumes it.

## Blue

### Gate (preventive control)

`blue/gate/rules.py`, `blue/gate/engine.py`. Deterministic and uses only the context
battlefield supplies (vendor, PO, recent vendor changes, recent paid and open invoices, flags,
employee and expense history); no Droid. Verdicts are identical in every mode; battlefield alone
enforces. Rule effects: `note` (allowed, listed in the reason), `review` (escalate), `block`,
`unavailable` (escalate). `T` = `APPROVAL_THRESHOLD`.

| Rule id(s) | Fires when | Effect |
|---|---|---|
| `vendor_age_lt_7d` | invoice approve/pay, vendor 0–6 days old, amount > $1,000 | note |
| `near_threshold` | invoice approve/pay, 0.95·T ≤ amount < T | note |
| `threshold_split` | expense approve/pay: same-day, same-category parts for one employee, each < T, total ≥ T (#173) | block (review if ≥ 3 parts within 5% below T) |
| `invoice_threshold_split` | invoice approve/pay: same-vendor invoices received within a day, each < T, sharing one PO or none, total ≥ T (#206) | block (review if ≥ 3 parts within 5% below T) |
| `duplicate_invoice` | same vendor and invoice number, or one appended letter with the same PO and ≤ $0.05 difference | block |
| `duplicate_near_match` | > $1,000, within 2% of a paid invoice from the vendor in the last 15 days, under a different number | review |
| `recent_bank_change` | invoice pay > $2,500 within 14 days of an approved bank change | review |
| `bank_change_with_open_invoices` | approving a bank change while the vendor has open invoices | review |
| `no_po_from_po_vendor` | no PO, ≥ 5 paid invoices all with POs, amount above every prior payment (#148) | note |
| `po_vendor_mismatch`, `invalid_po`, `over_po_amount` | PO belongs to another vendor; PO cancelled; amount > 110% of PO (also on match) | block |
| `recurring_drift` | ≥ 3 paid invoices within 5% of their mean, amount > 115% of it | note |
| `employee_bank_matches_vendor` | expense: employee shares a payment account with a vendor | review |
| `no_hr_record`, `inactive_employee` | expense: `hr_record` false; employee not active | block |
| `vendor_frozen`, `already_flagged_high` | vendor frozen; a high-severity flag on the invoice, vendor, expense or employee | block |
| `unverified_vendor_exposure` | vendor 0–6 days old, no PO, no established paid history, amount ≥ $500 (#219) | block |
| `verification_unavailable`, `rule_error:<rule>` | evidence missing, malformed or out of episode; a rule raised | unavailable |

Rejections and `gl.post` fire nothing. **Decision:** any `unavailable` → escalate (a learned
control's `unavailable` can't override a baseline block); else any `block` → block (0.98); else
any `review` → escalate (0.65); else allow (0.99). Reasons are the rule details joined in plain
sentences. Verdicts are cached per (episode, key) for 120 s; the key is bound to its first action
(sub-cent tolerance; `gl.post` binds the posted fields) and a conflicting reuse → 409. At 100,000
retained entries or 256 in-flight keys, new admissions get 503. The cache is process-local; the
durable record is battlefield's.

**LLM advisory is log-only.** On a review-driven escalate, outside dry-run and only when a
provider is configured (`BLUE_GATE_LLM_PROVIDER`), `blue/gate/llm.py` makes one bounded call
(2.4 s deadline, 8 concurrent). Its output is logged and never changes verdict, reason,
confidence or rule ids. Prod has no gate LLM configured.

**Learned and retired controls** (`blue/gate/learned.py`, lineage episodes only). Four
pre-written `review` predicates a playbook can switch on or off, never author:
`learned:young_vendor_any_amount`, `learned:near_threshold_wide` (band widens toward 0.80·T),
`learned:duplicate_amount_loose`, `learned:bank_change_any_amount`. Blue's `reflect` enables the
controls mapped to each scheme that got money out (`extracted`/`partial`), retires a learned
control that hit a legit item, and retires a baseline **note** rule after legit-only fire
(`on_legit ≥ 3`, `on_red = 0`; `RETIREABLE_RULE_IDS`: `near_threshold`, `no_po_from_po_vendor`,
`recurring_drift`, `vendor_age_lt_7d`, #133). Block and review rules are never retired. `/gate`
receives `playbook_version` and refreshes with a cold `GET /playbook`.

### Daily audit (detective control)

`blue/audit/agent.py`, `snapshot.py`, `evidence.py`, `tools.py`. Runs live on Droid on prod
(`DRY_RUN_BLUE=false`, `gpt-5.4-mini`) since the guard lift (#157); `Autonomy.OFF`, strict
identity, handler always `PROCEED_ONCE`. Audit and `/turn` share one lock (overlap → 409); `/gate`
is unlocked and keeps answering because turns run on their own loop.

- **Snapshot:** public `LedgerClient` reads only: vendors, employees, invoices, POs, today's
  payments, vendor changes, flags, and `list_audit_log(agent="green", day=day)`. At most 4
  concurrent reads, 10 s per read, 25 s collection, 2,000 rows per dataset, 20 prioritized
  findings. Names, invoice numbers, bank details and prose never reach the model.
- **Findings** (service-derived, each with evidence in a family: integrity, identity,
  destination, authorization, structure): duplicate invoice, same-day split, unverified
  vendor exposure, bank-change exposure, no HR record, account collisions, CRS identity mismatch.
- **Seven pinned tools** (`AUDIT_TOOL_IDS`, observed via `list_tools()`): `day_activity`,
  `vendor_dedupe`, `benford_check` (hint only), `crs_identity_check`, `raise_flag(finding_id)`,
  `freeze_vendor(vendor_id, finding_ids)`, `post_report`. The service fixes entity, severity and
  reason; the model only picks finding ids.
- **Freeze rule:** findings from **two independent evidence families**, at least one substantive
  integrity or identity fact, plus a fresh unchanged vendor read. Newness, threshold, splitting,
  name or Benford hints never suffice. At most 4 freezes per turn.
- **Flags are enforced by the gate:** a high-severity flag on an invoice, vendor, expense or
  employee makes `already_flagged_high` block the next payment.
- **Budget and receipts:** `min(170, TURN_TIMEOUT_SEC − 10)` s; writes 4 s each with a reporting
  reserve. Every write keeps a receipt (`confirmed`, `failed`, `unknown`); unknown writes are
  never blindly retried. A stalled or over-budget audit ends as a truthful partial audit. Reports
  are under 200 words: Reviewed / Flagged / Needs a human tomorrow, plus gaps.
- State is single-process and in memory; same episode/day replays the completed response.

### CRS identity verification

`blue/audit/crs.py`, `contracts/ext/blue/01_crs_profiles.sql`. The operator binds a synthetic
employee to one of three fictional sponsor personas (`P01`, `P12`, `P16`) with
`PUT /api/x/blue/crs/episodes/{episode_id}/employees/{employee_id}` (operator token, no
`X-Agent`); bindings are immutable per episode, and the employee's name must match the persona.
Blue alone reads the binding. `crs_identity_check` checks active employees onboarded within
seven days, at most ten per audit, against the CRS sandbox (TransUnion identity verification;
one login per client, no retries). Only a DELIVERED product with well-formed messages counts:
SSN/name, issuance/DOB or deceased inconsistencies create a high-severity employee finding;
address-only mismatches and fraud alerts need a human; unknown produces nothing. CRS adds no call
or latency to `/gate`. DRY_RUN never calls CRS unless `CRS_LIVE=true` is exported for acceptance.

Live prod run, **ep_9cbc3362d44e** (seed 42, 2 days, `make prod-crs-episode`, #197): the live
audit called `crs_identity_check` both days, raised the HIGH flag on P12 (mismatch), and P12's
day-1 expense was blocked (`expenses.approve`, `already_flagged_high`, enforced) while P01 and
P16 were paid. Audit credits 3,985 and 5,318. Recording:
`docs/recordings/crs-live-ep_9cbc3362d44e.jsonl`.

## Evolution

### Lineage lifecycle

A **lineage** (`battlefield/app/orchestrator/lineage.py`) is a chain of episodes, one per
**generation** `g`, on seed `base_seed + g`; no two episodes of a lineage share a seed, so legit
traffic is never replayed verbatim. Config (`LineageConfig`, unknown keys refused): `generations`
(3), `days` (6), `controller_mode` (`enforce`), `reveal_days` (3), `reveal_generations` (2),
`headless {day_pause_sec 0, escalation_policy "block", escalation_timeout_sec 5}`, `max_credits`
(0 = off).

`POST /lineages` → v0 playbooks (`{}`) per agent → `POST /lineages/{id}/start` runs each
generation like an episode; after it finishes, battlefield sends each agent its after-action
review on `POST /reflect` (sequentially, within `TURN_TIMEOUT_SEC`) and writes the returned
playbook as a new version (`source=reflect`). `POST /episodes {lineage_id}` starts the next
generation by hand as the real-time demo. One run at a time per battlefield; a restart pauses a
running lineage, `resume` continues at the same generation. `MAX_CREDITS_PER_EPISODE` applies per
generation (prod 375,000) and `max_credits` caps the lineage (turns + reflections), pausing it
with `error {where: "credit_guard"}`. `/reflect` credits are not persisted across a restart.

### Playbooks

Per (lineage, agent) versioned JSON, opaque to battlefield, ≤ 64 KiB, immutable versions with
parent, generation, day, source (`seed | turn | reflect | operator`) and rationale.
`GET /playbook`, `GET /playbook/history`, `PUT /playbook {content, rationale, base_version}`
(own playbook only, active turn only; stale base → 409; idempotent on `X-Tool-Use-Id`; emits
`playbook.updated`). No agent sees another agent's playbook.

### Information policy

- **Debriefs** (`options.debrief`; `debrief` on blue `/audit`) reveal only **resolved** red
  attacks (failed, or with entities and none pending) from the last `reveal_days` completed days.
  Red sees its own attacks with outcomes and coarse control categories; blue sees scheme,
  entities, amounts, outcome and what caught it; green sees fraud items it acted on. Daily
  debriefs never list legit items, and a live approved bank swap counts as unresolved.
- When a debrief first reveals an attack, `attacks.revealed_day` is set and its outcome is frozen,
  so hindsight flags don't score as detection.
- The **after-action review** (once the generation ends) adds unresolved attacks, legit items
  each agent hurt (`false_positive` / `legit_blocked`), per-rule precision for blue, the score,
  and summaries of earlier generations within `reveal_generations`.
- Every disclosure is stored in `debriefs`. Plain episodes reveal nothing.

### Export and report

`GET /lineages/{id}/export` (operator) → `make lineage-export LN=` writes `runs/<lineage>/gen-<g>/`
(events, audit log, verdicts, attacks, score, credits, debriefs, playbooks; git-ignored, secret
scan applied). `make evolution-report LN=` (and `/fe/lineages/{id}/report|timeline`) builds a
deterministic report from the database: run card, score per generation, red tactic mix, blue
rules learned/retired with precision and recall, scheme × rule matrix, green throughput,
playbook timeline, and disclosure counts.

### What actually evolved on prod

- **`ln_f52a3df83c8d`** (5 gens × 8 days, enforce, seeds 502–506, red live, green and blue
  keyless, before #206): red re-weighted toward `threshold_split`, from 1 of 7 attacks in g1 to
  7 of 8 in g5; extraction $18,534 → $93,568 (live report, current scoring); all 19 splits extracted and no rule fired on them.
  Blue enabled all four learned controls after g1; `learned:young_vendor_any_amount` fired once.
  Red invented no schemes.
- **P9, `ln_431bf702e8a0`** (3 gens × 4 days, enforce, seeds 502–504, red **and** blue's audit
  live, green keyless, deploy 15f08b4 with #206/#195/#207): **$0 extracted** in all three
  generations; blocked $13,800 / $2,430 / $0; FP cost $100 / $50 / $0. `invoice_threshold_split`
  caught red's split 3 of 3 in g1, and red pivoted. **Blue learned nothing** ("Learned: none");
  the control that caught the split is the one we shipped, not a learned one. Blue caught 3 of 12
  launches; the $0 partly reflects red choosing `duplicate_invoice`, which never pays here (green
  holds a duplicate whose PO is already used), because red's ranking prefers uncaught failures over
  caught schemes.
- Keyless mock lineages (`battlefield/mock_agents`, deterministic `/reflect`) show a closed loop
  and are illustrations only.

## Scoring

`battlefield/app/scoring/score.py`, emitted as `score.updated`:

- `dollars_extracted`: payments whose source is red, plus legit payments diverted into a
  red-swapped account while the swap was live, minus a swap attack's own red invoices paid into
  the hijacked vendor's real account (#207 rescoring: the controller-on live-red run scores $0,
  not $1,824).
- `dollars_blocked`: red invoices/expenses blocked or rejected, red invoices of a frozen vendor
  never paid, legit invoices stopped while a red swap was live, and the target of a change-only
  attack stopped at the change.
- `false_positive_cost`: each legit item (`sim` invoices not stopped during a red swap, `sim`
  expenses, `sim` vendor changes at $0) is charged **once, by its worst outcome**: blocked
  (status blocked, any block verdict, or an escalation ending block/timeout) →
  amount × 2% (`FP_PENALTY_RATE`) + $50 (`FP_FLAT_PENALTY`); escalated but never blocked → $50.
  **Shadow verdicts count** as "would-have" costs; off has no verdicts and scores 0.
- `detection_latency_days`: mean(`detected_day − day_launched`) over detected attacks.
- `attacks_caught` (outcome `blocked`, `flagged` or `partial`) / `attacks_launched`,
  `legit_blocked`, `legit_processed`.

Read views use `score.live_attacks` (current scoring on unrevealed attacks), so the controls
report (`GET /fe/episodes/{id}/controls`) reconciles with #207 (#217).

## Droid SDK usage

All three agents subclass `agentkit.DroidAgent` (`agentkit/agentkit/droid_agent.py`). One Session
per live turn:

- `SessionConfig(system_prompt=<string from prompts/>, disable_builtin_skills=True,
  restrict_tools=<ids>, autonomy=…)`, `include_partial_messages=True`; thinking and text deltas
  become `agent.thinking`.
- **Tool ids** are `<server>___<tool>`. Green and blue pin theirs; red's come from its
  `@ledger_tool` names. Every session checks them against `session.list_tools()`: strict agents
  fail the turn before streaming on a missing or extra id; best-effort agents log the mismatch.
- **Tool events** come from the `ledger_tool` wrapper: exactly one `agent.tool_call` /
  `agent.tool_result` pair per call (executed, cancelled, refused, timed out), with arguments
  redacted by `redact=`.
- **Identity:** the SDK `tool_use_id` is the call's idempotency key (`X-Tool-Use-Id` on its first
  write, `<id>:<n>` on the n-th). Strict agents (green, blue) refuse unverified, explicit,
  ambiguous or conflicting ids before anything is sent (#84); binding waits for streamed
  arguments to complete (#195). UUID4 only under DRY_RUN or best-effort (red).
- **Timeouts:** `stream(timeout=TURN_TIMEOUT_SEC − 10)` (default 180 s); tool calls must finish
  within `TURN_TIMEOUT_SEC − 20` (min 5) of turn start; blue's audit budget
  `min(170, TURN_TIMEOUT_SEC − 10)`.
- **Turn loop and ownership:** live turns and reflections run on their own thread and event loop
  (`agentkit.sync.run_on_turn_loop`), so `/health` and `/gate` stay responsive. Every asyncio
  object belongs to the loop that created it; turn-scoped state shared across loops goes through
  `agentkit.TurnLock`. Tool coroutines run to completion on a worker pool (awaiting in-process MCP
  tools stalls the CLI).
- **Permission handlers** never return `PROCEED_ALWAYS*` or `PROCEED_AUTO_RUN*`. A call asks
  for permission iff its impact level exceeds the autonomy level, so `OFF` asks for every MCP call
  (confirmed live, #119) and `HIGH` for none.
- **Credits:** `turn_usage` logs `factory_credits` per turn at INFO and returns it in `usage`
  (blue's `/audit` too, #174/#176). Battlefield pauses an episode at `MAX_CREDITS_PER_EPISODE`.
- **Measured on prod (`gpt-5.4-mini`):** red median **~2,790 credits/turn** (1,043–3,725, 118
  turns), a full attack in ~11 s; blue audit median **~3,985 credits** (3.3k–5.4k) when its tools
  work (10.6k–18.7k only when retrying refused flags before #195); green 0 (keyless).
  `gemini-3.8-flash` stalled live turns to the 170 s timeout and was dropped (Finding, #118).
- **Pinning:** models come from `DROID_MODEL_*` deploy variables; no pin is enforced in code.
- Open question: whether a `CANCEL` comment reaches the model (green has never run live).

Findings with their proofs are in `contracts/CHANGELOG.md`.

## Readiness evidence

| Area | Evidence |
|---|---|
| Blue tool ids | All 7 `blue-ledger___*` ids matched by a real `Session.list_tools()` (SDK 0.5.0 / MCP 1.30.0, #68) |
| Blue controlled SDK probe | One OFF permission, verified SDK id = report header = confirmed receipt, one event pair; concurrent `/gate` 3.4 ms; 1,850 credits (`tests/sdk_authenticated_probe.py`) |
| Blue real Ledger, happy path | `ep_edd0d922b9a5` (#119): 6 calls, 6 permissions, one pair each; flag and report committed; same-key replay → audited 409; `/gate` p95 8.04 ms, max 56.6 ms over 1,817 samples |
| Blue real Ledger, interrupted | `ep_677e52f4197f` (#127, `gpt-5.4-mini`): battlefield killed mid-report → `unknown` receipt, 0 commits, replay 409; `/gate` max 69 ms |
| Blue live guard lift | #157; prod smoke `ep_f9c695b3144f`: live audits both days, 3,806 / 4,109 credits |
| Blue CRS, local | `ep_e1d35dfb24b1` exposed missing expense flags in the gate context (fixed #139); re-run `ep_0181eda1c921` passed: P12 flagged, its day-1 expense blocked, 19 checks all `billable:false` |
| Blue CRS, prod | `ep_c2c98b2da583` failed (streamed `{}` arguments refused, fixed #195); `ep_9cbc3362d44e` passed (#197) |
| Blue learned controls | Seeded baseline-vs-#83 comparison not run; lineage evidence above |
| Green tool ids | All 9 `green-ledger___*` ids observed by `list_tools()` (Finding #96, #94) |
| Green handler | Keyless: per-mode decisions, causes and fail-closed cases with mocked Ledger HTTP (#93/#94); 16-session SDK matrix proposed, not run; harnesses `tests/sdk_acceptance_harness.py` and `tests/sdk_stage_b_harness.py` refuse before SDK access |
| Preparations | DB suites: `battlefield/tests/test_preparations_db.py`, `test_consume_preparation_db.py`, `test_stale_verdict_db.py`, `test_escalation_db.py` |
| Joint live acceptance | 3-day all-real shadow (#78) not run (green keyless by decision); nearest: red + blue live off/enforce pair (#193), ep_89d1df6b012a / ep_d9b561111d60 |

Known open items: green's `ClerkState` is not guarded by `TurnLock` (safe only while green is
keyless); agents read `APPROVAL_THRESHOLD` with their own defaults rather than
`AgentSettings.approval_threshold`; the inline 403 lacks `cause`.
