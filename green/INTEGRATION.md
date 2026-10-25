# Green integration status for Ad

## Current Option-P checkpoint (2026-10-24)

Contracts #80 supersede the mirror proposal: **Green never calls Blue**. Shared
strict identity and `LedgerClient.prepare` are merged (#84), as are nullable pending
deciders (#86), preparation creation (#87), and consumption (step 2b, #89,
`5d3dc03`). The handler follow-up uses this merged protocol.

`preparation.py` supplies the eight existing mutation mappings and the contract's
per-mode decisions against mocked Ledger HTTP. Preparation uses the SDK key
without consuming the first mutation's key. Its JSON cancellation comment carries
the cause. `on_permission` applies the decision with `PROCEED_ONCE`/`CANCEL`;
turn-local state suppresses held entities and separates unique cancellation causes.
The pre-SDK live guard is lifted in the guard-lift PR following the accepted Stage B SDK
acceptance evidence (issue #78); DRY_RUN remains the default and live still requires the
operator to set `DRY_RUN_GREEN=false`. No new model tools or AP policy.

Unknown/empty permission requests and multi-use batches fail closed without preparing;
the SDK's response applies to the whole batch, so callers must request tools individually.
Callback granularity remains part of Green acceptance, not an asserted SDK finding.

Finding #96 records the nine observed AP IDs from a list-only Session on canonical #94.
`AP_TOOL_IDS` pins them before the first Session; expected-ID lists are fresh copies.
This is discovery/configuration evidence, not restriction-enforcement or live acceptance.
See [SDK-ACCEPTANCE.md](SDK-ACCEPTANCE.md) for the unexecuted, explicitly budgeted proposal.

Next, prove exact first-session restriction enforcement, OFF callbacks, CANCEL comment delivery,
identity/header/event parity, bounded escalation holds, and no duplicate gating or
writes in isolated acceptance. Mocked HTTP is not real SDK or database evidence.
Phase C still needs Ad's three-day all-real-agent shadow run; Bright Data is not cleared.
This follow-up is stacked on preparation foundation #93. Keyless TurnLoop #92 and
merged reflection #82 remain separate concerns; preserve both, including reflection hooks
and explicit playbook API guidance. No active-turn memory consumption is added here.

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
