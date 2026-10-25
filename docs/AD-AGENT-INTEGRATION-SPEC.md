# Temporary Green + Blue integration handoff to Dev Ad

**Status: superseded.** Ad answered this handoff in [`AD-INTEGRATION-DESIGN.md`](AD-INTEGRATION-DESIGN.md) (D1–D14
accepted 2026-10-24; D15 partly lifted: red and blue's audit live on prod, green keyless). That doc's "Progress" table is
the current state; the checklists below are kept as the original ask and are not updated. Not an approved contract.
Baseline: merged main `8a2157d`. Shared implementation owner: **Ad**.
Green and Blue integration owners: **M**, through their respective agents.

- [x] Blue requirements consolidated from merged code and its verified readiness checkpoint.
- [x] Green requirements collected from merged handoffs and confirmed by its user-relayed contribution.
- [x] Original Green agent approved this document as-is; approval was relayed by the user.
- [ ] Ad has accepted the protocol decisions and implementation order below.

Use this one document for the joint handoff. The Blue orchestrator is the sole writer;
Green reviews and returns corrections rather than editing concurrently.
After acceptance, Ad owns the implementation checklist and evidence references.
Green supplied its requirements and approval as-is through the user. This document review
does not approve an unmerged API or establish live-release acceptance.

## Completion and deletion instruction for Ad

**Ad: delete `docs/AD-AGENT-INTEGRATION-SPEC.md` only after the agreed implementation is
merged and acceptance is complete, with lasting contracts and evidence recorded elsewhere.
Do not delete it merely because this draft was accepted.** Before deleting it:

1. Confirm the agreed implementation PRs are merged and complete the acceptance checklist,
   with Green and Blue evidence and independent verification. Any explicitly deferred
   accounting work must have an accepted durable follow-up.
2. Move lasting API decisions into `contracts/` and SDK findings into
   `contracts/CHANGELOG.md`; keep operational instructions in the owning service's documentation.
3. Link the implementation PRs, tests and accepted follow-ups from the cleanup PR or a new
   devlog fragment. Then remove this temporary spec in the final cleanup commit/PR.

Do not delete existing devlog history, other handoff documents, worktrees or branches as part
of this instruction. Until completion, keep this file and update unresolved items honestly.

## Already landed, preserve rather than reimplement

| Work | Merged evidence | What it does not prove |
|---|---|---|
| Bounded event draining and tool offload | #20 | Nonblocking service-loop execution |
| Invocation registry, canceled-call pairs, copied ContextVars | #33/#34, Green #36 | Genuine SDK execution correlation or cross-loop object safety |
| Keyless Green service/recovery and identity adapter coverage | #35/#36 | Canonical preflight, safe live permission mirroring or live SDK acceptance |
| Blue offline readiness and truthful health | #37 | Live audit readiness; its guard remains unconditional |
| Blue pending/retained key action binding | #38 | A replay-only path; ordinary `/gate` still evaluates on cache miss |
| Race-safe Green state transitions/payment protection and GL replay handling | #39 | Atomic balanced multi-line accounting or a canonical preparation protocol |

Old claims that ContextVars never propagate or shared IDs only reach events are superseded.
The current offline Blue probe sees copied Blue state and a bound **local/unverified**
shared invocation, on a different event loop, while the service-loop heartbeat is blocked.
Copying a diagnostic marker is not authentication.

## Work package A: canonical preflight (preparation) and replay protocol (Ad first)

Ad must choose and merge the contract before either agent depends on a new interface.
**No endpoint name, request field, token format or response schema is invented here.**

- Battlefield prepares an action from verified invocation identity and normalized arguments,
  assembles the complete provenance-stripped gate context, and binds the invocation and
  arguments to episode, day, mode, action/entity/amount or GL posted fields, relevant ledger
  state and expiry.
- Preparation may persist decisions, audit receipts and escalation state, but must not perform
  the requested approval, rejection, payment or journal posting.
- Return a canonical envelope and effective result that Green forwards unchanged. Green must
  never reconstruct partial evidence or seed Blue's authoritative cache with an incomplete mirror.
- Specify replay-only behavior for Blue: a missing, expired, conflicting or invalid replay must
  fail explicitly, never trigger a new evaluation or prime the cache. Existing action binding
  is necessary but insufficient; preserve complete same-action verdict replay for 120 seconds.
- Specify freshness, authoritative-envelope validation, restart/cache-loss behavior and the
  relationship between the 120-second cache and up to 90 seconds of escalation waiting.
  A late human answer must not silently extend authority beyond the reviewed validity rule.
- Battlefield owns escalation and persists its effective result. Preparation and execution
  must reuse that result rather than open duplicate human requests.
- Persist enforced blocks even when SDK cancellation prevents execution. Distinguish a fraud
  control hold from an integration/auth/transport failure in events, receipts and summaries.
- Execution consumes only a matching, still-valid preparation and retains Battlefield's own
  validation/enforcement and #39 concurrency protections. State/mode/argument changes, expiry or
  conflicting identities reject execution without an automatic mutation retry.
- Provide the contract-backed `LedgerClient` methods and configuration wiring needed by both
  agents. Review the existing approval-threshold wiring rather than introducing a second default.

## Work package B: safe shared SDK execution (Ad)

- Preserve the genuine SDK identity across permission handling, execution, tool events, ledger
  headers and receipts. First write uses that ID; later writes use `<id>:<n>`, per #33.
- Live SDK mutations must reject missing, ambiguous, conflicting or unverified identity.
  Local UUIDs, explicit test IDs, model arguments, last-ID globals and bare-name suffixes are
  not substitutes. Prove correlation under concurrent identical arguments and cancellations;
  permission-shaped test fixtures alone are not live SDK evidence.
- Emit exactly one tool-call/result pair for executed, canceled, refused, interrupted and
  timed-out invocations. Reconcile shared narration with Blue's private decorator before live use.
- Make the shared bridge nonblocking for the service loop while preserving bounded tool/turn
  deadlines, cancellation, event draining and truthful unknown-outcome handling. Do not add a
  service-local lifecycle/offload fork to bypass this dependency.
- Establish safe ownership of asyncio locks, clients, snapshots and mutable receipt/clerk state.
  Copied ContextVars may hold the same objects across loops; copying alone is not a safety proof.
- Verify exact Green and Blue session tool IDs and first-session restrictions. Keep Green's
  autonomy off; do not silently relax permission handling to make an SDK test pass.
- With separately authorized credentials and an isolated session, measure permission callbacks,
  actual invocation correlation, cancellation behavior/comment delivery and timeout cleanup.
  Record sanitized SDK/version findings through Ad's contracts path. This document does not
  authorize model spending, deployment or a second local stack.

## Work package C: owner integrations after A/B merge (M, not an Ad-only task)

**Green:** replace the prerequisite-only permission cancel with the reviewed preparation/replay
flow, forward the canonical envelope, keep exact identity and clerk-state continuity, and
preserve the trusting AP workflow and confirmed-only recovery summaries.

**Blue:** implement the agreed replay-only gate behavior and verified shared invocation adapter,
single-owner narration and safe receipt/lock handling. Preserve audit replay, partial/unknown
receipts, cross-day suppression and the rule that weak evidence alone cannot freeze a vendor.

Neither owner enables live execution until its acceptance evidence exists. Keyless DRY_RUN
continues to use normal public LedgerClient routes; no agent reads events, scoring or hidden
provenance. Gate rules remain supplied-context-only, with no ledger or Droid I/O.

## Accounting decision, separate from the live AP/audit release

Green's balanced-GL milestone remains separate. Ad must agree recognition versus payment
settlement, account conventions and an atomic, deduplicated posting contract tied to confirmed
payment references before Green implements automatic GL.
Two independent line writes are not an atomic journal, and an already-paid invoice must not be
repaid to repair accounting. #39's GL replay protection does not settle these accounting choices.
Either implement this milestone under an accepted contract or record an explicitly accepted
durable follow-up; it need not block unrelated Blue audit acceptance.

## Acceptance checklist and implementation order

Order: **Ad contract decisions → shared implementation → owner integrations → coordinated
acceptance → durable documentation → delete this temporary spec.**

- [ ] Ad records protocol/freshness/accounting decisions and contracts merge before consumers.
- [ ] Green and Blue complete review of this document and their eventual owner integrations.
- [ ] Tests prove complete canonical context, replay hit/miss/expiry/conflict, state/mode changes,
      concurrent identical calls, canceled blocks, and one reused escalation outcome.
- [ ] Off skips Blue; shadow observes but does not enforce fraud verdicts or mirror failures;
      enforce follows Battlefield's effective decision and fails safely on invalid preparation.
      Authentication/identity and ordinary ledger validation remain mandatory in every mode.
- [ ] Permission → events → exact ledger write/receipt IDs match, including canceled and
      timed-out calls, with one event pair and no blind retry after an unknown write.
- [ ] Tests prove owner-loop safety and `/gate` responsiveness during concurrent live audit;
      the eight-second gate budget and mode-independent verdict policy remain intact.
- [ ] Both services pass no-key DRY_RUN tests, lint and actual SDK acceptance, with versions and
      pinned review SHAs recorded. Fakes/offline registration are not labeled live validation.
- [ ] Under separately authorized operator coordination, run one shared stack with matching
      off/shadow/enforce seeds, then a second seed; verify ledger outcomes, no duplicate payments,
      cancellation accounting, legitimate completion and Blue receipt truthfulness.
- [ ] Core changes receive Ad's required independent verifier and pinned steward assessment;
      affected owners are tagged. PRs stay under 600 changed lines and authors never merge.
- [ ] Durable contracts/service docs and accepted follow-up references replace this temporary
      plan; Ad deletes this spec only after agreed implementation merges and acceptance completes.

## Source handoffs

- [Green identity checkpoint](../green/IDENTITY.md): current shared-adapter status and remaining
  preflight/SDK acceptance; supersedes older identity claims in the following documents.
- [Green protocol proposal](../green/HANDOFF.md) and [integration notes](../green/INTEGRATION.md):
  proposed preparation/replay semantics and the separate accounting milestone.
- [Blue SDK evidence and prerequisites](../blue/SDK-READINESS.md).
- [Blue gate action binding](../blue/GATE-IDEMPOTENCY.md).
- [Existing service contract](../contracts/agent-service.md),
  [Ledger API contract](../contracts/ledger-api.yaml) and [events contract](../contracts/events.md).
