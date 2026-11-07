# blue/ — maintenance guide (original author: M)

Read the root `README.md`, `docs/ARCHITECTURE.md` and `docs/CONTRIBUTING.md` first. See `green/AGENTS.md` for the related clerk.

## Your job

Build the controller. Blue has two halves with different constraints:

1. **Gate** (`gate/`): synchronous, called by battlefield on every green mutation, 8-second
   budget. Deterministic rules first (`rules.py`), optional log-only LLM advisory
   (`llm.py`, never changes the verdict), decision policy in `engine.py`, idempotency cache in `cache.py`. No Droid
   here. The `reason` string is what users read on the verdict card: write it like an auditor.
2. **Audit** (`audit/`): a Droid session that runs once per day after green. Bounded by the configured turn timeout.
   Reads the day's activity and the audit log, raises flags, freezes vendors, posts the
   end-of-day report. This is where visible agent reasoning lives.

Blue is scored on both sides: dollars blocked *and* false-positive cost. "Block everything" loses.
`/api/fe/episodes/<EP>/verdicts/confusion` is your scorecard.

## Files

| File | What goes there |
|---|---|
| `gate/rules.py` | pure rule functions + `RULES` list; one function per control |
| `gate/engine.py` | decision policy, reason text, cache; keep it explainable |
| `gate/llm.py` | direct LLM call with structured output; provider via env |
| `gate/cache.py` | bounded idempotency cache |
| `audit/agent.py` | `AuditAgent(DroidAgent)` + its tools; DRY_RUN path |
| `prompts/audit.md` | auditor persona |
| `server.py` | `/gate`, `/gate/explain`, `/audit`; leave the shape alone |
| `tests/` | rules are pure: test them directly, no mocks needed |

## Tuning loop

Use the same `AGENT_TOKEN` as your local battlefield (compose default `change-me-agent`).
Keep local development keyless with `DRY_RUN=true`.

Every rule change: run two seeded episodes (`make episode MODE=enforce SEED=42`, then a
different seed), compare `/api/fe/episodes/<EP>/verdicts/rules`. A rule that fires mostly on
`origin=sim` rows is a false-positive machine; narrow it or lower its severity.

## Escalation

`escalate` opens a human decision on the frontend and blocks green for up to 90 s. Use it for
the ambiguous middle, not as a default. Timeout = block, so escalating legit traffic costs points.

## Evolution / lineages

In lineage episodes `/audit` gets `lineage` and `debrief` (resolved red attacks with `caught_by`;
empty = you missed it), and battlefield's `/gate` requests carry `playbook_version`.
- Learned rules go in your playbook as data, with rule ids `learned:<slug>` so the report credits them.
- Keep `/gate` read-free in the common case: cache learned rules by `playbook_version` and refresh
  them during `/audit` (or once per new version). Mock blue in `battlefield/mock_agents/server.py`
  shows the pattern.
- Your after-action review adds `false_positive` items and precision/recall per rule id; override
  `reflect(req)` / `dry_run_reflect(req)` to act on it. Contract: `contracts/agent-service.md` (Lineages); runbook and design: `docs/ARCHITECTURE.md` (Evolution).
- Both reflection hooks now deterministically enable four fixed `learned:*` review controls
  from extracted/partial attacks in the supplied AAR. Any legitimate-item impact retires the
  corresponding learned control. Only note-only baseline rules (`vendor_age_lt_7d`,
  `near_threshold`, `no_po_from_po_vendor`, `recurring_drift`; `rules.RETIREABLE_RULE_IDS`) can be
  retired for a lineage, and only when a generation review shows sustained legit-only fire
  (`on_legit >= 3`, `on_red == 0`), recorded as `retired_baseline` playbook data. Block and hold
  rules are never retired or weakened. Retirement reads the exact requested playbook version
  only (never the stale fallback) and applies to invoice actions only (#133).
- Gate snapshots are scoped by episode and exact playbook version (128 retained snapshots).
  A cold version gets one bounded playbook read; cached/plain gates perform no
  playbook I/O. An unavailable version escalates neutrally and never weakens a baseline hold.
- Reflection performs no model calls or ledger writes. It preserves unrelated content and
  applies each generation once. Daily debriefs are forwarded but do not yet update playbooks
  within a turn. These keyless controls do not qualify live audit or the CRS gate.

## Don't

- Never call Droid in `/gate`. Evaluate supplied context; only the bounded, versioned
  playbook refresh described above may read the ledger on a cold lineage gate.
- Don't return a reason that's just rule ids. Write the sentence.
- Don't disable a rule by deleting its test. Lower severity or narrow it.

## Maintenance validation

Follow root `AGENTS.md` and `docs/CONTRIBUTING.md`; historical team prefixes are no longer path restrictions.
Run root `make lint test-blue` for changes here; keep `DRY_RUN=true` keyless.
Use `agentkit.LedgerClient` for agent ledger access and preserve the root information boundaries.
