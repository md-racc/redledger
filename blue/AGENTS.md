# blue/ — working guide for Dev M and any coding agent in this directory

Read the root `README.md` (§§3, 5, 6, 9) and `GIT.md` first. You also own `green/`.

## Your job

Build the controller. Blue has two halves with different constraints:

1. **Gate** (`gate/`): synchronous, called by battlefield on every green mutation, 8-second
   budget. Deterministic rules first (`rules.py`), an optional direct-API LLM call for ambiguous
   cases (`llm.py`), decision policy in `engine.py`, idempotency cache in `cache.py`. No Droid
   here. The `reason` string is what judges read on the verdict card: write it like an auditor.
2. **Audit** (`audit/`): a Droid session that runs once per day after green. No latency budget.
   Reads the day's activity and the audit log, raises flags, freezes vendors, posts the
   end-of-day report. This is where visible agent reasoning lives.

Blue is scored on both sides: dollars blocked *and* false-positive cost. "Block everything" loses.
`/api/fe/episodes/<EP>/verdicts/confusion` is your scorecard.

## Boundaries

- You own `blue/`. Branch prefix `blue/`.
- Gate rules read only `req.context` (battlefield assembles it; shape in
  `contracts/agent-service.md`). If you need more context in the gate, that's a `contracts/`
  PR to Ad, not a ledger read inside `/gate`.
- Audit may read anything via `LedgerClient` (blue routes include `/audit_log`) and write
  flags, freezes, reports.
- No imports from other services. No DB.

## Files

| File | What goes there |
|---|---|
| `gate/rules.py` | pure rule functions + `RULES` list; one function per control |
| `gate/engine.py` | decision policy, reason text, cache; keep it explainable |
| `gate/llm.py` | direct LLM call with structured output; provider via env |
| `gate/cache.py` | leave alone |
| `audit/agent.py` | `AuditAgent(DroidAgent)` + its tools; DRY_RUN path |
| `prompts/audit.md` | auditor persona |
| `server.py` | `/gate`, `/gate/explain`, `/audit`; leave the shape alone |
| `tests/` | rules are pure: test them directly, no mocks needed |

## Day-one tasks (Friday)

1. `make mock-agents`, stop the mock blue, run yours in DRY_RUN. Run an `enforce` episode and
   watch `verdicts` and `verdicts/confusion` in the frontend API. Get a block on the mock red's
   ghost vendor and zero blocks on legit traffic.
