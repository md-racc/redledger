# Green integration status for Ad

## Current Option-P checkpoint (2026-10-24)

Contracts #80 supersede the mirror proposal: **Green never calls Blue**. Shared
strict identity and `LedgerClient.prepare` are merged (#84), as are nullable pending
deciders (#86), preparation creation (#87), and consumption (step 2b, #89,
`5d3dc03`). Green's handler/cause-accounting follow-up is now unblocked.

`preparation.py` stages the eight existing mutation mappings and the contract's
per-mode decisions against mocked Ledger HTTP. Preparation uses the SDK key
without consuming the first mutation's key. Its JSON cancellation comment carries
the cause; this is not yet wired to the production permission/cancellation path.
The static CANCEL and pre-SDK live guard remain. No new model tools or AP policy.

Next, integrate the handler and turn-local cause accounting;
then prove exact first-session restrictions, OFF callbacks, CANCEL comment delivery,
identity/header/event parity, bounded escalation holds, and no duplicate gating or
writes in isolated acceptance. Mocked HTTP is not real SDK or database evidence.
Phase C still needs Ad's three-day all-real-agent shadow run; Bright Data is not cleared.
Reflection #82 is a separate draft; this branch neither duplicates it nor enables
active-turn memory consumption.

## Historical baseline (superseded where it conflicts with the checkpoint above)

Baseline: merged main `899c133`. Ad released the DRY_RUN-only hold; Green #12,
#13 (`d71698c`) and #14 (`0c26a2b`) are merged. Live Green stays disabled before
SDK execution. No constant `mirror` key or local identity workaround.
Ad requested a small live follow-up after reviewed shared support merges.

- Shipped in `9736639`: first executable `restrict_tools` IDs use observed
  `<server>___<tool>` names, and async MCP functions run on private worker loops.
  These fixes do not provide verified permission-callback/execution invocation identity:
  `ledger_tool` still pops `_tool_use_id` for events only; `LedgerClient._write`
  still generates a fresh UUID when no ID is supplied.
- Ad must expose the true SDK `tool_use_id` consistently through permission callbacks,
  execution, tool events and ledger `X-Tool-Use-Id` headers. Never guess a last/global ID.
- Canonical battlefield preparation and Blue cache replay-only support are not in
  merged contracts/client. The mirror must reuse authoritative complete context and
  verdicts, never seed Blue's cache with incomplete context.
- Shared cancellation recording must produce a tool-call/result pair even when execution
  is canceled, with authoritative blocked status and escalation reuse. Preflight,
  replay-only and cancellation recording remain shared prerequisites, not Green patches.
- `_offload` binds `agentkit.ctx` in worker threads but does not copy turn ContextVars.
  Propagate Green's `clerk_scope` state safely with shared turn context across worker
  execution; never use global last-state guesses. This is an integration requirement,
  not an experimentally measured SDK finding.
- Shipped in `51ebf1a` (#20): emitter shutdown drains remaining batches within a
  bounded flush budget; tool offload has bounded execution. The old 50-event
  shutdown defect is resolved in shared code, not a remaining Green blocker.
  These changes do not add invocation-ID parity or propagate clerk ContextVars.

Ad owns the remaining shared identity work in `battlefield/agentkit-tool-identity`
and the preparation/replay-only contract proposal. A branch or proposal is not a
merged dependency. No live-release date or SDK evidence is claimed.

Manual acceptance after shared support merges: verify true invocation-ID parity across
permission/tool/events/header, first-session restrictions and clerk-state continuity;
exercise off/shadow/enforce, allow/block/escalate with no duplicate gate or write;
verify cancellation event pairs, authoritative blocked summaries, escalation reuse and
CANCEL comments reaching the model under `Autonomy.OFF`. Unit fakes are not SDK evidence.
