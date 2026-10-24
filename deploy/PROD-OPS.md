# PROD-OPS.md — driving the prod stack without moving the operator token

Owner: Dev Ad. Tool: `deploy/prod.sh` (wrapped by `make prod-*`; `make help | grep prod-`).

## Why it works this way

Prod's `OPERATOR_TOKEN` lives in exactly two places: the GitHub `production` environment and
`/opt/redledger/.env` on the VM (mode 600, rendered by `deploy/render-env.sh` on every deploy).
Battlefield publishes no host port in prod, and `api.$DOMAIN` only exists once DNS does. So
instead of bringing the token to you, `prod.sh` brings the request to the token:

```
laptop ── ssh deploy@PROD_HOST ──> cd /opt/redledger && docker compose … exec -T battlefield \
          python3 -c '<fixed bootstrap>' <program, base64> <op> <args, base64 each>
                                       └─> reads OPERATOR_TOKEN from the container's env,
                                           calls http://localhost:8000/api/…, prints the JSON
```

- The token is never in argv on your laptop, in the ssh command line, or in any output. The
  in-container program replaces any `*TOKEN*`/`*KEY*`/`*SECRET*`/`*PASS*` value of its own
  environment with `[REDACTED]` before printing, so even an event payload that somehow
  contained the token comes back scrubbed.
- Your arguments never reach the remote shell or the Python source as code. The program text is
  fixed; it and every argument travel base64-encoded and are decoded in Python. JSON (attack
  plans, scheme params) is parsed and type-checked there.
- Every hop has a timeout: ssh `ConnectTimeout` + keepalives, a local `timeout` around ssh, a
  remote `timeout` around `docker compose exec`, and a per-request HTTP timeout.
- `PROD_DRY=1 make prod-…` prints exactly what would run (program elided, args decoded).
- Through `make`, your values are passed as raw text: the Makefile never exports `EP`, `MODE`,
  `PLAN`, `PARAMS`, … (GNU make would otherwise evaluate a `$(shell …)` inside them on your
  laptop while building the environment), and hands the script `$(value X)` instead. Prod
  targets get no defaults: `MODE`/`SEED`/`DAYS` are passed only if you set them on the command
  line or in the environment, so a bare `make prod-episode` or `make prod-toggle EP=…` fails
  with usage instead of acting on prod. Encoded arguments are capped at 64 KiB.

Don't undo this by hand on the VM: `cat .env`, `docker compose config` (prints interpolated
values, tokens included) and `docker inspect` all put the token on your screen and in your
terminal scrollback. `make prod-logs` is not scrubbed; battlefield doesn't log tokens, but treat
logs as sensitive anyway.

## Prerequisites

- The deploy key at `~/.ssh/redledger_deploy` (override: `PROD_KEY`), the VM's host key already
  in `~/.ssh/known_hosts` (`ssh -i ~/.ssh/redledger_deploy deploy@"$PROD_HOST" true` once; `prod.sh`
  runs ssh with `BatchMode=yes`, so it never prompts).
- `PROD_HOST`: the VM address. It is deliberately not in this public repo: export it, or put it on the first line of `~/.config/redledger/prod_host` (override the path with `PROD_HOST_FILE`). The owner has it in the Vultr console / the `VULTR_HOST` repo secret.
- A deployed stack (`deploy.yml` roll job ran, so `.env` exists; compose refuses to start
  battlefield otherwise). `make prod-health` is the first thing to run.
- Local tools: bash, ssh, base64, coreutils `timeout` (macOS: `brew install coreutils`).

## Commands

