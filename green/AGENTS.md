# green/ — working guide for Dev M and any coding agent in this directory

Read the root `README.md` (§§3, 5, 6) and `GIT.md` first. You also own `blue/`; see `blue/AGENTS.md`.

## Your job

Build the finance-ops agent: a competent, trusting AP clerk that does the daily process through
the gated green routes. Green is the thing red exploits and blue protects. It must (a) actually
pay legitimate invoices so the false-positive penalty is real, and (b) actually pay fraudulent
ones when the controller is off so the baseline loses money. Don't make green suspicious; that's
blue's job.

`battlefield` remains the enforcement point. Live Green is intentionally disabled before
Droid Session/tool execution pending Green SDK acceptance,
including exact tool restrictions and verified invocation correlation. The merged contract
uses Battlefield preparations, not a Green → Blue mirror (#80, Option P). Shared strict identity
and `LedgerClient.prepare` landed in #84; preparation creation/consumption landed in #87/#89.
The permission handler uses `preparation.py` for canonical decisions, but the pre-SDK
`_droid_turn` hard guard still prevents live execution.
[INTEGRATION.md](INTEGRATION.md) separates current prerequisites
from the superseded handoff; [IDENTITY.md](IDENTITY.md) records identity evidence limits.

## Boundaries

- You own `green/`. Branch prefix `green/`.
- Talk to the world only through `agentkit.LedgerClient` (green routes). No DB, no imports from
  other services. Need another route or field? `contracts/` PR to Ad.
- Green never calls Blue. Prepare only through `LedgerClient.prepare` against Battlefield;
  the later gated write uses the same verified SDK `tool_use_id`.

## Files

| File | What goes there |
|---|---|
| `tools.py` | model-facing tools; wrappers over LedgerClient; the descriptions are prompt material |
| `agent.py` | `GreenAgent(DroidAgent)`: prompt, guarded permission handler, DRY_RUN clerk |
| `preparation.py` | Option-P mapping and decision helpers; no SDK/session or execution writes |
| `workflow.py` | shared turn-local procedure, eligibility, reconciliation and confirmed summary |
| `prompts/system.md` | persona; a string replacing Droid's default |
| `server.py` | leave alone |
| `tests/` | `respx` tests against a fake Ledger API |

## Day-one tasks (Friday)

1. Hand shared identity/preflight/restriction gaps to Ad. Do not implement a Green-local
   invocation identity workaround or depend on an unmerged contract.
2. Once shared integration is merged, experimentally verify `Autonomy.OFF` permission requests,
   exact tool IDs/restrictions from the first session and `CANCEL` comments reaching the model.
   Keep autonomy off until evidence exists; unit fakes are not SDK findings.
3. DRY_RUN is keyless and uses the same decorated tools as the eventual live surface. It emits
   only `agent.thinking`, `agent.tool_call`, `agent.tool_result`, not gate/mutation events.
   Its `/health` reports `droid_ok=false` without inspecting SDK availability; the SDK is not
   required or imported for this path. Live health still uses the shared diagnostic.

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

## Realism work (shared with Ad)

`battlefield/orchestrator/legit_traffic.py` and `battlefield/seed/company.py` generate the
company. You don't edit them directly (they're Ad's directory), but you own their *tuning*:
open `battlefield/` PRs with Ad as reviewer, or hand Ad the numbers. The goal is traffic that
makes green's job non-trivial and blue's false-positive risk real: recurring monthly vendors,
PO amounts that drift a few percent, legit no-PO vendors, occasional legit bank-detail changes.

## Local loop

`AGENT_TOKEN` replaces `INTERNAL_TOKEN` (still accepted as a fallback); use your own `FACTORY_API_KEY` locally. Pass `AGENT_TOKEN=<your .env value>` (compose default `change-me-agent`) where the command below says `INTERNAL_TOKEN=change-me`, or battlefield and your service 401 each other.

```
make mock-agents                       # battlefield + stub red/blue
docker compose stop green
cd green && uv sync --extra dev
AGENT_NAME=green BATTLEFIELD_URL=http://localhost:8000 INTERNAL_TOKEN=change-me DRY_RUN=true \
  uv run uvicorn server:app --port 8002 --reload
make episode MODE=enforce
```

## Droid specifics

- `autonomy = "off"`. Permission handler is `on_permission` in `agent.py`; live stays guarded.
- Never return `PROCEED_ALWAYS*` / `PROCEED_AUTO_RUN*`. They disable the gate.
- Pin a cheap model. Green does procedural work.
- Keep the prompt short; green runs every day of every episode and burns the most credits.

## Extension points (grow without a contracts PR)

See README.md (Ledger API overview, extensions). For `green/` specifically:
- Memory across turns: `ctx.ledger().get_state("k")` / `put_state("k", {...})`.
- Inputs: `req.options["inputs"]` is a list of messages left for you (judge, crowd, other agents). Read it in `build_prompt` / `dry_run_turn` if you want to react.
- Custom events: `ctx.emitter().custom("name", {...})` emits `x.green.name`; the frontend stores it in `state.custom`.
- Your own tables: `contracts/ext/green/<nn>_<name>.sql`, tables prefixed `green_`.
- Your own battlefield routes: `battlefield/extensions/green_<name>.py` with `router = APIRouter()`, mounted at `/api/x/green/...`. Read-only on core tables; writes only to `green_*` tables.
CI allows exactly those extra paths on a `green/` branch. Nothing else outside `green/`.

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

## Paste this to your coding agent as its first message

```
You are working in the Red Ledger repo, directory `green/`, as Dev M's coding agent.
Before any edit: read `green/AGENTS.md`, `GIT.md` §7, `README.md`, `ARCHITECTURE.md`and
`contracts/agent-service.md`, `contracts/events.md`. Confirm `git branch --show-current` starts with `green/`;
if not, create `green/<topic>` from origin/main. Edit only inside `green/`,
`battlefield/extensions/green_*.py`, `contracts/ext/green/`, and one new `devlog/` fragment per PR.
`DEVLOG.md` is frozen; the orchestrator owns the fragment when delegating.
Never force-push, never merge, never touch another directory; if you need a contracts change,
write the proposed diff into the PR description and stop. Run `make lint test-green` before
each push. Everything must work with DRY_RUN=true. Current scope: trusting AP clerk foundation;
live preparation execution waits for Green SDK acceptance. Never call Blue.
```

## Don't

- Don't give green investigative tools (audit log, flags beyond what it already sees). Trusting clerk.
- Don't retry blocked actions in the prompt or the code.
- Don't put rules in green that belong in blue.
