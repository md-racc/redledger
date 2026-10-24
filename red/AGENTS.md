# red/ — working guide for Dev Al and any coding agent in this directory

Read the root `README.md` (§§3, 5, 6, 8) and `GIT.md` first. This file is the local rulebook.

## Your job

Build the attacker. Red is a Droid session with a small tool surface (`tools.py`) and a catalog
of fraud schemes (`schemes/`). Red's success condition is money leaving Coastal Supply Co.
without the controller noticing. Red being too weak is the most likely way the whole demo
fails: if the controller-off baseline doesn't lose real money, nothing else matters.

## Boundaries

- You own everything under `red/`. Nothing else. Branch prefix `red/`.
- You talk to the world only through `agentkit.LedgerClient` (red routes: create vendor,
  request vendor change, submit invoice, submit expense, add employee, declare attack). You
  cannot pay, approve, freeze, or read the audit log. If you think red needs another route,
  that's a `contracts/` PR to Ad.
- You never import from `battlefield/`, `green/`, or `blue/`.
- `origin` and `attack_id` are hidden from you by battlefield. Don't try to infer them.

## Files

| File | What goes there |
|---|---|
| `schemes/base.py` | abstract scheme; don't change its interface without a contracts PR |
| `schemes/<id>.py` | one class per scheme: `viable`, `plan`, `execute`, catalog fields |
| `schemes/__init__.py` | the registry; `/schemes` and the judge's attack picker read it |
| `tools.py` | what the model can call; wrappers over LedgerClient; descriptions matter |
| `agent.py` | `RedAgent(DroidAgent)`: prompt construction and the DRY_RUN path |
| `prompts/system.md` | the persona; a string, replaces Droid's default |
| `server.py` | leave alone; it's the agentkit factory plus `/schemes` |
| `tests/` | one test per scheme using `respx` against a fake Ledger API |

## Scheme checklist (README §8 has the list)

Each scheme needs: a `story` sentence a non-engineer judge understands, a `params_schema` so the
judge's picker can offer knobs, `viable()` so red doesn't attempt impossible things, `plan()`
that reads the ledger and resolves amounts/ids, `execute()` that makes ≤4 ledger writes, and a
test. Make amounts look like real traffic (see what `inspect_books` returns); the realistic
schemes are the ones that beat the rules.

Priority order: `ghost_vendor` (done, reference), `bank_swap`, `duplicate_invoice`,
`threshold_split`, then the rest.

## DRY_RUN

`RedAgent.dry_run_turn` must work with no Factory key: it rotates schemes deterministically. Keep
it working; backend and frontend run whole episodes on it.

## Local loop

`AGENT_TOKEN` replaces `INTERNAL_TOKEN` (still accepted as a fallback); use your own `FACTORY_API_KEY` locally. Pass `AGENT_TOKEN=<your .env value>` (compose default `change-me-agent`) where the command below says `INTERNAL_TOKEN=change-me`, or battlefield and your service 401 each other.

```
make mock-agents                       # battlefield + stub green/blue
cd red && uv sync --extra dev
AGENT_NAME=red BATTLEFIELD_URL=http://localhost:8000 INTERNAL_TOKEN=change-me DRY_RUN=true \
  uv run uvicorn server:app --port 8001 --reload
# in another shell: make episode MODE=shadow ; watch :8000/api/fe/episodes/<EP>/attacks
```
Stop the mock red first (`docker compose stop red`) so battlefield hits yours.

## Droid specifics

- Autonomy HIGH; permission handler approves everything (default in `DroidAgent`).
- Tool IDs: after the first live turn, `agentkit` logs the exact MCP tool ids; record the format in `contracts/CHANGELOG.md` Findings.
- Pin `DROID_MODEL` to a low-multiplier model. Red doesn't need frontier reasoning.
- Log credits per turn (agentkit does); if a turn costs >2 credits, shorten the prompt.

## Extension points (grow without a contracts PR)

See README §16. For `red/` specifically:
- Memory across turns: `ctx.ledger().get_state("k")` / `put_state("k", {...})`.
- Inputs: `req.options["inputs"]` is a list of messages left for you (judge, crowd, other agents). Read it in `build_prompt` / `dry_run_turn` if you want to react.
- Custom events: `ctx.emitter().custom("name", {...})` emits `x.red.name`; the frontend stores it in `state.custom`.
- Your own tables: `contracts/ext/red/<nn>_<name>.sql`, tables prefixed `red_`.
- Your own battlefield routes: `battlefield/extensions/red_<name>.py` with `router = APIRouter()`, mounted at `/api/x/red/...`. Read-only on core tables; writes only to `red_*` tables.
CI allows exactly those extra paths on a `red/` branch. Nothing else outside `red/`.

## Evolution / lineages

In lineage episodes your `/turn` gets `options.lineage {id, generation, playbook_version}` and
`options.debrief`: your own **resolved** attacks from the last `reveal_days` days, with the controls
they ran into (verdict rules and reasons, flags, freezes). That disclosure is deliberate and is the
one exception to "red doesn't see blue's reasons" below; outside the debrief the rule stands.
- Read and write your playbook with `ledger.get_playbook()` / `ledger.put_playbook(content, rationale, base_version)`
  inside your turn (`None` outside lineages: fall back to defaults).
- Override `reflect(req)` (and `dry_run_reflect`) on your agent: `req.review` is the after-action
  review of the whole generation, `req.playbook` your current version; return new content or `None`.
- Composed schemes go in the playbook and are declared as `scheme_id = "evolved:<slug>"`.
- `battlefield/mock_agents/server.py` (mock red's evasion ladder) is a worked example of using only
  these inputs. Contract: `contracts/agent-service.md` (Lineages); runbook: README §15; design: `docs/EVOLUTION-DESIGN.md` §12.

## Paste this to your coding agent as its first message

```
You are working in the Red Ledger repo, directory `red/`, as Dev Al's coding agent.
Before any edit: read `red/AGENTS.md`, `GIT.md` §7, `README.md` §§0,1,3,5,6,7,16, and
`contracts/agent-service.md`, `contracts/events.md`. Confirm `git branch --show-current` starts with `red/`;
if not, create `red/<topic>` from origin/main. Edit only inside `red/`,
`battlefield/extensions/red_*.py`, `contracts/ext/red/`, and append to `DEVLOG.md`.
Never force-push, never merge, never touch another directory; if you need a contracts change,
write the proposed diff into the PR description and stop. Run `make lint test-red` before
each push. Everything must work with DRY_RUN=true. Goal for this session: implement the next scheme in README §8 with a test, land it against `make mock-agents`.
```

## Don't

- Don't hardcode entity ids. Read them.
- Don't add tools that bypass the scheme catalog's bounds (e.g. "submit 50 invoices").
- Don't make red adaptive by reading blue's reasons from events; red is not supposed to see them. Adaptation comes from what got blocked (invoice status), which you can read.
