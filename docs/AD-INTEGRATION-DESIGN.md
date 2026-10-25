# Agent integration design: packages A and B (Ad)

Status: **decided — Ad accepted D1–D14 as recommended on 2026-10-24 (§6).** The live hold is lifted:
prod runs red and blue's audit live (blue since 2026-10-25, #157), green keyless and on hold (per-agent `DRY_RUN_*`, #75). The contracts in §3 are on main
(#80, #86); `contracts/` supersedes the text below wherever they differ. Input: [`AD-AGENT-INTEGRATION-SPEC.md`](AD-AGENT-INTEGRATION-SPEC.md) and
its Green/Blue sources. Baseline: main `d0600d4` (#52, escalation e2e, merged unsplit). File:line
refs from §2 on are main at that commit; §1 is re-verified at a later commit (dated there).

**D1 reverses M's mirror design:** Green no longer calls Blue `/gate`; invariant 2's exception
(`AGENTS.md` §3.2) is deleted in PR 9. M has to know this before PRs 6/7.

## Progress (2026-10-24)

| Step (§5) | GitHub | State |
|---|---|---|
| 1 contracts (preparations, D1) | #80, #86 (`decided_by` nullable while pending) | merged |
| 2a battlefield preparations | #87 | merged |
| 2b gated routes consume preparations | #89 | merged |
| 3 strict identity, exact tool ids, `prepare()` | #84 | merged |
| 4 turn loop, `TurnLock`, `redact=` | #79 (+ #81 teardown) | merged, live for red on prod |
| 5 SDK findings | #91 (blue OFF, bounded), #96 (green tool ids); blue live evidence #119, #127 | partly; "OFF prompts on every MCP call" and CANCEL comment still open |
| 6 green live handler (M) | #93, #94 | merged; live green turn still guarded (`green/agent.py:81-83`) |
| 7 blue shared adapter (M) | #85, #88, #90 | merged; guard lifted (#157), live audit on prod since 2026-10-25 |
| 8 joint acceptance (3-day shadow, all live) | issue #78 | blocked on 6/7 |
| 9 cleanup | #97 (invariants 2/7, §5 rules, README) | partly; spec + this doc not yet deleted |

## 0. Summary of position

- Battlefield gets a **preparation** route that runs today's pre-mutation half of a gated route
  (validate → assemble context → gate → persist verdict/escalation/block) and stores a row that
  binds the key to action, args, mode, day, a state fingerprint and a fixed expiry. The gated
  route, called later with the same `X-Tool-Use-Id`, **consumes** that row (it does not call Blue
  again), still runs the #39 CAS, and refuses stale, expired or mismatched preparations with a 409.
- **Decided (D1): drop Green's call to Blue** (Option P). Once battlefield returns the effective
  decision, Green → Blue `/gate` replay adds no enforcement (invariant 3), only a new failure mode
  (Blue restart → legit action cancelled). Replay-only Blue (Option R) is kept in §2.9 only as the
  rejected alternative.
- Package B: #34 already carries the SDK id into events and headers. Missing at the baseline, since
  landed (#79, #84, #85, #88, #90; status in §1): refusing unverified/ambiguous ids live, a service
  loop the bridge can't block, loop-safe ownership, exact tool-ID checks, one narration owner for
  Blue. Spec conflicts/overreach: §2.10.

## 1. Gap table (strict: "partial" if any sub-bullet is missing)

Re-verified against origin/main @ `2a90f5e` on 2026-10-25. File:line refs in this section are at that
commit. `gatekeeper.py` = `battlefield/app/gate/gatekeeper.py`; `preparations.py`, `green_writes.py` are
in `battlefield/app/api/`; `droid_agent.py`, `invocation.py`, `ledger_client.py`, `sync.py` in
`agentkit/agentkit/`.

### Work package A

| # | Requirement (spec) | Status | Evidence |
|---|---|---|---|
| A1 | Battlefield prepares from verified id + normalized args, assembles complete stripped context, binds to episode/day/mode/action/entity/amount or GL fields/ledger state/expiry | **done** | `POST /api/preparations`: `preparations.py:139-215` (#87; contract #80, #86). Route's own state checks/404/409 first (`:166-194`), then the inline routes' stripped context (`green_writes.py:56-140`; expense context gains employee/expense flags `:104-112`, #139). Row binds key/day/agent/mode/action/entity/amount/args/`state_hash`/`expires_at` (`schema.sql:233-256`, insert `gatekeeper.py:676-713`); narrow fingerprint `preparations.py:56-84`. Battlefield can't verify the id (§2.10.1); agentkit does (B2) |
| A2 | Preparation may persist decisions/receipts/escalation, never performs the action | **done** | `prepare()` gates and persists only (`gatekeeper.py:538-600`): verdict, enforced block marks the entity `blocked` (D6, `:592-594`, `preparations.py:87-100`), escalation held to a decision (`gatekeeper.py:603-622`). No mutation rows; test `battlefield/tests/test_preparations_db.py:113` |
| A3 | Canonical envelope + effective result Green forwards unchanged; no incomplete mirror seeding Blue | **done** | Green's handler prepares one verified use and answers on `effective` (`green/agent.py:85-113`, `green/preparation.py:68-115`; #93, #94). No green → blue call (`BLUE_URL`/`/gate` in `green/`: none). Live green turn still hard-guarded (`green/agent.py:81-83`): a rollout gate, not this row |
| A4 | Blue replay-only: miss/expired/conflict/invalid fail explicitly, never evaluate or prime; complete same-action replay for 120 s | **n/a (D1)** | Green never calls Blue (`contracts/agent-service.md:145`). Blue's binding + 120 s retention stay for battlefield's own retries (`blue/gate/engine.py:20,55-70,90-110,157-162`) |
| A5 | Freshness, envelope validation, restart/cache-loss, 120 s vs 90 s, late human answer can't extend authority | **done** | #52: CAS close (`gatekeeper.py:385-402`), resolve without a waiter → timeout + 409 (`:484-496`), orphan sweep (`:499-509`, `main.py:44-52`). #87/#89: fixed 120 s expiry (`gatekeeper.py:695,712`), refused in enforce at consumption (`green_writes.py:270-273`; the claim re-checks `clock_timestamp() < expires_at`, `:308-316`); startup refuses `ESCALATION + GATE + 15 > 120` (`gatekeeper.py:517-524`, `main.py:36`); approval after expiry → block/timeout (`gatekeeper.py:650-664`); restart sweeps `pending` → block/timeout (`:716-727`, `preparations.py:227-233`). Inline verdicts bound to day + enforcement (A8); no wall-clock age within a day (by design: preparations carry the expiry) |
| A6 | Battlefield owns escalation, persists effective result; reuse, no duplicate human requests | **done** | One single flight per key for `check()` and `prepare()` (`gatekeeper.py:147-163`); replay joins/reuses the key's escalation (`_join_escalation`, `:463-481`); a pending re-prepare joins or abandons, never a second card (`:625-647`). Effective result stored on the preparation (`effective/decided_by/decided_at`, `:650-664`; `escalation_id` `:446,634`), per §2.3 rather than on the verdict |
| A7 | Persist enforced blocks even when SDK cancels; distinguish fraud hold vs integration/auth/transport failure in events, receipts, summaries | **partial** | Done: block persisted at preparation, so a cancelled call still records it (`gatekeeper.py:592-594`, D6); `verdicts.cause` (`:195-197,224-245`, `schema.sql:210`) on `gate.verdict` (`gatekeeper.py:263`) and `escalation.opened` (`:441-443`); prepared 403 carries `cause`/`decided_by`/`preparation_id` (`green_writes.py:274-287`); green's cancel comment and turn summary carry the cause (`green/preparation.py:48-55,114-115`, `green/workflow.py:93-109`). Missing: the inline (unprepared) 403 omits `cause`/`decided_by` (`green_writes.py:163-164`; nullable in `ledger-api.yaml:253-262`) |
| A8 | Execution consumes only a matching valid preparation, keeps validation + #39 CAS; state/mode/args change, expiry, identity conflict reject without retry | **done** | `_prepared` (`green_writes.py:251-288`): binding (every mode) → consumed/pending → mode/day stale (every mode) → enforce: expired, stored block 403. `_consume` runs in the txn before the #39 CAS: mode `FOR SHARE`, claim on `consumed_at IS NULL`, fingerprint recomputed `FOR UPDATE` (`:291-324`) (#89). Pay re-reads the vendor in txn (`:548-550`). Inline replay refuses another day/enforcement (`StaleVerdictError`, `gatekeeper.py:71-81,294-301`; #147, #151). Tests: `battlefield/tests/test_consume_preparation_db.py`, `test_stale_verdict_db.py` |
| A9 | Contract-backed `LedgerClient` methods + config; review threshold wiring, no second default | **partial** | Done (#84): `LedgerClient.prepare`/`get_preparation` (`ledger_client.py:168-184`, refuses a non-SDK source `:173-174`), typed `PreparationRejected` (`:56-65,139-144`), `GateBlocked.cause/escalation_id/preparation_id` (`:44-53`); `AgentSettings.approval_threshold` as the agent default (`agentkit/agentkit/config.py:35-36`) and `APPROVAL_THRESHOLD` in the `x-agent-env` anchor (`docker-compose.yml:29-30`). Missing: agents still read the env with their own default instead of `AgentSettings`: `green/workflow.py:219`, `blue/gate/rules.py:31-32`, `red/schemes/bank_swap.py:20`, `red/schemes/threshold_split.py:174` |

**Verdict replay vs mode/day (current, `2a90f5e`).** A stored verdict for the key replays only for the
same action (`same_action`, `gatekeeper.py:304-320`) and only on its own day and under its own
enforcement: `_refuse_stale` (`:294-301`) compares `verdicts.day` with `X-Day` and `verdicts.enforced`
with the current mode and raises `StaleVerdictError` (`:71-81`) → audited
`409 {"error":"stale verdict","verdict_id"}` (contract #147: `agent-service.md:150-154`,
`ledger-api.yaml:57`; code #151). `prepare()` runs the same check before reusing an inline verdict
(`:580-581`). So a shadow block no longer replays as an enforced 403, an enforce block no longer
replays as allowed in shadow, and a human approval no longer carries to another day
(`battlefield/tests/test_stale_verdict_db.py`). Unchanged: in `off` the lookup is skipped
(`gatekeeper.py:140-142`), so a prior verdict for the key is ignored. History: on `d0600d4` replay
compared only action/entity/amount/args and ran under the current mode, with no day check.

### Work package B

| # | Requirement | Status | Evidence |
|---|---|---|---|
| B1 | Genuine SDK id across permission, execution, events, headers, receipts; write 1 = id, n-th = `<id>:<n>` | **done** | Registration from permission and stream (`invocation.py:347-372`, `droid_agent.py:405-426,655-664`), claim (`invocation.py:387-433`), events from `_offload` (`droid_agent.py:541-606`), header and `<id>:<n>` keys (`ledger_client.py:115-130`, `invocation.py:92-94`). Execution ↔ id is argument correlation by necessity (Finding: the CLI never passes the id to the handler, `contracts/CHANGELOG.md:15-20`). Blue receipts use the shared verified id (`blue/audit/tools.py:86-98,155-163`; #67, #85) |
| B2 | Live mutations reject missing/ambiguous/conflicting/unverified identity; no local UUID, explicit test id, model args, last-id, suffix | **done** (strict agents, D7) | #84: strict live refuses an explicit `_tool_use_id` and unlinked executions, tool body never runs (`droid_agent.py:471-483,541-547`); ambiguous/conflicting refused, no FIFO (`invocation.py:406-433`); writes without a verified invocation raise `UnverifiedInvocation` (`ledger_client.py:115-121`); `tool_uses()` without a registry raises live (`droid_agent.py:271-275`); no suffix match (`:684-707`). Green and blue set `identity="strict"` (`green/agent.py:48`, `blue/audit/agent.py:42`); red stays best_effort with the UUID4 fallback (`droid_agent.py:490-507`) pending Al |
| B3 | Exactly one call/result pair for executed, cancelled, refused, interrupted, timed-out; reconcile Blue's private decorator | **done** | Executed/timed-out/failed/refused: `droid_agent.py:541-606`; cancelled: `:419-422`; never ran: `invocation.py:488-535`. Blue's `blue_tool` wraps the shared `ledger_tool(..., redact=)` and claims the shared invocation: one pair per call (`blue/audit/tools.py:59-126`; #85). Proven live for blue: one pair per permission id (#119, `blue/SDK-READINESS.md:323-327`) |
| B4 | Bridge nonblocking for the service loop; keep bounded deadlines, cancellation, draining, unknown-outcome | **done** | Live turns and reflections run on their own thread + loop (`droid_agent.py:308-327,356-367`, `sync.py:71-134`; #79, #81). The blocking `concurrent.futures.wait` is still there (`droid_agent.py:574`) but freezes only the turn loop the Session lives on (`:525-526`), never the service loop. Deadlines `:434-469`; cancel forwarded with `call_soon_threadsafe` + bounded join (`sync.py:137-154`); narration drained on the turn loop (`droid_agent.py:93-132,600-601`); unknown outcome on timeout (`:576-590`). D14 (DRY_RUN on the turn loop) is opt-in: default off (`:204-208`), on for green and red (`green/agent.py:49`, `red/agent.py:23`), off for blue |
| B5 | Safe ownership of locks, clients, snapshots, receipt/clerk state across loops | **partial** | Done (#79, #85, #88): `TurnLock` (`sync.py:186-274`) for blue's audit lock (`blue/audit/agent.py:48`) and per-session tool lock (`:91`, `blue/audit/models.py:82`), which serializes `session.effects` writes (`blue/audit/tools.py:70`); registry and `EventEmitter` assert their owner thread (`invocation.py:299,310-312`, `agentkit/agentkit/events.py:52-55,88-97`); fresh per-worker `LedgerClient` (`droid_agent.py:559`). Missing: green's `ClerkState` is plain sets mutated by the permission handler on the turn loop and by tools on worker threads, with no `TurnLock` (`green/workflow.py:49-60,150-195`, `green/agent.py:94-111`); serialized today only because a sync tool freezes the turn loop, and live green is guarded |
| B6 | Verify exact Green/Blue session tool IDs + first-session restriction; Green autonomy stays off | **done** | IDs observed and pinned: green (`green/agent.py:20-31,54-57`; Finding #96, evidence on #94), blue (`blue/audit/agent.py:27-36,47,61-63`; #68, #90). First Session restricted from the pinned list (`droid_agent.py:632`); exact-set check, strict fails the turn before `stream()` (`:649-650,684-707`; #84). Green `autonomy="off"`: `green/agent.py:47`. Live proof that the restriction holds for green is B7 |
| B7 | Authorized isolated live measurement of callbacks, correlation, cancel comment, timeout cleanup; record findings | **partial (D15)** | Blue measured live in local runs: one OFF `post_report` permission + id parity (Finding #91, `contracts/CHANGELOG.md:13`); under an Ad-authorized budget, a full real-Ledger audit with a permission per call, one pair per id, `/gate` max 56.6 ms (#119), and an interrupted write → `unknown` receipt, refused replay (#127) (`blue/SDK-READINESS.md:292-367`). Missing: CANCEL comment delivery, OFF-every-call beyond blue, permission-callback timeout during a held escalation (still open: `contracts/CHANGELOG.md:55-57`); green's live matrix not run (`green/SDK-ACCEPTANCE.md:3`) |

### Acceptance checklist

| Item | Status | Note |
|---|---|---|
| Ad decisions recorded; contracts merge first; Green/Blue review | done | §6; contracts #80/#86 merged before #87/#89; M built on them (#85, #88, #90, #93, #94) |
| Tests: complete context, replay hit/miss/expiry/conflict, state/mode change, concurrent identical, cancelled blocks, one reused escalation | done | `battlefield/tests/test_preparations_db.py`, `test_consume_preparation_db.py`, `test_stale_verdict_db.py`, `test_escalation_db.py`, `test_green_writes_db.py` |
| Off skips Blue; shadow observes; enforce follows effective decision; auth/identity/ledger validation in every mode | done | `gatekeeper.py:583-599`, `green_writes.py:251-288`; tests `test_preparations_db.py:79-113`, `test_consume_preparation_db.py:169-243` |
| Permission → events → ledger write/receipt ids match incl. cancelled/timed-out; one pair; no blind retry | partial | Code done (B1–B3); proven live for blue only (#119, #127); green live unrun |
| Owner-loop safety and `/gate` responsiveness during live audit; 8 s budget | partial | `/gate` max 56.6 ms during an authorized local live audit (#119), 69 ms under interruption (#127); green clerk state open (B5); blue's `LIVE_BLOCKERS` emptied (#157; asserted by `blue/tests/test_sdk_readiness.py:50`) |
| No-key DRY_RUN, lint, actual SDK acceptance with versions/SHAs | partial | DRY_RUN suites pass per owners; blue SDK acceptance recorded with droid-sdk 0.5.0 / mcp 1.30.0 (#119, #127); green none |
| One shared stack, matching off/shadow/enforce seeds ×2 | missing | Operator-authorized only (D15 hold) |
| Verifier/steward, PRs < 600 lines; durable docs, spec deleted last | partial | Steward/verifier loop runs (`AGENTS.md` §10); invariants 2/7 and §5 updated (#97); spec and this doc not yet deleted (PR 9) |

## 2. Protocol design (package A)

### 2.1 Flow (Option P, accepted D1)

```
model → CLI permission request (tool_use_id T, args)                         [Autonomy.OFF]
  green on_permission: map tool+args → (action, entity_id, body); POST /api/preparations
        X-Tool-Use-Id: T     ← battlefield: 404/409 checks, context, Blue /gate (8 s), persist verdict,
                               enforce+block → entity 'blocked' + audit 403-equivalent,
                               enforce+escalate → open escalation, HOLD ≤ ESCALATION_TIMEOUT_SEC,
                               store effective result; 200 Preparation
  effective=allow → PROCEED_ONCE ; effective=block → CANCEL(comment=reason, cause)
CLI executes tool → LedgerClient.pay_invoice, X-Tool-Use-Id: T (first write of the invocation)
  battlefield gated route: load prep(T) → binding/day/mode/expiry checks → txn{ CAS entity;
        recompute fingerprint FOR UPDATE; consume prep (CAS consumed_at IS NULL); mutate }
```
No preparation for the key → the route gates inline exactly as today (DRY_RUN, mock agents and any
caller that skips preparing keep working; enforcement is unchanged).

### 2.2 Routes

| Method, path | Who | Request | Responses |
|---|---|---|---|
| `POST /api/preparations` | green (`X-Agent`, `AGENT_TOKEN`, `X-Episode`, `X-Day`, `X-Tool-Use-Id` = SDK id) | `{action, entity_id?, args{}}`; `action` ∈ the 9 gated actions; `args` = the route body the execution will send (GL: the `GlEntryCreate` body; no `entity_id`) | `200 Preparation` (allow **or** block; a block is a successful preparation). `404` entity/PO not found. `409 {error:"invalid_state",detail:"invoice is paid"}` (step-1 checks of the route). `409 {error:"idempotency key reused for a different action",verdict_id}`. `409 {error:"no active turn for this agent"}` (#52 guard, `turns.py:19`, `auth.py:96`). `422` unknown action/body. All audited (`action="prepare:<action>"`) |
| `POST` same key, same action again | green | identical | `200` the stored Preparation unchanged (no Blue call, joins a pending escalation, never opens a second one) |
| `GET /api/preparations/{key}` | green | — | `200 Preparation` (incl. `consumed`, `consumed_status`), `404`. For reconciling an unknown-outcome tool without retrying |
| gated routes (existing 9) | green | unchanged | new `409 PreparationRejected {error, preparation_id, detail}` with `error` ∈ `preparation_expired`, `preparation_stale`, `preparation_consumed`, `preparation_pending`; `403 GateBlocked` gains `cause`, `decided_by`, `preparation_id` |

`200`-for-block is deliberate: `LedgerClient` raises `GateBlocked` on 403, which would conflate
"the gate said no" with "the call failed". The typed model makes `effective` required.

### 2.3 Persisted state

New core table `preparations` (DDL in §3.4), one row per episode+key in every mode (off rows have no
verdict). It holds the binding (compared like `same_action`, `gatekeeper.py:206-220`), mode, day,
`state_hash` (§2.4), `effective` (`allow`/`block`/`pending` while escalated), `decided_by`
(`mode`/`gate`/`human`/`timeout`), a fixed `expires_at`, and `consumed_at/consumed_status` (set in the
execution txn). The verdict row stays the record of what Blue said; the preparation row records
what execution may do. `verdicts.cause` = `control` (Blue evaluated supplied context) or `gate_unavailable` (fallback in
`_ask_blue`). Fraud hold = `effective=block` with `cause=control`; infra = `cause=gate_unavailable`
(in enforce that becomes an escalation; its card and `gate.verdict` carry the cause).

### 2.4 Freshness and the state fingerprint

| Action | Fingerprint fields (current values, provenance-stripped) |
|---|---|
| `invoices.match` | invoice{amount,vendor_id,po_id}, proposed PO{vendor_id,amount,status}, vendor{status} |
| `invoices.approve/reject/pay` | invoice{amount,vendor_id,po_id}, vendor{status,bank_account,bank_routing,name}, PO{vendor_id,amount,status} or null |
| `vendor_changes.approve/reject` | change{vendor_id,field,new_value}, vendor{status, value of `field`} |
| `expenses.approve/pay` | expense{amount,employee_id}, employee{status,bank_account,hr_record} |
| `gl.post` | none (args are the whole action) |

The subject entity's `status` is excluded on purpose: the CAS already guards it, and including it
would make "approve then pay" prepared back-to-back go stale. History lists (paid invoices, recent
changes) are excluded so paying invoice A doesn't invalidate invoice B of the same vendor.

Timing rule (answers the 120 s / 90 s question):
- `PREPARATION_TTL_SEC = 120` (constant; equals Blue's cache TTL). Authority ends at
  `created_at + 120 s` regardless of when a human answers. Escalation resolution never extends it.
- Startup check: `ESCALATION_TIMEOUT_SEC + GATE_TIMEOUT_SEC + 15 ≤ 120` (default 90 + 8 + 15 = 113);
  otherwise battlefield refuses to start. A human answering at the last moment (t0 + 8 + 90) leaves
  22 s at defaults (≥ 15 s guaranteed) to execute. A resolve after the escalation's `expires_at`
  is already a timeout/409 (`gatekeeper.py:359-371`).

### 2.5 Execution consumes a preparation

Order inside a gated route when `preparations(episode, key)` exists:
0. GL only: the #39 audit-log replay (`green_writes.py:510-525`) runs first, unchanged.
1. Binding ≠ (action, entity, amount ±1¢, args) → `409 idempotency key reused…` (all modes).
2. `consumed_at` set → `409 preparation_consumed` with `consumed_status` (no second mutation;
   Green reconciles). `effective=pending` → `409 preparation_pending`.
3. `controller_mode ≠ current` or `day ≠ X-Day` → `409 preparation_stale` (all modes).
4. Enforce only: `now ≥ expires_at` → `409 preparation_expired`; `effective=block` →
   `403 GateBlocked` (stored reason, no Blue call, no new escalation).
5. Transaction: CAS (unchanged) → recompute fingerprint with `FOR UPDATE` reads → mismatch in
   enforce rolls back → `409 preparation_stale` → `UPDATE preparations SET consumed_at=now(),
   consumed_status=<2xx> WHERE id=$1 AND consumed_at IS NULL RETURNING` (0 rows → rollback, 409
   consumed) → mutation rows. Audit + `ledger.mutation` carry `verdict_id` and `preparation_id`.
6. Shadow/off: expiry and fingerprint drift are audited (`result.stale=true`) but don't refuse.

No automatic retry anywhere: a 409 goes to the model as a tool error; a new tool call gets a new id.

### 2.6 Escalation ownership

- Opened only by preparation (or the inline path when unprepared), held in the prepare request.
  Effective result written to `preparations.effective/decided_by/decided_at` in the same transaction
  that closes the escalation (CAS on `status='open'`, `_close`, `gatekeeper.py:274-291`).
- Same key again (re-prepare or execution): reads the stored result, or joins the open waiter
  (`_join_escalation`, `gatekeeper.py:338-356`). Never a second escalation for one key.
- Client gave up mid-hold: row stays `pending` and the hold continues; execution meanwhile gets
  `409 preparation_pending`. Prepare's read timeout must exceed the hold (`ledger_client.py:55`, sized by #52).

### 2.7 Restart and cache loss

| Event | Behavior |
|---|---|
| Battlefield restart | Rows persist; `expires_at` is wall-clock. Startup sweep (`recover_after_restart`, `main.py:43-59`) also sets `pending` rows to `block / timeout`. The active-turn guard (`turns.py`, `auth.py:96`) 409s writes from turns orphaned by the restart, so old preparations can't be used |
| Blue restart | Irrelevant to execution (the verdict is in battlefield); a prepare during the outage gets `cause=gate_unavailable` |
| Green restart | Turn dies; rows expire unconsumed; registry close emits `not_run` pairs |

### 2.8 Mode semantics and failure classes (Green handler, Option P)

| Prepare outcome | off | shadow | enforce |
|---|---|---|---|
| `200 effective=allow` | PROCEED | PROCEED | PROCEED |
| `200 effective=block` | n/a | n/a (always allow) | CANCEL, `cause=control_hold` (or `escalation_timeout`) |
| `404/409 invalid_state`, `409 key conflict` | CANCEL (ledger validation / identity) | CANCEL | CANCEL |
| 401/403/5xx/timeout/network/malformed body | PROCEED (execution gates inline) | PROCEED | CANCEL, `cause=integration_failure` |

Mode is the **turn's** `controller_mode` for the handler's fallback only; battlefield decides from
the current mode. A mode switch mid-turn is caught by step 3 of §2.5. Cancel comments and the
`agent.tool_result` summary carry `cause` so Green's summary separates fraud holds from integration
failures. A fraud block is already persisted at preparation, so CANCEL loses nothing.

### 2.9 Option R: Blue replay-only (rejected by D1)

Kept for the record. R would have had the preparation return the exact `GateRequest` plus a sha256
digest, and Blue add a Green-only `POST /gate/replay` that never evaluates or caches (`404` miss,
`409` pending / key conflict / digest mismatch, `200` stored verdict verbatim). Rejected because it adds
no enforcement over the ledger (invariant 3), adds a failure mode (Blue restart → legit action
cancelled), and Blue can't tell battlefield from Green anyway (both hold `AGENT_TOKEN`,
`agent-service.md:10,20`), so the route split would only stop *accidental* priming (D2).

### 2.10 Conflicts and overreach in the spec

1. "Prepares from **verified** invocation identity": battlefield can't verify an SDK id. It can
   authenticate the agent, require an active turn and bind the key. Verification is agentkit's job
   (B-1); the contract says agents MUST send only SDK-reported ids.
2. Replay-only Blue is redundant under invariant 3. The ledger enforces; a replay re-reads what
   battlefield already stored. Decided P (D1).
3. Spec demands strict rejection of unverified ids. That changes invariant 7 ("else a UUID4") for
   live Droid calls and would break red (Autonomy HIGH, stream-only ids that race execution,
   `invocation.py:38-43`). Scoped to green and blue; red needs Al (D7).
4. "Ambiguous" ids: FIFO among identical approved calls is deliberate on main
   (`invocation.py:41-43`); strict rejection is a behavior change (accepted, D8).
5. "`/gate` during concurrent live audit": the orchestrator never overlaps green's turn with blue's
   audit (`events.md` ordering). B4 is still right (health, orphaned turns), but not a live race.
6. Holding the permission callback up to ~98 s: the CLI may have its own permission timeout
   (unknown). B7 must measure it before relying on in-handler escalation holds (D15 hold: until then
   this is an unverified assumption). Turn budget: two held escalations already exceed
   `TURN_TIMEOUT_SEC=180`.
7. #52's `409 no active turn` (`turns.py:19`, `auth.py:96`, handler `main.py:65-66`) was implemented
   before it was contracted; #80 contracted it (`ledger-api.yaml` info and `ConflictError`).

### 2.11 Alternatives rejected

| Alternative | Why not |
|---|---|
| Extend `verdicts` instead of a new table | Off mode has no verdict (`verdict NOT NULL`); mixes "what Blue said" with "what may execute" |
| Full-context hash as fingerprint | Paying one invoice invalidates every sibling's preparation; constant stale churn |
| HMAC-signed envelope | Green holds the same `AGENT_TOKEN`, so a signature proves nothing; the digest comparison is enough |
| 202 + polling for escalations | Adds a poll loop to the permission handler; the hold already works and is bounded |
| Execution re-evaluates on stale preparation | Spec: no automatic retry; a re-evaluation could open a second escalation |
| Separate gate token now | New env var + compose change for a threat (malicious Green) outside the model (D2) |

## 3. Proposed contract changes (text for PR1; applied in #80, #86, `contracts/` supersedes)

Option R text is removed (D1). The `409 no active turn` line in §3.1 is **already implemented on
main** (#52: `turns.py:19`, `auth.py:96`, `main.py:65-66`, tests `battlefield/tests/test_turn_guard_db.py`);
PR1 only puts it in the contract.

### 3.1 `contracts/ledger-api.yaml`

```yaml
# components.schemas — add
    PreparationCreate:
      type: object
      required: [action]
      properties:
        action: { type: string, enum: [invoices.match, invoices.approve, invoices.reject, invoices.pay, vendor_changes.approve, vendor_changes.reject, expenses.approve, expenses.pay, gl.post] }
        entity_id: { type: string, description: "required except for gl.post" }
        args: { type: object, description: "the exact body the execution will send (gl.post: GlEntryCreate)" }
    Preparation:
      type: object
      required: [preparation_id, idempotency_key, controller_mode, day, action, effective, decided_by, expires_at, consumed]
      properties:
        preparation_id: { type: string }
        idempotency_key: { type: string, description: "X-Tool-Use-Id of the prepare call = first write key of the tool call" }
        controller_mode: { type: string, enum: [off, shadow, enforce] }
        day: { type: integer }
        action: { type: string }
        entity_type: { type: string, nullable: true }
        entity_id: { type: string, nullable: true }
        amount: { $ref: '#/components/schemas/Money' }
        effective: { type: string, enum: [allow, block, pending], description: "what execution under this key will do; shadow/off always allow" }
        enforced: { type: boolean }
        decided_by: { type: string, enum: [mode, gate, human, timeout] }
        verdict_id: { type: string, nullable: true }
        verdict: { type: string, enum: [allow, block, escalate], nullable: true }
        cause: { type: string, enum: [control, gate_unavailable], nullable: true }
        reason: { type: string }
        rules_fired: { type: array, items: { type: string } }
        escalation_id: { type: string, nullable: true }
        expires_at: { type: string, format: date-time, description: "created_at + 120 s; never extended" }
        consumed: { type: boolean }
        consumed_status: { type: integer, nullable: true }
    PreparationRejected:
      type: object
      required: [error, preparation_id]
      properties:
        error: { type: string, enum: [preparation_expired, preparation_stale, preparation_consumed, preparation_pending] }
        preparation_id: { type: string }
        detail: { type: string, description: "e.g. 'mode changed', 'day changed', 'state changed: vendor.bank_account'" }
    GateBlocked:            # add to properties
        cause: { type: string, enum: [control, gate_unavailable], nullable: true }
        decided_by: { type: string, enum: [gate, human, timeout], nullable: true }
        preparation_id: { type: string, nullable: true }
# paths — add
  /preparations:
    post:
      summary: Prepare a gated green action. Validates, gates and persists the decision (and any block or escalation); never performs the action.
      description: |
        Same key + same action returns the stored preparation (no new gate call, no second escalation).
        In enforce an escalate verdict holds this request until a human decides or ESCALATION_TIMEOUT_SEC.
        A later gated call with the same X-Tool-Use-Id consumes it (409 PreparationRejected on the x-gated routes).
        Agents MUST send only an SDK-reported tool_use_id here; battlefield binds it, it cannot verify it.
      x-agents: [green]
      security: [ { agentBearer: [] } ]
      parameters: [ { $ref: '#/components/parameters/XAgent' }, { $ref: '#/components/parameters/XEpisode' }, { $ref: '#/components/parameters/XDay' }, { $ref: '#/components/parameters/XToolUseId' } ]
      requestBody: { content: { application/json: { schema: { $ref: '#/components/schemas/PreparationCreate' } } } }
      responses:
        '200': { content: { application/json: { schema: { $ref: '#/components/schemas/Preparation' } } } }
        '404': { description: entity or referenced PO not found }
        '409': { description: "{error: invalid_state | 'idempotency key reused for a different action' | 'no active turn for this agent', detail?, verdict_id?}" }
        '422': { description: unknown action or body }
  /preparations/{key}:
    get: { x-agents: [green], security: [ { agentBearer: [] } ], parameters: [ { name: key, in: path, required: true, schema: { type: string } } ],
           responses: { '200': { content: { application/json: { schema: { $ref: '#/components/schemas/Preparation' } } } }, '404': { description: none } } }
# every x-gated route — add to responses
        '409': { description: "PreparationRejected, idempotency conflict, or entity state", content: { application/json: { schema: { $ref: '#/components/schemas/PreparationRejected' } } } }
# info.description — add: "Any agent write outside that agent's active turn → 409 {error: 'no active turn for this agent'} (audited)."
```

### 3.2 `contracts/agent-service.md`

```diff
 ## Green
-`/turn` options: `{}`. Green works the AP queue: match → approve → pay, resolve vendor changes,
-approve/pay expenses, post GL entries for what it paid. Green's Droid permission handler mirrors
-`POST blue/gate` with the same `idempotency_key` (= `X-Tool-Use-Id`) and returns `CANCEL` when
-the verdict is `block`; the ledger-side gate is still the enforcement point.
+`/turn` options: `{}`. Green works the AP queue: match → approve → pay, resolve vendor changes,
+approve/pay expenses (automatic GL deferred, D12). Green's permission handler calls `POST /api/preparations` with the call's
+SDK `tool_use_id` as `X-Tool-Use-Id` and returns `CANCEL` when `effective` is `block`, or (enforce
+only) when preparation fails. The gated route later consumes that preparation; it remains the
+enforcement point. Green never calls blue.
+Live Droid writes use only SDK-reported ids (permission or stream). A tool call the SDK reported
+no unique id for is not executed. DRY_RUN and non-Droid calls use UUID4.
 ## Blue
-- `/gate` is idempotent on `idempotency_key` for 120 s (same key → same verdict, no re-evaluation).
+- `/gate` is called only by battlefield. It is idempotent on `idempotency_key` for 120 s (same key →
+  same verdict, no re-evaluation).
```
(Also drop "green → blue `/gate` mirror" from the token table, `agent-service.md:10`. In PR 9:
`AGENTS.md` §3.2 deletes the green → blue exception (D1); §3.7 "else a UUID4" → "DRY_RUN /
non-Droid calls only" (D7).)

### 3.3 `contracts/events.md`

```diff
-| `ledger.mutation` | battlefield | `{agent, action, entity_type, entity_id, amount?, verdict_id?}` |
-| `gate.verdict` | battlefield | `{verdict_id, agent, action, entity_type?, entity_id?, amount?, verdict, reason, confidence?, rules_fired: string[], enforced}` |
-| `escalation.opened` | battlefield | `{escalation_id, verdict_id, action, entity_type?, entity_id?, amount?, reason, expires_at}` |
+| `ledger.mutation` | battlefield | `{agent, action, entity_type, entity_id, amount?, verdict_id?, preparation_id?}` |
+| `gate.verdict` | battlefield | `{verdict_id, agent, action, entity_type?, entity_id?, amount?, verdict, reason, confidence?, rules_fired: string[], enforced, cause?: "control"\|"gate_unavailable", preparation_id?}` — emitted once per key, at preparation when prepared |
+| `escalation.opened` | battlefield | `{escalation_id, verdict_id, action, entity_type?, entity_id?, amount?, reason, expires_at, cause?}` |
```
No new event types. Green's cancel pair stays `agent.tool_result {ok:false}`; its summary JSON
carries `cause` (`control_hold | escalation_timeout | integration_failure | invalid_state`).

### 3.4 `contracts/schema.sql`

```sql
-- core section, after escalations
CREATE TABLE IF NOT EXISTS preparations (
  id               TEXT PRIMARY KEY,                       -- prep_
  episode_id       TEXT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
  idempotency_key  TEXT NOT NULL,
  day              INTEGER NOT NULL,
  agent            TEXT NOT NULL,
  controller_mode  TEXT NOT NULL CHECK (controller_mode IN ('off','shadow','enforce')),
  action TEXT NOT NULL, entity_type TEXT, entity_id TEXT, amount NUMERIC(14,2),
  args             JSONB NOT NULL DEFAULT '{}',
  state_hash       TEXT NOT NULL,                          -- sha256 of the §2.4 fingerprint
  verdict_id       TEXT REFERENCES verdicts(id),           -- NULL in off
  escalation_id    TEXT REFERENCES escalations(id),
  effective        TEXT NOT NULL CHECK (effective IN ('allow','block','pending')),
  decided_by       TEXT CHECK (decided_by IN ('mode','gate','human','timeout')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(), decided_at TIMESTAMPTZ, expires_at TIMESTAMPTZ NOT NULL,
  consumed_at TIMESTAMPTZ, consumed_status INTEGER,
  UNIQUE (episode_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS preparations_pending ON preparations(episode_id) WHERE effective = 'pending';

-- additive upgrades section
-- 2026-10-2x: verdicts.cause (existing rows NULL = unknown; read as 'control' unless rules_fired has 'gate_timeout').
ALTER TABLE verdicts ADD COLUMN IF NOT EXISTS cause TEXT CHECK (cause IN ('control','gate_unavailable'));
```

### 3.5 `contracts/CHANGELOG.md` and `agentkit/agentkit/models.py`

```
- 2026-10-2x · Ad · ledger-api.yaml, agent-service.md, events.md, schema.sql, models.py · gated actions
  can be prepared (POST/GET /preparations; preparations table; 120 s fixed expiry; execution consumes
  the preparation, 409 PreparationRejected on stale/expired/consumed/pending); verdicts.cause;
  GateBlocked/gate.verdict/escalation.opened gain cause; green no longer calls blue;
  live Droid writes require SDK-reported ids; 409 for agent writes outside the active turn · green (M), blue (M), red (Al), frontend (R)
```
`models.py` (contracts area, GIT.md §2): `PreparationCreate`, `Preparation`, `PreparationRejected`;
`GateResponse` unchanged.

## 4. Package B remaining work (agentkit; Ad)

| # | Change | Files |
|---|---|---|
| B-1 | Identity policy `identity: Literal["strict","best_effort"]` on `DroidAgent` (default strict when `autonomy=="off"`, set by Blue; red keeps best_effort). Strict + live: `_begin_invocation` refuses explicit `_tool_use_id`, refuses unlinked executions (tool body never runs; result `{"error":true,"identity":"unverified","not_run":true}`; one pair under a local id marked `unverified`), and refuses when >1 approved identical entry or an `_meta` hint conflicts with the argument match (`ambiguous`/`conflicting`) | `agentkit/agentkit/droid_agent.py:369-387`, `invocation.py:343-359` (`claim` returns a reason, not None) |
| B-2 | `LedgerClient._write` in strict live mode: raise `UnverifiedInvocation` before sending if there is no current invocation or `not inv.verified`; keep UUID4 only for DRY_RUN/best_effort. New `prepare(use: ToolUse, action, entity_id, args)` requires `use.source in VERIFIED_SOURCES`; `get_preparation(key)`; typed `PreparationRejected(LedgerError)`; `GateBlocked` keeps `cause`, `escalation_id`, `preparation_id` | `agentkit/agentkit/ledger_client.py:38-46,94-121`; models from PR1 |
| B-3 | Exact tool IDs: compare `session.list_tools()` against `{f"{server}___{n}"}` (no suffix match); in strict mode a missing or extra ID fails the turn before `stream()`. `tool_uses()` without a bound registry raises in live mode instead of building a throwaway one | `droid_agent.py:229-235,518-519,549-560` |
| B-4 | Nonblocking bridge: run each turn (live **and** DRY_RUN, D14) on a dedicated per-turn thread with its own loop (`TurnLoop`): context copied in, `LedgerClient`/`EventEmitter`/Session created there, service loop awaits `asyncio.wrap_future`; service-side cancel → `call_soon_threadsafe(task.cancel)` with bounded join; tools still offload to worker loops (SDK Finding). Keeps #52's `_tool_budget_sec` / `read_timeout_sec` | `droid_agent.py:255-277,389-478`, `server.py:50-58`, `events.py` (owner-loop assertion) |
| B-5 | Ownership rules + helpers: every asyncio object belongs to the loop that created it; cross-loop only via `call_soon_threadsafe`. Provide `agentkit.TurnLock` (threading-backed, awaitable from any loop) and document that turn-scoped mutable state touched from tools must use it. Registry calls from worker threads are forbidden (assert) | `agentkit/agentkit/invocation.py:245-260`, new `agentkit/agentkit/sync.py`, `__init__.py` |
| B-6 | One narration owner: `ledger_tool(name, desc, *, redact=fn)`; `_offload` applies `redact` to `tool_call.args` so Blue can drop its private pair and `INVOCATION` marker (C) | `agentkit/agentkit/tools.py:98-138`, `droid_agent.py:421` |
| B-7 | Config: `AgentSettings.approval_threshold: Decimal = 5000` (`APPROVAL_THRESHOLD`) as the single agent-side default; add `APPROVAL_THRESHOLD` to the `x-agent-env` anchor (green currently lacks it) | `agentkit/agentkit/config.py`, `docker-compose.yml:15-26` (mock green inherits it) |
| B-8 | **On hold (D15).** Authorized live probe (no paid sessions without Ad's go): OFF permission per MCP call, Blue impact level at its autonomy, callback timeout during a 90 s hold, CANCEL comment delivery, timeout cleanup; record in Findings | `agentkit/scripts/sdk_probe.py`, `contracts/CHANGELOG.md` |

## 5. Implementation plan

#52 landed the escalation e2e work unsplit, so the old prerequisite PRs 0a/0b/0c are gone (D10).

| PR | Branch | Files (exclusive while open) | Tests | Size | Needs |
|---|---|---|---|---|---|
| 1 | `contracts/gate-preparation` | `contracts/*` (§3), `agentkit/agentkit/models.py` | schema applies twice cleanly (idempotent); `npm run gen:api` in frontend still compiles | M | verifier; affected owners notified (non-blocking) |
| 2a | `battlefield/preparations` | `gatekeeper.py` (prepare, cause, effective store, pending sweep), new `battlefield/app/api/preparations.py`, `main.py`, `battlefield/mock_agents/server.py` (mock prepare-aware green) | DB: allow/block/escalate per mode, same-key re-prepare (one Blue call, one escalation), conflict 409, block persisted with no execution, Blue down → `gate_unavailable`, restart sweep of `pending` | M | after 1 |
| 2b | `battlefield/consume-preparation` | `green_writes.py` (shared step-1 checks + fingerprint, consumption in txn) | DB: hit, mode change, day change, expiry, fingerprint drift (bank change), consumed retry, pending, GL replay precedence, concurrent identical executions → one payment, shadow drift audited not refused | M | after 2a |
| 3 | `battlefield/agentkit-strict-identity` | `agentkit/agentkit/{droid_agent,invocation,ledger_client,config}.py`, `docker-compose*.yml`, `agentkit/tests/*` | unit: unlinked refused (not run, one pair), explicit id refused live, ambiguous identical refused, hint conflict, exact tool-ID set, `prepare` refuses non-verified source, UUID4 still in DRY_RUN | M | after 1; parallel with 2a/2b (disjoint files) |
| 4 | `battlefield/agentkit-turn-loop` | `agentkit/agentkit/{droid_agent,server,events,tools,sync,__init__}.py`, tests | unit: service-loop heartbeat ≤ 50 ms while a tool sleeps 2 s; cancel from service loop ends turn and closes pairs; emitter drains from turn loop; `TurnLock` across loops; DRY_RUN turns via TurnLoop | L (split if > 600 lines: loop / redact+lock) | after 3 (same files) |
| 5 | `contracts/sdk-findings` | `contracts/CHANGELOG.md`, `agentkit/scripts/sdk_probe.py` | live, isolated, authorized | S | **D15 hold** |
| 6 | `green/preparation-handler` (M) | `green/agent.py`, `green/tools.py`, `green/workflow.py`, `green/tests/*` | keyless: handler table §2.8 per mode with mocked Ledger; cause in summaries; no blue call | M | after 2b, 3, 4 |
| 7 | `blue/shared-adapter` (M) | `blue/audit/{tools,agent}.py` | keyless: one pair per call, `ctx.invocation()` ids on receipts, `TurnLock` | M | after 4; parallel with 6 |
| 8 | joint acceptance (operator) | none | `make mock-agents` episode per mode now; live seeds ×2 off/shadow/enforce only when D15 lifts | — | D15 for the live half |
| 9 | `docs/integration-cleanup` | `AGENTS.md` §3.2 (delete green → blue exception, D1) / §3.7 (D7) / §5, README mirror mentions, delete spec + this doc | — | S | after 8 |

Parallelism: 1, then 2a ∥ 3, then 2b ∥ 4, then 6 ∥ 7. Nothing in parallel touches the same file.
`contracts/ext/**` is untouched, so the one-at-a-time schema rule only covers PR1.

## 6. Decisions (Ad, 2026-10-24)

| # | Decision | Status |
|---|---|---|
| D1 | Drop the Green → Blue hop (Option P). Green acts on battlefield's preparation; Blue `/gate` is battlefield-only; invariant 2's exception deleted in PR 9. Reverses M's mirror design | Accepted |
| D2 | No separate battlefield → Blue token (the token can't distinguish callers; threat is out of model) | Accepted |
| D3 | Preparation TTL fixed at 120 s from creation, a constant, never extended; refuse to start unless `ESCALATION_TIMEOUT_SEC + GATE_TIMEOUT_SEC + 15 ≤ 120` | Accepted |
| D4 | Binding/mode/day mismatch refused in every mode; expiry and fingerprint drift refused only in enforce (audited in shadow/off) | Accepted |
| D5 | Narrow per-action fingerprint (§2.4), not a full-context hash | Accepted |
| D6 | An enforced block marks the entity `blocked` at preparation, so a cancelled call still records and scores it | Accepted |
| D7 | Strict identity for green and blue live turns; red best-effort pending Al; reword invariant 7 | Accepted |
| D8 | Refuse both of two ambiguous identical approved calls (strict agents) | Accepted |
| D9 | No scoring change here; add `cause` to verdicts/events/receipts; infra-hold scoring is a separate PR | Accepted |
| D10 | Split the E2E branch into 0a/0b/0c | Moot — #52 merged unsplit |
| D11 | Blue live autonomy `off` with an always-`PROCEED_ONCE` handler (M agrees; impact levels unconfirmed until B-8) | Accepted |
| D12 | Defer accounting with a durable follow-up; no automatic green GL until a `POST /gl/journals` contract (proposed: accrual, Dr expense / Cr 2000 at approve, Dr 2000 / Cr 1000 at pay, one balanced journal unique on `(episode, ref_type, ref_id, kind)`, settlement needs a confirmed payment) | Accepted |
| D13 | Prepare returns 200 for a block, with a required `effective` field | Accepted |
| D14 | DRY_RUN turns also run on the per-turn TurnLoop | Accepted |
| D15 | Live SDK probe (B-8, PR 5, live half of PR 8) | **Partly lifted** (2026-10-24/25): red runs live on prod (Droid `gpt-5.4-mini`); blue's live audit is merged (#157) and runs on prod since 2026-10-25 (`DRY_RUN_BLUE=false`, `gpt-5.4-mini`); green's live probe (B-8) is still on hold |
