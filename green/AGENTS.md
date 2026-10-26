# green/ — maintenance guide (original author: M)

Read the root `README.md`, `docs/ARCHITECTURE.md` and `docs/CONTRIBUTING.md` first. See `blue/AGENTS.md` for the related controller.

## Your job

Build the finance-ops agent: a competent, trusting AP clerk that does the daily process through
the gated green routes. Green is the thing red exploits and blue protects. It must (a) actually
pay legitimate invoices so the false-positive penalty is real, and (b) actually pay fraudulent
ones when the controller is off so the baseline loses money. Don't make green suspicious; that's
blue's job.

`battlefield` remains the enforcement point. Live Green is intentionally disabled before
Droid Session/tool execution pending Green SDK acceptance,
including exact tool restrictions and verified invocation correlation. This is an unfinished
hackathon limitation, not a cleanup task. The merged contract
uses Battlefield preparations, not a Green → Blue mirror (#80, Option P). Shared strict identity
and `LedgerClient.prepare` landed in #84; preparation creation/consumption landed in #87/#89.
The permission handler uses `preparation.py` for canonical decisions, but the pre-SDK
`_droid_turn` hard guard still prevents live execution.
[docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) (Green, Readiness evidence) records current prerequisites
and identity evidence limits.

## Files

| File | What goes there |
|---|---|
| `tools.py` | model-facing tools; wrappers over LedgerClient; the descriptions are prompt material |
| `agent.py` | `GreenAgent(DroidAgent)`: prompt, guarded permission handler, DRY_RUN clerk |
| `preparation.py` | Option-P mapping and decision helpers; no SDK/session or execution writes |
| `workflow.py` | shared turn-local procedure, eligibility, reconciliation and confirmed summary |
| `prompts/system.md` | persona; a string replacing Droid's default |
| `server.py` | service entry point |
| `tests/` | `respx` tests against a fake Ledger API |

## Current AP milestone

- Stable day/ID order: pending vendor changes; invoice matching or genuine no-PO approval;
  matched/approved invoice payments including backlog; pending expense approval; approved
  expense payments including backlog. Referenced missing/unusable POs are deferred, never
  converted to no-PO approvals. Do not investigate vendor age, duplicate invoices or bank history.
- Decimal invoice limit is inclusive `<= APPROVAL_THRESHOLD` (existing default 5000).
  Above-limit invoices are deferred, not fraud/escalations. No expense threshold.
- Operations re-read current entities and existing payments before dependent writes. Turn-local
  context suppresses blocked/failed/deferred/uncertain entities across tools, including rejects.
  Ambiguous writes reconcile via current invoice/vendor-change/expense state or payments and
  are never resent in the same turn, even if confirmed. Restart recovery uses ledger reads,
  not a promise of backend exactly-once payments.
- Summaries count only confirmed actions/payment dollars, with unique blocks, deferrals,
  failures and unknowns separate. HTTP/auth/contract failures are not controller blocks.
  Non-HTTP tool failures use a small `LedgerError` subclass with `status=null`, explicitly
  not an HTTP response, so the shared decorator emits `ok=false`. HTTP errors retain their
  actual status; error bodies and bank/account details are not narrated.
- There is no automatic GL tool in this milestone. Do not claim balanced accounting.
  Posting GL requires a separate accounting milestone; this staged foundation deliberately
  does not yet implement balanced GL or SDK-qualified live execution.
- Shared #33/#34 carry invocation IDs into tool events and the first ledger write, with
  `:<n>` keys for subsequent writes, canceled-call pairs and copied clerk ContextVars.
  #84 refuses missing, ambiguous or conflicting identities in strict live turns; local UUIDs
  remain valid for DRY_RUN, not live Green. Adapter fixtures are not live SDK evidence.
  Verified Green SDK behavior remains a release prerequisite; unit adapters do not qualify it.

## Permission preparations, not live enablement

`preparation.py` maps the eight existing AP mutation tools to the exact route body; `ap_queue`
is read-only and GL is not registered. Its decisions follow `contracts/agent-service.md` (Green):
validation/key/turn conflicts cancel in every mode; availability or malformed-response failures
fall back to inline gating only in off/shadow; enforce fails closed. Block decisions carry
`control_hold` or `escalation_timeout`; failures carry `invalid_state` or `integration_failure`.
Helpers never retry, consume a write key, execute a mutation, or invent an identity.
`on_permission` uses the shared registry, turn-owned LedgerClient, and turn-local clerk state.
Only `PROCEED_ONCE` can authorize execution. Cancel comments carry JSON cause/source data;
the shared registry includes that comment in the single canceled-call result pair.
Held entities remain suppressed across later tools; cause counts are unique per entity and
are appended only when present, leaving ordinary keyless summaries unchanged.
Unknown/empty requests and batches of multiple tool uses fail closed before preparing.
Batch callers must issue individual tool requests; Green SDK acceptance must verify callback
granularity as well as OFF prompting, restrictions, identity and cancellation delivery.
Do not remove the pre-SDK guard without separate Green SDK acceptance.

## Local loop

Use the same `AGENT_TOKEN` as your local battlefield (compose default `change-me-agent`).
Keep local development keyless with `DRY_RUN=true`.

```
make mock-agents                       # battlefield + stub red/blue
docker compose stop green
cd green && uv sync --extra dev
AGENT_NAME=green BATTLEFIELD_URL=http://localhost:8000 AGENT_TOKEN=change-me-agent DRY_RUN=true \
  uv run uvicorn server:app --port 8002 --reload
make episode MODE=enforce
```

## Droid specifics

- `autonomy = "off"`. Permission handler is `on_permission` in `agent.py`; live stays guarded.
- Never return `PROCEED_ALWAYS*` / `PROCEED_AUTO_RUN*`. They disable the gate.
- Pin a cheap model. Green does procedural work.
- Keep the prompt short; green runs every day of every episode and burns the most credits.

## Evolution / lineages

In lineage episodes your `/turn` gets `options.lineage` and `options.debrief`: `fraud` items of
**resolved** red attacks you actually acted on (invoices, expenses, vendor changes; outcome
paid/approved/blocked/rejected). Legit items you had blocked arrive only in the after-action review.
- Playbook: `ledger.get_playbook()` / `ledger.put_playbook(...)` inside your turn (procedures as data).
  These shared APIs are not current Green model tools. Writes require an active turn;
  reflection returns content for Battlefield to persist, never calls `put_playbook`.
- `reflect(req)` and `dry_run_reflect(req)` share deterministic, keyless AAR reflection in
  `playbook.py`; Battlefield persists the returned content. Reflection performs no ledger I/O.
- The reserved `green_reflection` object stores schema version 1, latest-review counts of unique
  entities (fraud paid/approved/blocked/rejected versus legitimate blocked), and up to three fixed
  procedural reminders retained across reviews. Duplicate disclosures count once; conflicting
  outcomes for one entity are ignored. Counts are snapshots, not cumulative totals.
- Only valid Green `fraud` / AAR-only `legit_blocked` items are used (at most 2000; IDs up to 128
  characters). No raw items, identifiers, amounts, field values, source prose, scores, history or
  other agents' internals are learned. Unrelated operator content, including unknown namespace
  fields, is preserved; incompatible namespace versions and oversized content are kept unchanged.
- `build_prompt` consumes it on lineage turns only: a bounded (≤1 KB), deterministic section of
  stored `procedure_reminders` (fixed PROCEDURES entries, stored order, no rationale or operator
  prose), degrading to the static prompt on any read failure. The keyless clerk never sees it
  (`dry_run_turn` does not call `build_prompt`), and daily debriefs remain unconsumed. No
  playbook tools/writes were added — that still needs fresh tool-ID acceptance. Live Green
  retains the pre-SDK guard. Contract: `contracts/agent-service.md` (Lineages).

## Don't

- Don't give green investigative tools (audit log, flags beyond what it already sees). Trusting clerk.
- Don't retry blocked actions in the prompt or the code.
- Don't put rules in green that belong in blue.

## Maintenance validation

Follow root `AGENTS.md` and `docs/CONTRIBUTING.md`; historical team prefixes are no longer path restrictions.
Run root `make lint test-green` for changes here; keep `DRY_RUN=true` keyless.
Use `agentkit.LedgerClient` for agent ledger access and preserve the root information boundaries.
