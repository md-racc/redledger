# Green identity adapter checkpoint

Current update (2026-10-24): #84 adds strict live identity (the shared default at
Green's `autonomy="off"`), refusing unverified/ambiguous/conflicting invocations
and writes without verified SDK identity. `LedgerClient.prepare` requires an
SDK-reported `ToolUse`; its request does not consume an invocation write key.
UUID4 fallback described below is historical best-effort behavior, not permission
to execute live Green. Contracts #80 drop the Blue mirror entirely; Green prepares
only against Battlefield. See [INTEGRATION.md](INTEGRATION.md) for current blockers.
The guard/static CANCEL still stand, and fixture correlation is not SDK acceptance.

## Historical #34 evidence (preparation/replay proposal superseded by Option P)

Shared baseline: merged main `78a3b25`, after contracts #33 and implementation #34.
This updates the earlier identity status in `INTEGRATION.md` and `HANDOFF.md`;
it does not replace their proposed preflight/replay semantics.

## Landed shared support

- `DroidAgent.tool_uses(request)` exposes registered permission metadata.
- The first ledger write and tool-call/result events use the invocation ID.
  Subsequent writes use `<tool_use_id>:<n>` under the merged #33 contract.
- The shared permission entry records one failed event pair for a canceled call;
  worker offload copies ContextVars, including Green's turn-local clerk state.
- Battlefield rejects a key reused for a different action/entity/amount.

Green uses the shared adapter, not a local identity map or a different mirror key.
Each current AP mutation tool performs at most one ledger mutation.

## Evidence boundary

Adapter tests use permission-shaped fixtures, real decorated Green tools, shared
worker offload and mocked Ledger HTTP. Registering an approved fixture does not
mean Green's production permission handler approved it: that handler still cancels.
These tests are not SDK experiments or evidence that a CANCEL comment reaches a model.

The shared adapter correlates exact tool names and canonical arguments against
approved registrations when MCP metadata supplies no invocation ID. It can fall
back to a local UUID for an unlinked execution. Neither behavior is evidence of
direct SDK-to-handler identity delivery. Live Green must not silently treat a
fallback UUID as a verified SDK ID; missing, ambiguous or conflicting correlation
must fail safely under the reviewed integration protocol.

## Still required before live release

Canonical Battlefield preparation and Blue replay-only behavior are not supplied
by #33/#34. Green must mirror the returned authoritative envelope, not reconstruct
incomplete evidence or seed an empty cache. Freshness, argument/state/mode binding,
canceled-block accounting and escalation reuse still need the reviewed contract.
No endpoint, response shape or Green-local workaround is invented here.

Keep the live guard and autonomy off. Authorized SDK acceptance must verify exact
first-session restrictions, invocation correlation and cancellation behavior.
Balanced atomic, deduplicated GL remains a separate accounting milestone.