| Make | Script | Notes |
|---|---|---|
| `make prod-health` | `prod.sh health` | battlefield `/api/health`, includes each agent's `/health` |
| `make prod-ps` / `make prod-logs [SVC=red]` | `ps`, `logs [SVC]` | last `PROD_LOG_TAIL` (200) lines |
| `make prod-episode MODE= SEED= DAYS= [PLAN=]` | `episode MODE SEED DAYS [PLAN]` | create + start; stdout is the episode id only |
| `make prod-wait EP=` | `wait EP` | exit 0 finished; 3 paused/failed/not started; 124 after `PROD_WAIT_TIMEOUT` (3600 s) |
| `make prod-step/pause/resume EP=` | `step/pause/resume EP` | `step` allows `PROD_STEP_TIMEOUT` (900 s): a live day is three turns plus escalation waits |
| `make prod-toggle EP= MODE=` | `toggle EP MODE` | `off\|shadow\|enforce`, takes effect from the next turn |
| `make prod-attack EP= SCHEME= [PARAMS=]` | `attack EP SCHEME [PARAMS]` | queued for the next red turn |
| `make prod-escalations [EP=]` | `escalations [EP]` | open ones only |
| `make prod-resolve ESC= DECISION=` | `resolve ESC approve\|block` | `by` = `PROD_RESOLVE_BY` (`judge`) |
| `make prod-score EP=` | `score EP` | |
| `make prod-credits EP=` | `credits EP` | sums `turn.ended.factory_credits` per agent and per day; shows the cap and any guard trips |
| `make prod-record EP= [NAME=]` | `record EP [NAME]` | events → `battlefield/fixtures/episodes/<NAME or EP>.jsonl`, secret-scanned |

## Going live: red only

