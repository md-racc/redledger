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

Every rule change: run two seeded episodes (`make episode MODE=enforce SEED=42`, then a
different seed), compare `/api/fe/episodes/<EP>/verdicts/rules`. A rule that fires mostly on
`origin=sim` rows is a false-positive machine; narrow it or lower its severity.

## Escalation

`escalate` opens a human decision on the frontend and blocks green for up to 90 s. Use it for
the ambiguous middle, not as a default. Timeout = block, so escalating legit traffic costs points.

## Optional integrations (only if cheap)

- **CRS**: identity/fraud check on new vendors and employees from the audit agent. One REST
  call per new entity; results feed a flag. Put it in `audit/crs.py`, behind `CRS_API_KEY`.
- **Cartesia**: voice callback on bank-account changes. Only if someone has slack.

## Extension points (grow without a contracts PR)

See README §16. For `blue/` specifically:
- Memory across turns: `ctx.ledger().get_state("k")` / `put_state("k", {...})`.
- Inputs: `req.options["inputs"]` is a list of messages left for you (judge, crowd, other agents). Read it in `build_prompt` / `dry_run_turn` if you want to react.
- Custom events: `ctx.emitter().custom("name", {...})` emits `x.blue.name`; the frontend stores it in `state.custom`.
- Your own tables: `contracts/ext/blue/<nn>_<name>.sql`, tables prefixed `blue_`.
- Your own battlefield routes: `battlefield/extensions/blue_<name>.py` with `router = APIRouter()`, mounted at `/api/x/blue/...`. Read-only on core tables; writes only to `blue_*` tables.
CI allows exactly those extra paths on a `blue/` branch. Nothing else outside `blue/`.

## Paste this to your coding agent as its first message

```
You are working in the Red Ledger repo, directory `blue/`, as Dev M's coding agent.
Before any edit: read `blue/AGENTS.md`, `GIT.md` §7, `README.md` §§0,1,3,5,6,7,16, and
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