2. Wire one LLM provider in `llm.py` (Gemini is the default; it's also an MLH prize) and confirm
   `/gate` stays under 3 s with it on.
3. Record any Droid findings for the audit session in `contracts/CHANGELOG.md`.

## Tuning loop

`AGENT_TOKEN` replaces `INTERNAL_TOKEN` (still accepted as a fallback); use your own `FACTORY_API_KEY` locally. A blue you run on the host needs the same `AGENT_TOKEN` battlefield has (compose default `change-me-agent`).

Every rule change: run two seeded episodes (`make episode MODE=enforce SEED=42`, then a
different seed), compare `/api/fe/episodes/<EP>/verdicts/rules`. A rule that fires mostly on
`origin=sim` rows is a false-positive machine; narrow it or lower its severity.

## Escalation

`escalate` opens a human decision on the frontend and blocks green for up to 90 s. Use it for
the ambiguous middle, not as a default. Timeout = block, so escalating legit traffic costs points.

## Optional integrations (only if cheap)

- **CRS**: employee identity checks in `audit/crs.py`, using sandbox username/password login.
  Only pinned fictional profiles are allowed. Missing credentials and DRY_RUN return unknown;
  no sponsor calls occur in the gate. `CRS_USERNAME` / `CRS_PASSWORD` require the companion
  `battlefield/crs-runtime` PR and human secret setup; `CRS_API_KEY` is unused by this API.
  See `CRS.md` for prerequisite PRs and remaining live-demo blockers.
- **Cartesia**: voice callback on bank-account changes. Only if someone has slack.

## Extension points (grow without a contracts PR)

See README.md (Ledger API overview, extensions). For `blue/` specifically:
- Memory across turns: `ctx.ledger().get_state("k")` / `put_state("k", {...})`.
- Inputs: `req.options["inputs"]` is a list of messages left for you (judge, crowd, other agents). Read it in `build_prompt` / `dry_run_turn` if you want to react.
- Custom events: `ctx.emitter().custom("name", {...})` emits `x.blue.name`; the frontend stores it in `state.custom`.
- Your own tables: `contracts/ext/blue/<nn>_<name>.sql`, tables prefixed `blue_`.
- Your own battlefield routes: `battlefield/extensions/blue_<name>.py` with `router = APIRouter()`, mounted at `/api/x/blue/...`. Read-only on core tables; writes only to `blue_*` tables.
CI allows exactly those extra paths on a `blue/` branch. Nothing else outside `blue/`.

## Evolution / lineages

In lineage episodes `/audit` gets `lineage` and `debrief` (resolved red attacks with `caught_by`;
empty = you missed it), and battlefield's `/gate` requests carry `playbook_version`.
- Learned rules go in your playbook as data, with rule ids `learned:<slug>` so the report credits them.
- Keep `/gate` read-free in the common case: cache learned rules by `playbook_version` and refresh
  them during `/audit` (or once per new version). Mock blue in `battlefield/mock_agents/server.py`
  shows the pattern.
- Your after-action review adds `false_positive` items and precision/recall per rule id; override
  `reflect(req)` / `dry_run_reflect(req)` to act on it. Contract: `contracts/agent-service.md` (Lineages); runbook: ARCHITECTURE.md (Evolution); design: root `ARCHITECTURE.md` (Evolution).
- Both reflection hooks now deterministically enable four fixed `learned:*` review controls
  from extracted/partial attacks in the supplied AAR. Any legitimate-item impact retires the
  corresponding learned control. Only note-only baseline rules (`vendor_age_lt_7d`,
  `near_threshold`, `no_po_from_po_vendor`, `recurring_drift`; `rules.RETIREABLE_RULE_IDS`) can be
  retired for a lineage, and only when a generation review shows sustained legit-only fire
  (`on_legit >= 3`, `on_red == 0`), recorded as `retired_baseline` playbook data. Block and hold
  rules are never retired or weakened. Retirement reads the exact requested playbook version
  only (never the stale fallback) and applies to invoice actions only (#133).
- Gate snapshots are scoped by episode and exact playbook version (128 retained snapshots).
  A cold version gets one read under a 0.5-second budget; cached/plain gates perform no
  playbook I/O. An unavailable version escalates neutrally and never weakens a baseline hold.
- Reflection performs no model calls or ledger writes. It preserves unrelated content and
  applies each generation once. Daily debriefs are forwarded but do not yet update playbooks
  within a turn. These keyless controls do not qualify live audit or the CRS gate.

## Paste this to your coding agent as its first message

```
You are working in the Red Ledger repo, directory `blue/`, as Dev M's coding agent.
Before any edit: read `blue/AGENTS.md`, `GIT.md` §7, `README.md`, `ARCHITECTURE.md`and
`contracts/agent-service.md`, `contracts/events.md`. Confirm `git branch --show-current` starts with `blue/`;
if not, create `blue/<topic>` from origin/main. Edit only inside `blue/`,
`battlefield/extensions/blue_*.py`, `contracts/ext/blue/`, and append to `DEVLOG.md`.
Never force-push, never merge, never touch another directory; if you need a contracts change,
write the proposed diff into the PR description and stop. Run `make lint test-blue` before
each push. Everything must work with DRY_RUN=true. Goal for this session: tune gate rules against two seeded episodes using /api/fe verdicts/rules and verdicts/confusion; zero legit blocks, all mock attacks caught.
```

## Don't

- Don't make `/gate` call Droid or do ledger reads. It's on the hot path.
- Don't return a reason that's just rule ids. Write the sentence.
- Don't disable a rule by deleting its test. Lower severity or narrow it.