Green raises before starting Droid until integration packages A/B land, and blue's live audit is
disabled by its readiness guard (blue's gate LLM also only runs when its `DRY_RUN` is false). So
the first live configuration runs red's Droid session and keeps green and blue keyless:

1. GitHub `production` environment, **secret**: `FACTORY_API_KEY` (UI or `gh secret set
   FACTORY_API_KEY --env production` in your own terminal; never paste it anywhere else).
2. **Variables**: `DROID_MODEL_RED` (a pinned low-multiplier model, never `auto`; see
   `contracts/CHANGELOG.md` Findings for costs), optional `DROID_REASONING_RED` (e.g. `low`),
   `DRY_RUN=false`, `DRY_RUN_GREEN=true`, `DRY_RUN_BLUE=true`. Keep `MAX_CREDITS_PER_EPISODE` set.
3. Run the deploy workflow and approve the `production` gate.
4. Smoke: `make prod-health` (red `dry_run: false`, green/blue `true`), then
   `make prod-episode MODE=enforce SEED=42 DAYS=2`, `make prod-wait EP=…`, `make prod-credits EP=…`.

Going back: set `DRY_RUN=true` (or `DRY_RUN_RED=true`) and redeploy.


```bash
make prod-health                                   # all three agents ok, dry_run false
EP=$(deploy/prod.sh episode enforce 42 10)         # or: make prod-episode MODE=enforce SEED=42 DAYS=10
make prod-credits EP=$EP                           # after day 1: is the burn what you expected?
make prod-escalations EP=$EP                       # resolve before ESCALATION_TIMEOUT_SEC (90 s)
make prod-resolve ESC=esc_… DECISION=block
make prod-wait EP=$EP && make prod-score EP=$EP
```

`wait` stops on `paused` too. If you didn't pause it, the credit guard did: run `prod-credits`,
then see "Credit cap" below.

## Record the demo fixtures (off vs enforce, same seed)

The seed fixes the company and the legit traffic; `PLAN` pins which scheme red is told to run
on which day (other days red picks). The LLMs still vary run to run, so pin every day you want
to compare:

```bash
PLAN='[{"day":1,"scheme_id":"ghost_vendor"},{"day":3,"scheme_id":"bank_swap"},{"day":5,"scheme_id":"threshold_split"},{"day":7,"scheme_id":"duplicate_invoice"}]'
OFF=$(deploy/prod.sh episode off 42 10 "$PLAN");     make prod-wait EP=$OFF
ON=$(deploy/prod.sh episode enforce 42 10 "$PLAN");  make prod-wait EP=$ON
make prod-score EP=$OFF; make prod-score EP=$ON      # the demo's before/after numbers
make prod-record EP=$OFF NAME=demo-off-s42-10d
make prod-record EP=$ON  NAME=demo-enforce-s42-10d
```

Run them one after the other, not in parallel, so `prod-credits` after the first tells you
what the second will cost.

`record` pages through `GET /api/events` (5000 per page) and refuses to overwrite an existing
fixture unless `PROD_RECORD_OVERWRITE=1`. Then it scans the file, because fixtures get committed
and replayed publicly:

- **Refused** (exit 3, file moved to `redledger-quarantine.*` under `$TMPDIR`, or `/tmp` if
  `$TMPDIR` is inside the repo; path printed): `sk-…`, `fk-…`,
  `ghp_…`/`github_pat_…`, `AKIA…`, `AIza…`, `xox?-…`, JWTs, PEM private keys, `Bearer <long>`, or
  `[REDACTED]` (the VM scrubbed a live token/key out of an event: find out which agent emitted it).
- **Warned** (file kept): hex runs ≥ 32 chars, base64-ish runs ≥ 40 chars with letters and at
  least 4 digits (so prose identifiers like `task-assessment_for_vendor_onboarding_q3` pass).
  Prefix patterns (`sk-`, `fk-`, `gh?_`, `xox?-`) only match at a word start, for the same reason.

Hits are printed as line number + first 4 chars + length, never in full. Commit the fixtures on a
`battlefield/` branch; after the next deploy they are on the VM too (the repo checkout is mounted
into battlefield) and `POST /api/replays/<NAME>/play` replays them.

## Credit cap (`MAX_CREDITS_PER_EPISODE`)

**Measured** (Al, PR #9): one live agent turn costs about **6.7k–10k `factory_credits`**, most of
it ~31k input tokens of system prompt + tool context, so it barely depends on what the turn does.

**One planned demo episode:** 3 Factory-billed turns per day (red turn, green turn, blue audit;
blue's `/gate` uses `BLUE_GATE_LLM_*`, not Factory) × 10 days = **30 turns**:

```
low   30 × 6,700  = 201,000 credits
high  30 × 10,000 = 300,000 credits
```

**Recommended prod cap: `MAX_CREDITS_PER_EPISODE=375000`** = 1.25 × 300,000 (the high estimate).
A normal 10-day demo episode never trips it, even at the top of the measured range. A runaway
(a turn looping on tools, retries, a model swap with a higher multiplier) is paused at most about
25% above a worst-case normal episode. The guard checks after every turn and pauses after the
turn that crosses the line, so the real worst case is the cap plus one turn: ~385k. For a
different length, scale it: 1.25 × 30,000 × DAYS = **37,500 × DAYS** (4 days → 150000).

The cap is **per episode**, not a budget. The demo plan above plus one live run during judging is
3 episodes ≈ 0.6M–0.9M credits; check the prod Factory key's balance covers that before
Saturday. (`README.md` §11 and `deploy/OWNER-CHECKLIST.md` suggest `40` as an example; at
6.7k+ per turn that pauses every episode after its first turn.)

**It is off until you set it.** `render-env.sh` writes `MAX_CREDITS_PER_EPISODE='0'` when the
`production` variable is unset, and `0` disables the guard.

Set or raise it:

```bash
gh variable set MAX_CREDITS_PER_EPISODE --env production --body 375000
gh workflow run deploy.yml                 # re-renders .env on the VM and recreates battlefield
make prod-credits EP=<any episode>         # "max_credits_per_episode": 375000.0 confirms it
```

Battlefield reads the cap at startup, so a change takes a redeploy, and a redeploy restarts
battlefield, which kills any running episode's loop (its status stays `running`/`paused` in the
DB). Between episodes that doesn't matter. If the guard paused an episode you want to finish:
raise the cap, redeploy, then `make prod-resume EP=…`; the running total is re-read from that
episode's `turn.ended` events, so the new cap applies to what it has already spent. Resuming
without raising the cap buys exactly one more paid turn before it pauses again.

## Running an evolution on prod (lineages)

A lineage is a chain of headless generations (docs/EVOLUTION-DESIGN.md); on prod every live agent
turn and every `/reflect` costs Factory credits, so `prod-evolve` refuses to start without a
lineage cap. Same token-free channel as the episode targets: everything runs inside battlefield on
the VM.

```bash
make prod-health                          # which agents are live (dry_run false)
LN=$(make -s prod-evolve GENS=3 DAYS=5 MODE=enforce SEED=42 MAX_CREDITS=1000000)   # [REVEAL_DAYS= REVEAL_GENERATIONS=]
make prod-lineage-wait LN=$LN             # progress on stderr; exits 0 finished, 3 paused/failed, 124 timeout
make prod-lineage-status LN=$LN           # per generation: seed, day, status, score, turn credits
make prod-lineage-pause LN=$LN            # / prod-lineage-resume (also lifts a lineage credit-cap pause)
make prod-evolution-report LN=$LN         # runs/$LN/report.json + report.md (partial while it runs)
make prod-lineage-export LN=$LN [GEN=2]   # runs/$LN/{lineage.json,playbooks/,gen-<g>/...}
```

- **No defaults on prod:** `GENS`, `DAYS`, `MODE`, `SEED` and `MAX_CREDITS` must be given. `MAX_CREDITS`
  becomes `config.max_credits` (whole lineage, turns + reflections); `MAX_CREDITS_PER_EPISODE` still
  caps each generation. Rough cost with red live and green/blue keyless: about 7–9k credits per red turn,
  so a 5-day generation is about 40–50k plus red's reflection.
- **Credits shown are a lower bound:** `prod-lineage-status` sums `turn.ended` credits; `/reflect`
  usage counts toward the cap but isn't in those events.
- **Waiting:** `PROD_LINEAGE_WAIT_TIMEOUT` (7200 s) and `PROD_LINEAGE_WAIT_INTERVAL` (30 s; each poll
  scores every generation on the server). A timed-out wait leaves the lineage running.
- **Ground truth:** the export and the report contain `origin`. They are fetched into a temp dir
  outside the repo, secret-scanned by `battlefield/scripts/evolution_report.py` (a key/token shape
  writes nothing and exits 3), and written under `runs/` (or `RUNS_DIR`), which ignores itself.
  Never commit or publish them.
- One lineage runs at a time: `prod-evolve` refuses (exit 3) while another is running. If two
  operators race, the loser's lineage is created but not started (409); it just stays `created`.

## Testing prod.sh without prod

Make-level self-check (after any Makefile edit; must print nothing and create no file):

```bash
PROD_DRY=1 make -s prod-score EP='$(shell touch /tmp/rl-canary)' >/dev/null 2>&1
make -s help EP='$(shell touch /tmp/rl-canary)' >/dev/null
make -s prod-episode >/dev/null 2>&1 && echo "BUG: prod-episode ran with defaults"
ls /tmp/rl-canary 2>/dev/null && echo "BUG: make evaluated user input"
```

The ssh and `docker compose exec` layers can be swapped out:

| Variable | Default | Local test value |
|---|---|---|
| `PROD_SSH` | ssh to `$PROD_USER@$PROD_HOST` with the options above | `bash -c` (takes the remote shell string as one argument) |
| `PROD_DIR` | `/opt/redledger` | any existing directory |
| `PROD_BF_EXEC` | `$PROD_COMPOSE exec -T battlefield` | a wrapper that exports the battlefield process's `OPERATOR_TOKEN` and runs its argv |
| `RL_OPS_API` (read in the exec env) | `http://localhost:8000` | e.g. `http://127.0.0.1:8100` |

Run battlefield (port 8100) and `mock_agents` (8101–8103) on a scratch Postgres with
`OPERATOR_TOKEN` set only in battlefield's environment, have the `PROD_BF_EXEC` wrapper read it
from `/proc/<battlefield pid>/environ` (that is what `docker exec` does: the new process gets
the container's environment), then run `episode`/`wait`/`score`/`record`/`credits` (and `evolve`/`lineage-*`/`evolution-report`, with
`RUNS_DIR` pointed at a scratch directory) as usual.
Delete any fixture recorded this way; don't commit it.
