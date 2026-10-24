# green/ — working guide for Dev M and any coding agent in this directory

Read the root `README.md` (§§3, 5, 6) and `GIT.md` first. You also own `blue/`; see `blue/AGENTS.md`.

## Your job

Build the finance-ops agent: a competent, trusting AP clerk that does the daily process through
the gated green routes. Green is the thing red exploits and blue protects. It must (a) actually
pay legitimate invoices so the false-positive penalty is real, and (b) actually pay fraudulent
ones when the controller is off so the baseline loses money. Don't make green suspicious; that's
blue's job.

Green is also the Factory-native showpiece: its Droid permission handler mirrors blue's gate.
That mirror is for the demo; `battlefield` remains the enforcement point.

## Boundaries

- You own `green/`. Branch prefix `green/`.
- Talk to the world only through `agentkit.LedgerClient` (green routes). No DB, no imports from
  other services. Need another route or field? `contracts/` PR to Ad.
- The only cross-service call you may make is `POST $BLUE_URL/gate` from the permission handler,
  with the same idempotency key battlefield uses (the Droid `tool_use_id`).

## Files

| File | What goes there |
|---|---|
| `tools.py` | model-facing tools; wrappers over LedgerClient; the descriptions are prompt material |
| `agent.py` | `GreenAgent(DroidAgent)`: prompt, permission handler mirror, DRY_RUN clerk |
| `prompts/system.md` | persona; a string replacing Droid's default |
| `server.py` | leave alone |
| `tests/` | `respx` tests against a fake Ledger API |

## Day-one tasks (Friday)

1. Verify in a 10-line script that `Autonomy.OFF` raises a permission request for MCP tool
   calls. Record the answer in `contracts/CHANGELOG.md` Findings. If it doesn't, drop autonomy
   to LOW and record that too; the ledger-side gate still enforces.
2. Verify whether `comment=` on `CANCEL` reaches the model. If not, the tool's `{"blocked": true,
   "reason": ...}` output is what the model sees, which is fine.
3. Run `GreenAgent` in DRY_RUN against `make mock-agents` and confirm payments land and blocked
   invoices show `status=blocked` in `/api/fe/episodes/<EP>/verdicts`.

## Realism work (shared with Ad)

`battlefield/orchestrator/legit_traffic.py` and `battlefield/seed/company.py` generate the
company. You don't edit them directly (they're Ad's directory), but you own their *tuning*:
open `battlefield/` PRs with Ad as reviewer, or hand Ad the numbers. The goal is traffic that
makes green's job non-trivial and blue's false-positive risk real: recurring monthly vendors,
PO amounts that drift a few percent, legit no-PO vendors, occasional legit bank-detail changes.

## Local loop

```
make mock-agents                       # battlefield + stub red/blue
docker compose stop green
cd green && uv sync --extra dev
AGENT_NAME=green BATTLEFIELD_URL=http://localhost:8000 BLUE_URL=http://localhost:8003 INTERNAL_TOKEN=change-me DRY_RUN=true \
  uv run uvicorn server:app --port 8002 --reload
make episode MODE=enforce
```

## Droid specifics

- `autonomy = "off"` (see day-one task 1). Permission handler is `on_permission` in `agent.py`.
- Never return `PROCEED_ALWAYS*` / `PROCEED_AUTO_RUN*`. They disable the gate.
- Pin a cheap model. Green does procedural work.
- Keep the prompt short; green runs every day of every episode and burns the most credits.

## Extension points (grow without a contracts PR)

See README §16. For `green/` specifically:
- Memory across turns: `ctx.ledger().get_state("k")` / `put_state("k", {...})`.
- Inputs: `req.options["inputs"]` is a list of messages left for you (judge, crowd, other agents). Read it in `build_prompt` / `dry_run_turn` if you want to react.
- Custom events: `ctx.emitter().custom("name", {...})` emits `x.green.name`; the frontend stores it in `state.custom`.
- Your own tables: `contracts/ext/green/<nn>_<name>.sql`, tables prefixed `green_`.
- Your own battlefield routes: `battlefield/extensions/green_<name>.py` with `router = APIRouter()`, mounted at `/api/x/green/...`. Read-only on core tables; writes only to `green_*` tables.
CI allows exactly those extra paths on a `green/` branch. Nothing else outside `green/`.

## Paste this to your coding agent as its first message

```
You are working in the Red Ledger repo, directory `green/`, as Dev M's coding agent.
Before any edit: read `green/AGENTS.md`, `GIT.md` §7, `README.md` §§0,1,3,5,6,7,16, and
`contracts/agent-service.md`, `contracts/events.md`. Confirm `git branch --show-current` starts with `green/`;
if not, create `green/<topic>` from origin/main. Edit only inside `green/`,
`battlefield/extensions/green_*.py`, `contracts/ext/green/`, and append to `DEVLOG.md`.
Never force-push, never merge, never touch another directory; if you need a contracts change,
write the proposed diff into the PR description and stop. Run `make lint test-green` before
each push. Everything must work with DRY_RUN=true. Goal for this session: get GreenAgent's Droid permission handler verified (Autonomy.OFF finding → contracts/CHANGELOG.md) and a gated pay call end to end.
```

## Don't

- Don't give green investigative tools (audit log, flags beyond what it already sees). Trusting clerk.
- Don't retry blocked actions in the prompt or the code.
- Don't put rules in green that belong in blue.
