# Green integration status for Ad

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
