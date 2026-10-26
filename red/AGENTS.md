# red/ — maintenance guide (original author: Al)

Read the root `README.md`, `docs/ARCHITECTURE.md` and `docs/CONTRIBUTING.md` first. This file is the local rulebook.

## Your job

Build the attacker. Red is a Droid session with a small tool surface (`tools.py`) and a catalog
of fraud schemes (`schemes/`). Red's success condition is money leaving Meridian Components
without the controller noticing. Preserve the controller-off baseline and scheme bounds.

## Files

| File | What goes there |
|---|---|
| `schemes/base.py` | abstract scheme; don't change its interface without a contracts PR |
| `schemes/<id>.py` | one class per scheme: `viable`, `plan`, `execute`, catalog fields |
| `schemes/__init__.py` | the registry; `/schemes` and the judge's attack picker read it |
| `tools.py` | what the model can call; wrappers over LedgerClient; descriptions matter |
| `agent.py` | `RedAgent(DroidAgent)`: prompt construction and the DRY_RUN path |
| `prompts/system.md` | the persona; a string, replaces Droid's default |
| `server.py` | it's the agentkit factory plus `/schemes` |
| `tests/` | one test per scheme using `respx` against a fake Ledger API |

## Scheme checklist (docs/ARCHITECTURE.md (Red) has the list)

Each scheme needs: a `story` sentence a non-engineer understands, a `params_schema` so the
judge's picker can offer knobs, `viable()` so red doesn't attempt impossible things, `plan()`
that reads the ledger and resolves amounts/ids, `execute()` that makes ≤4 ledger writes, and a
test. Make amounts look like real traffic (see what `inspect_books` returns); the realistic
schemes are the ones that beat the rules.

The eight built-in schemes are documented in `docs/ARCHITECTURE.md`; preserve their catalog interfaces.

## DRY_RUN

`RedAgent.dry_run_turn` must work with no Factory key: it rotates schemes deterministically. Keep
it working; backend and frontend run whole episodes on it.

## Local loop

Use the same `AGENT_TOKEN` as your local battlefield (compose default `change-me-agent`).
Keep local development keyless with `DRY_RUN=true`.

```
make mock-agents                       # battlefield + stub green/blue
docker compose --project-directory . -f deploy/compose/docker-compose.yml stop red
cd red && uv sync --extra dev
AGENT_NAME=red BATTLEFIELD_URL=http://localhost:8000 AGENT_TOKEN=change-me-agent DRY_RUN=true \
  uv run uvicorn server:app --port 8001 --reload
# in another shell: make episode MODE=shadow ; watch :8000/api/fe/episodes/<EP>/attacks
```
Run these commands from the repository root; stop the mock red before starting yours.

## Droid specifics

- Autonomy HIGH; permission handler approves everything (default in `DroidAgent`).
- Tool IDs: `<server>___<tool>`, derived and checked by `agentkit` every session (recorded in `contracts/CHANGELOG.md` Findings).
- Pin `DROID_MODEL_RED` for reproducible live experiments. Red doesn't need frontier reasoning.
- Log credits per turn (agentkit does). The measured median red turn is ~2,790 credits (#216); if a turn runs well above that, shorten the prompt.

## Evolution / lineages

In lineage episodes your `/turn` gets `options.lineage {id, generation, playbook_version}` and
`options.debrief`: your own **resolved** attacks from the last `reveal_days` days, with the controls
they ran into (verdict rules and reasons, flags, freezes). That disclosure is deliberate and is the
one exception to "red doesn't see blue's reasons" below; outside the debrief the rule stands.
- Read and write your playbook with `ledger.get_playbook()` / `ledger.put_playbook(content, rationale, base_version)`
  inside your turn (`None` outside lineages: fall back to defaults).
- Override `reflect(req)` (and `dry_run_reflect`) on your agent: `req.review` is the after-action
  review of the whole generation, `req.playbook` your current version; return new content or `None`.
- Composed (`evolved:<slug>`) schemes are not implemented: red runs only the catalog, and evolution drops anything outside it.
- `battlefield/mock_agents/server.py` (mock red's evasion ladder) is a worked example of using only
  these inputs. Contract: `contracts/agent-service.md` (Lineages); runbook and design: `docs/ARCHITECTURE.md` (Evolution).

## Don't

- Don't hardcode entity ids. Read them.
- Don't add tools that bypass the scheme catalog's bounds (e.g. "submit 50 invoices").
- Don't make red adaptive by reading blue's reasons from events; red is not supposed to see them. Adaptation comes from what got blocked (invoice status), which you can read.

## Maintenance validation

Follow root `AGENTS.md` and `docs/CONTRIBUTING.md`; historical team prefixes are no longer path restrictions.
Run root `make lint test-red` for changes here; keep `DRY_RUN=true` keyless.
Use `agentkit.LedgerClient` for agent ledger access and preserve the root information boundaries.
