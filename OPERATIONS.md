# OPERATIONS.md: run, deploy and operate Red Ledger

Owner: Dev Ad. Local runs, configuration, deploy and prod (`https://app.redledger.us`). Design: `ARCHITECTURE.md`;
frontend: `FRONTEND.md`; team rules: `AGENTS.md`, `GIT.md`.

## 1. Run locally

Nothing here needs a Factory or LLM key: under `DRY_RUN=true` agents return canned turns and blue's gate runs rules.

```bash
cp .env.example .env     # set AGENT_TOKEN and OPERATOR_TOKEN to two DIFFERENT strings; DRY_RUN=true if you have no key
make mock-agents         # postgres + battlefield + stub red/green/blue (no model calls); ports 5432, 8000-8003
make episode MODE=enforce SEED=42 DAYS=4      # prints `export EP=...`
make score EP=$EP
```

| Stack | Command | What runs |
|---|---|---|
| Stub agents (Docker) | `make mock-agents` | battlefield and Postgres, plus stub agents built from the battlefield image. Agent devs run their own service on top (`uv run uvicorn server:app --port 800X --reload`) |
| No Docker | `make local-stack [AGENTS=mock\|real] [RED=\|GREEN=\|BLUE=mock\|real]` | pgserver Postgres 16 plus battlefield and agents as processes; own tokens in `.local-stack/env`, never reads `.env`; real agents default to `DRY_RUN=true` and take keys only from your shell. `local-stack-status`, `local-stack-stop [RESET=1 CONFIRM=yes]` |
| Real agents, keyless | `make up-dry` | the real agent containers in DRY_RUN with hot reload (`docker-compose.dev.yml`) |
| Real agents, live | `make up` | spends Factory credits (needs `FACTORY_API_KEY` and `DROID_MODEL_*`) |

Run one stack per machine (they all bind 8000–8003). `make down` stops Docker stacks; `make db-reset` wipes the
volume. `make help` lists the rest (`step`, `toggle`, `attack`, `record`, `replay`, `evolve`, `lineage-*`, ...).

**Frontend.** With no backend: `cd frontend && npm install && NEXT_PUBLIC_MOCK=true npm run dev`
(<http://localhost:3000>, replays `public/mocks/sample.jsonl`; a build-time switch). Against a backend, set the
server-only `BATTLEFIELD_URL` and `OPERATOR_TOKEN` in `frontend/.env.local` and run `npm run dev`. Without Docker,
`npm run dev:live` runs `tools/fake-battlefield.mjs` (a contract stand-in, not the real gate) plus `next dev`. A blank
`ADMIN_KEY` makes everyone admin under `next dev` and nobody admin in a production build (including compose).

**Tokens** (`AGENTS.md` invariant 12). A request with `X-Agent: <a>` presents that agent's token (`AGENT_TOKEN_<A>`,
else the shared `AGENT_TOKEN`); one without `X-Agent` presents `OPERATOR_TOKEN`; anything else is a 401. The
Makefile's curl targets send `OPERATOR_TOKEN` from `.env` (or `.local-stack/env` while it is up). A host-run agent
needs battlefield's `AGENT_TOKEN` (compose default `change-me-agent`).

**Tests and lint (the commands that actually work).**

```bash
make install                                   # uv sync --extra dev in every Python service + npm install in frontend
cd battlefield && uv run --extra dev pytest -q # per service; same for agentkit, red, green, blue
cd frontend && npm run typecheck && npm run lint && npm test
uvx ruff check agentkit battlefield red green blue && uvx ruff format --check agentkit battlefield red green blue
```

`make test-<area>` and `make lint` work only after `make install` (see Known issues). Battlefield's DB tests skip
unless `TEST_DATABASE_URL` points at a Postgres 16 database. CI sets it, and runs the suite on both
`postgres:16-alpine` and `timescale/timescaledb:latest-pg16`.

## 2. Environment variables

`.env.example` is the local template. In prod, `deploy/render-env.sh` writes `/opt/redledger/.env` from the GitHub
`production` environment on every deploy; nobody edits it by hand. "Secret" is a `production` secret, other prod
values are `production` variables. Never put a token in a `NEXT_PUBLIC_*` var (they ship to the browser).

| Variable | Read by | Default | Prod |
|---|---|---|---|
| `AGENT_TOKEN` | battlefield, agents | `change-me-agent` (compose) | secret, `openssl rand -hex 32` |
| `AGENT_TOKEN_RED`/`_GREEN`/`_BLUE` | battlefield (all three); each agent only its own, as `AGENT_TOKEN` | blank, so each agent uses the shared `AGENT_TOKEN` (warning) | secrets, all three or none; render-env refuses a partial or duplicate set |
| `OPERATOR_TOKEN` | battlefield, frontend server, Makefile | `change-me` | secret, distinct from every agent token |
| `FACTORY_API_KEY` | agents (Droid) | blank | secret, the dedicated prod key, stored nowhere else |
| `DROID_MODEL_RED`/`_GREEN`/`_BLUE` | each agent as `DROID_MODEL` | blank (never pin `auto`) | `gpt-5.4-mini` (red, blue) |
| `DROID_REASONING_RED`/`_GREEN`/`_BLUE` | each agent | blank = model default; `none\|off\|minimal\|low\|medium\|high\|xhigh\|max`; a bad value stops the agent | optional |
| `DRY_RUN` | agents | `false` | `false` |
| `DRY_RUN_RED`/`_GREEN`/`_BLUE` | each agent as `DRY_RUN` | blank = follow `DRY_RUN` | `DRY_RUN_GREEN=true`, `DRY_RUN_BLUE=false` (red and blue's audit live, green keyless). Set them explicitly |
| `MAX_CREDITS_PER_EPISODE` | battlefield | `0` (guard off) | `375000` |
| `EPISODE_DEFAULT_DAYS` | battlefield | `10` | default |
| `TURN_TIMEOUT_SEC` | battlefield, agents | `180` (Droid stream gets `-10`) | default |
| `GATE_TIMEOUT_SEC` | battlefield, agents | `8` | default |
| `ESCALATION_TIMEOUT_SEC` | battlefield, agents | `90` | default |
| `HTTP_TIMEOUT_SEC` | agents (agentkit) | `15` | default (not rendered) |
| `APPROVAL_THRESHOLD` | battlefield, agents | `5000` | default |
| `FP_PENALTY_RATE` | battlefield | `0.02` | default |
| `FP_FLAT_PENALTY` | battlefield | `50` | default (not rendered) |
| `DAY_PAUSE_SEC` | battlefield | `0` | default |
| `LOG_LEVEL` | all Python services | `info` | default |
| `DATABASE_URL` | battlefield only | compose's Postgres | compose default (Postgres not exposed) |
| `RED_URL`/`GREEN_URL`/`BLUE_URL` | battlefield (`BLUE_URL` also in every agent's env, unused) | `http://<agent>:800X` | compose default |
| `FIXTURES_DIR`, `SCHEMA_PATH` | battlefield | `fixtures/episodes`, `db/schema.sql` | image default |
| `CORS_ORIGINS` | battlefield | `http://localhost:3000` | defaults to `https://app.<DOMAIN>` |
| `POSTGRES_IMAGE` | compose | `timescale/timescaledb:latest-pg16` locally | `postgres:16-alpine` (render-env default) |
| `BLUE_GATE_LLM_PROVIDER`/`_MODEL`, `BLUE_GATE_LLM_API_KEY` | blue gate | `gemini`, blank | unset key: the gate is rules plus learned controls (gate LLM output is logged, never decides) |
| `CRS_USERNAME`, `CRS_PASSWORD` | blue only | blank (checks return `unknown`) | secrets (CRS sandbox login) |
| `CRS_LIVE` | blue | off | not set; acceptance-only switch for the keyless audit |
| `CRS_API_KEY`, `CARTESIA_API_KEY` | nothing (legacy plumbing) | blank | unset |
| `MOCK_BLUE_ESCALATE` | stub blue (`make mock-agents`) | blank | n/a |
| `BATTLEFIELD_URL` | frontend server proxy | `http://battlefield:8000` (compose) | compose default |
| `NEXT_PUBLIC_WS_URL` | frontend server (handed to the browser in the ws-ticket) | `ws://localhost:8000` | `wss://app.redledger.us` (set explicitly; see Known issues) |
| `NEXT_PUBLIC_MOCK` | frontend (build time) | `false` | `false` |
| `ADMIN_KEY` | frontend server | blank | secret, at least 32 chars, distinct from every token; required when `CF_ACCESS_*` are blank |
| `CF_ACCESS_TEAM_DOMAIN`, `CF_ACCESS_AUD` | frontend middleware | blank (check off) | blank (public read-only mode) |
| `ELEVENLABS_API_KEY`, `ELEVENLABS_STT_MODEL` | frontend voice route (admin-only) | blank = voice off | secret; model default `scribe_v2` |
| `DOMAIN` | render-env, Caddy | blank | `redledger.us` |
| `GITHUB_REPO` | compose image refs | n/a | not settable (GitHub reserves `GITHUB_`); deploy.yml passes `github.repository` |
| `TEST_DATABASE_URL` | battlefield DB tests | unset (tests skip) | CI only |

The repository-level Actions settings hold only deploy plumbing: the secrets `VULTR_HOST`, `VULTR_USER` (`deploy`)
and `VULTR_SSH_KEY`, and the variable `DEPLOY_ENABLED=true`.

## 3. Deploy

The pipeline runs CI, then `deploy.yml`, then a `production` approval, then the VM.

1. **CI** (`ci.yml`, every PR and push to `main`): path-filtered ruff and pytest per Python service, frontend
   typecheck/lint/vitest, `ownership-guard`, `contracts-guard`. Integration squash-merges READY PRs (`GIT.md` §4).
   Repo settings: `main` protected (PR required, 0 approvals, those 8 checks required, admins included, no force
   push or deletion), squash-only, auto-delete branches, Actions with read/write workflow permissions.
2. **`deploy.yml`** runs on every push to `main` or by `workflow_dispatch`. `concurrency: deploy` with
   `cancel-in-progress: false`, so runs queue rather than cancel. Stale runs can sit waiting for approval: check them
   with `gh run list --workflow deploy.yml --status waiting` and approve the newest. A squash title containing
   `[skip ci]` skips both workflows on `main`.
   - The `build` job has no environment and sees no app secrets. It pushes five images to GHCR tagged `latest` and
     the commit SHA, with no build args.
   - The `roll` job needs `DEPLOY_ENABLED=true` and the **`production` environment, whose required reviewer is Ad**.
     After approval it SSHes to the VM as `deploy`, runs `git reset --hard origin/main` in `/opt/redledger`, renders
     `.env` with `deploy/render-env.sh`, runs `docker compose -f docker-compose.yml -f docker-compose.prod.yml pull`
     and `up -d` with `IMAGE_TAG=<sha>`, restarts Caddy if the Caddyfile changed, and probes battlefield from inside
     its container.
3. **render-env** writes atomically (mode 600, prints only names) and refuses on an empty or equal token, a partial
   or duplicate per-agent set, a short or reused `ADMIN_KEY`, or a `DOMAIN` with neither full `CF_ACCESS_*` nor
   `ADMIN_KEY`. `docker-compose.prod.yml` fails closed if any token is unset.
4. **Applying a variable or secret change:** change it in `production` (`gh variable set NAME --env production
   --body ...` or `gh secret set NAME --env production`), then re-run the workflow (`gh workflow run deploy.yml`, or
   `gh run rerun <run>`) and approve it. Rotation works the same way. Rotating `ADMIN_KEY` logs every admin out.
5. **Rollback:** the durable fix is `git revert` through a PR plus a merge, which redeploys. For a quick rollback,
   re-run an older successful deploy run. It pulls that commit's images but uses current `main`'s compose files and
   env render, and the next merge rolls forward again. The workflow has no `IMAGE_TAG` input.

**Every deploy recreates every container** (new image tags), killing any running episode or lineage loop (its DB
status stays `running`/`paused`). Merge between runs.

**VM (one-time):** `deploy/bootstrap.sh <org>/redledger <domain>` (root, Ubuntu) installs Docker, opens 80/443,
creates `deploy` and clones to `/opt/redledger`. Then set the deploy SSH key and `VULTR_*` secrets, fill `production`
(§2), `docker login ghcr.io` as `deploy`, point proxied Cloudflare DNS for `app.`, `red.`, `blue.` at the VM (SSL Full
strict), set `DEPLOY_ENABLED=true` and run the workflow.

Schema changes aren't migrated: a column change means `make db-reset` on the box (record fixtures first).

## 4. Operate prod

`deploy/prod.sh` (wrapped by `make prod-*`) runs every API call **inside the battlefield container on the VM** over
SSH, so `OPERATOR_TOKEN` never leaves the VM.

Arguments travel base64-encoded (never parsed by a shell), output redacts any token/key value, every hop has a
timeout, and prod targets take no defaults (a bare `make prod-episode` prints usage). `PROD_DRY=1` prints what would
run. On the VM never `cat .env`, `docker compose config` or `docker inspect` (they print the token); treat
`make prod-logs` as sensitive.

Prerequisites: the deploy key at `~/.ssh/redledger_deploy` (`PROD_KEY`), the VM host key in `known_hosts`, and
`PROD_HOST` exported or on the first line of `~/.config/redledger/prod_host` (the address is not in the repo). Run
from a fresh `origin/main` checkout.

| Target | Purpose |
|---|---|
| `prod-health` | battlefield `/health`, including each agent's `/health` (`dry_run`, `droid_ok`, model) |
| `prod-ps` / `prod-logs [SVC=red]` | `docker compose ps`; the last `PROD_LOG_TAIL` (200) log lines |
| `prod-episode MODE= SEED= DAYS= [PLAN='<json>']` | create and start an episode; stdout is the episode id |
| `prod-wait EP=` | poll until finished: exit 0 done, 3 paused/failed, 124 after `PROD_WAIT_TIMEOUT` (3600 s) |
| `prod-step EP=` | run one day of a paused episode (`PROD_STEP_TIMEOUT` 900 s) |
| `prod-pause EP=` / `prod-resume EP=` | pause; resume (also re-arms the credit guard) |
| `prod-toggle EP= MODE=off\|shadow\|enforce` | change the controller mode from the next turn |
| `prod-attack EP= SCHEME= [PARAMS='<json>']` | queue a scheme for red's next turn |
| `prod-fixtures EP= FILE=` | seed operator fixtures (legit employees and expenses) from a local JSON file |
| `prod-crs-episode SEED= [DAYS=2]` | blue's CRS identity scenario (personas P01/P12/P16), stepped with live audit; exit 0 PASS, 2 FAIL, 3 busy, 1 a step failed |
| `prod-escalations [EP=]` / `prod-resolve ESC= DECISION=approve\|block` | list open escalations; resolve one (`by` = `PROD_RESOLVE_BY`, default `judge`) |
| `prod-score EP=` | the episode's score |
| `prod-credits EP=` | `factory_credits` per agent and day, against the cap, with any guard trips |
| `prod-record EP= [NAME=]` | write events to `battlefield/fixtures/episodes/<NAME>.jsonl`, secret-scanned (a key-shaped hit quarantines the file outside the repo, exit 3); `PROD_RECORD_OVERWRITE=1` to replace |
| `prod-evolve GENS= DAYS= MODE= SEED= MAX_CREDITS= [REVEAL_DAYS= REVEAL_GENERATIONS=]` | create and start a lineage; stdout is the lineage id |
| `prod-lineage-status LN=` | per generation: seed, day, status, score, turn credits |
| `prod-lineage-wait LN=` | poll until finished, failed or paused (`PROD_LINEAGE_WAIT_TIMEOUT` 7200 s) |
| `prod-lineage-pause LN=` / `prod-lineage-resume LN=` | pause the lineage and its running generation; resume at the same generation (also lifts a lineage-cap pause) |
| `prod-evolution-report LN=` | `runs/<LN>/report.json` and `report.md` (partial while it runs) |
| `prod-lineage-export LN= [GEN=]` | `runs/<LN>/` bundle. **Contains `origin`: never commit or publish it** |

Battlefield runs one episode or lineage at a time; a second answers `409 another run is active`. To test `prod.sh`
without prod, point `PROD_SSH="bash -c"`, `PROD_BF_EXEC` and `RL_OPS_API` at a local battlefield (script header).
After a Makefile edit, `make -s help EP='$(shell touch /tmp/rl-canary)'` must create no file.

## 5. Running a show (judging loop)

**The background run.** The site shows whatever is running. Keep one lineage going for the whole judging window:

```bash
make prod-health                                    # red and blue dry_run false, green true
LN=$(make -s prod-evolve GENS=4 DAYS=5 MODE=enforce SEED=42 MAX_CREDITS=1000000)
make prod-lineage-status LN=$LN                     # check progress and credits
make prod-lineage-pause LN=$LN                      # / prod-lineage-resume LN=$LN
```

There are two caps:

- `MAX_CREDITS` caps the whole lineage, turns plus reflections. Lift its pause with `prod-lineage-resume`.
- `MAX_CREDITS_PER_EPISODE` pauses only a generation's episode, and `prod-lineage-wait` exits 3 naming it. Lift that
  with `make prod-resume EP=<ep>`.

`prod-lineage-status` credits are a lower bound, because `/reflect` usage counts toward the cap but isn't in
`turn.ended`. **Freeze merges during a show:** approving a deploy restarts every container and kills the run.

**Admin login.** Open `https://app.redledger.us/admin` once on each presenting laptop and paste `ADMIN_KEY`. Ad shares
it out of band. Everyone else is a viewer, and the proxy refuses their non-GET requests.

**What a presenter or judge does on the site:**

- **Run episode** and **Launch attack** join the running episode ("watching the run already in progress") and
  follow a lineage generation to generation; an attack is queued for red's next turn. With no run active, an attack
  creates a paused sandbox episode stepped one day per click.
- **Say it in your own words** (admin-only, ElevenLabs speech-to-text): in the attack console, speak or type a fraud
  scheme. Red uses the words to set the amount and details, and the closest of its eight schemes runs. Without
  `ELEVENLABS_API_KEY`, typing still works.
- **Approve / Block** an open escalation within 90 s (`ESCALATION_TIMEOUT_SEC`; terminal: `prod-resolve`).
- **Controller off / shadow / enforce** switches the controller mode from the next turn.
- **Compare**, **Evolution**, **Report** (blue's end-of-day text), **raw** JSON on every card, and the top bar's
  LIVE/RECORDED/SHOW/REPLAY badge with each agent's `/health`.
- **Pitch mode** (`P`, `?pitch=1`, admin **Live pitch**) joins the current run (an admin screen with none starts a
  live enforce episode); captions come only from real events, and an admin screen auto-blocks an unanswered escalation
  after 40 s. With no backend it replays the recorded prod run, badged RECORDED.
- **The 90-second show** (`S` or `?show=1`; `space`, `←` `→`, `esc`) needs its own episodes, so with live agents or
  another run active it plays the recording and says so (`?show=live|recorded` forces a source).
- **Backstage consoles** (`/backstage/{red,green,blue,battlefield}`, or the `red.` and `blue.` hosts, admin-only)
  follow the running episode and mirror the presenter's selection through `/api/sync`.

Before going on stage: `prod-health` is green, the lineage is `running`, `/backstage/battlefield` shows the
services, and the Evolution card shows a real lineage, not the synthetic sample (it tries `?lineage=` first).

## 6. Costs

Measured on prod with `gpt-5.4-mini` (`contracts/CHANGELOG.md` Findings):

| Turn | Credits |
|---|---|
| Red turn | median ~2,790 (1,043–3,725) |
| Blue audit | median ~3,985 (3.3k–5.4k when its tools work) |
| Green | 0 (keyless) |
| Blue `/gate` | 0 Factory credits (rules, no gate LLM in prod) |

A live day is about 6.8k credits: ~68k per 10-day episode, ~34k per 5-day generation plus red's reflection.

**The per-episode cap is `375000`.** After each turn battlefield sums `turn.ended.factory_credits` and pauses the
episode at the cap (`error {where: "credit_guard"}`; worst case cap plus one turn). It is read at startup: to finish a
guard-paused episode, raise it, redeploy, then `make prod-resume EP=`. Lineages also need `MAX_CREDITS`. Check the
burn with `make prod-credits EP=` after day 1.

## 7. Access

- **Edge.** Cloudflare (proxied) in front of Caddy, which serves only Cloudflare's IP ranges (others get 403):
  `app.<domain>` → frontend, except `/api/ws` → battlefield (60 s single-use ticket); `red.` and `blue.` → the
  hidden admin-only backstage doors. Battlefield's REST API has no public hostname; operators use `make prod-*`.
- **Public read-only mode** (prod): `CF_ACCESS_*` are blank, and the Cloudflare Access app stays attached with a
  bypass policy ahead of the team policy, so anyone can watch. The frontend's `/api/bf/*` proxy holds
  `OPERATOR_TOKEN` and allows only GET/HEAD for viewers. Starting runs, launching attacks, resolving escalations,
  voice and the laptop relay need an admin cookie from `/admin` (`ADMIN_KEY`).
- **To lock the site to the team:** restore both `CF_ACCESS_*` variables, detach the bypass policy, then redeploy.
  The origin then rejects any request without a valid Access JWT.

## 8. Known issues

- **render-env's WebSocket default is wrong.** With `DOMAIN` set, `deploy/render-env.sh` defaults
  `NEXT_PUBLIC_WS_URL` to `wss://api.<domain>`, a host Caddy doesn't serve. Prod works only because the variable is
  set explicitly to `wss://app.redledger.us`. Keep it set.
- **`make test-<area>` fails out of the box.** It runs `uv run pytest` without the dev extras, so pytest is missing.
  Run `make install` first, or use `cd <area> && uv run --extra dev pytest -q`.
- **`make lint` dies at frontend `tsc` without `node_modules`.** Run `cd frontend && npm install` first. It also skips
  `npm run lint` and the `check_contracts.py` lint that CI runs, so run those by hand for parity.
- **`.env.example` is incomplete.** It lacks `FP_FLAT_PENALTY`, `HTTP_TIMEOUT_SEC`, `FIXTURES_DIR`, `SCHEMA_PATH` and
  `RED_URL`/`GREEN_URL`/`BLUE_URL`. The defaults in §2 apply.
- **Stale comments:** `docker-compose.prod.yml` mentions an `api.` host and Cloudflare Pages; `frontend/.env.example`
  shows a prod Access team domain (prod's `CF_ACCESS_*` are blank).
- **A gate block caused by blue being unreachable** (fallback) looks the same in the UI as a control block. Don't
  narrate it as a catch.

## 9. Prod runbooks (full detail)

Kept verbatim from the former `deploy/PROD-OPS.md` so nothing operational is lost; §§3–7 above are the summary.

### Going live: red, then blue's audit

Prod today runs red and blue's daily audit on Droid and keeps green keyless: `DRY_RUN=false`,
`DRY_RUN_GREEN=true`, `DRY_RUN_BLUE=false`, `DROID_MODEL_RED` and `DROID_MODEL_BLUE` both
`gpt-5.4-mini`. Red went live first; blue's audit followed on 2026-10-25 after its readiness guard
was lifted (#157; smoke `ep_f9c695b3144f`). Green's `_droid_turn` still raises before starting
Droid, and green stays keyless for the hackathon. Blue's gate LLM also needs `BLUE_GATE_LLM_*`
(provider and API key), which prod leaves unset, so `/gate` stays rules plus learned controls.

1. GitHub `production` environment, **secret**: `FACTORY_API_KEY` (UI or `gh secret set
   FACTORY_API_KEY --env production` in your own terminal; never paste it anywhere else).
2. **Variables**: `DROID_MODEL_RED` and `DROID_MODEL_BLUE` (pinned low-multiplier models, never
   `auto`; see `contracts/CHANGELOG.md` Findings for costs), optional `DROID_REASONING_RED` /
   `DROID_REASONING_BLUE` (e.g. `low`), `DRY_RUN=false`, `DRY_RUN_GREEN=true`,
   `DRY_RUN_BLUE=false`. Keep `MAX_CREDITS_PER_EPISODE` set. (Red only: `DRY_RUN_BLUE=true`.)
3. Run the deploy workflow and approve the `production` gate.
4. Smoke: `make prod-health` (red and blue `dry_run: false`, green `true`), then
   `make prod-episode MODE=enforce SEED=42 DAYS=2`, `make prod-wait EP=…`, `make prod-credits EP=…`.
   Before #176 `prod-credits` showed blue as 0 and blue's `droid_ok` always read false; from the
   deploy containing 6640354 blue's audit credits count and `droid_ok` is truthful.

Going back: set `DRY_RUN_BLUE=true` (blue keyless) or `DRY_RUN=true` (everything keyless) and redeploy.


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

### Record the demo fixtures (off vs enforce, same seed)

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

### Blue's CRS scenario (`make prod-crs-episode`)

```bash
make prod-crs-episode SEED=42            # DAYS defaults to 2 (allowed 2-30)
make prod-crs-episode SEED=42 DAYS=3
```

`SEED` is required: it's a live run that spends credits, so it never starts on defaults. The script
(`deploy/prod.sh crs-episode`, #197) mirrors `blue/tests/crs_episode_acceptance.py`:

1. Refuses if another episode or lineage is running (one run at a time).
2. Creates an `enforce` episode and doesn't start it, so it only advances by `/step`.
3. Seeds `battlefield/fixtures/crs-personas.json` through the operator fixtures route.
4. Binds the three persona employees, found by exact name, to P01/P12/P16 through blue's operator
   extension (`PUT /api/x/blue/crs/episodes/{ep}/employees/{emp}`).
5. Steps day 0, adds one more expense per persona while paused, then steps the remaining days.
6. Prints a JSON summary (per persona: flags and expense statuses; P12/P01/P16 day-1 gate verdicts;
   blue's `crs_identity_check` calls and result counts by day; reports posted; blue credits; notes)
   and a last line `crs-episode <ep>: PASS` or `FAIL: <reasons>`.

PASS means P12 has a high-severity flag, P12's day-1 expense got a block verdict naming
`already_flagged_high` and wasn't paid, and every P01 and P16 expense was paid. Notes don't fail the
run but say what to look at: no `crs_identity_check` call, no blue credits (the audit ran keyless),
fewer reports than days, or P12's day-0 expense unpaid.

Exit codes:

| Code | Meaning |
|---|---|
| 0 | PASS |
| 2 | FAIL; the summary's `fail_reasons` say why |
| 3 | busy: another run is active, nothing was created |
| 1 | a step failed; stderr names the step and the episode id. Nothing is deleted: inspect with `make prod-score` / `make prod-credits EP=…` |

It needs blue's live audit (`DRY_RUN_BLUE=false`; a keyless audit never calls CRS) and the CRS
credentials (`CRS_USERNAME`, `CRS_PASSWORD`) as `production` environment secrets
(`deploy/ENVIRONMENT.md`). Without them every check comes back unknown and the run FAILs. Blue logs
in to CRS once per process and never retries (`blue/CRS.md`): if a run FAILs with all-unknown CRS
result counts after an earlier run worked, suspect the login: a failed or expired token needs a blue restart,
not a re-run loop. Red's and blue's turns are live, so it costs credits (blue's audit was 3,985 and
5,318 in ep_9cbc3362d44e).

First pass on prod: ep_9cbc3362d44e, 2026-10-25, `SEED=42 DAYS=2` (`blue/CRS.md`, "Prod live-audit
acceptance"; recording `recordings/crs-live-ep_9cbc3362d44e.jsonl`). Record a run like any other
with `make prod-record EP=… NAME=…`.

### Credit cap (`MAX_CREDITS_PER_EPISODE`)

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

### Running an evolution on prod (lineages)

A lineage is a chain of headless generations (ARCHITECTURE.md, Evolution); on prod every live agent
turn and every `/reflect` costs Factory credits, so `prod-evolve` refuses to start without a
lineage cap. Same token-free channel as the episode targets: everything runs inside battlefield on
the VM.

```bash
make prod-health                          # which agents are live (dry_run false)
LN=$(make -s prod-evolve GENS=3 DAYS=5 MODE=enforce SEED=42 MAX_CREDITS=1000000)   # [REVEAL_DAYS= REVEAL_GENERATIONS=]
make prod-lineage-wait LN=$LN             # progress on stderr (deploy/prod.sh lineage-wait exits 0/3/124; make reports a failure as 2)
make prod-lineage-status LN=$LN           # per generation: seed, day, status, score, turn credits
make prod-lineage-pause LN=$LN            # / prod-lineage-resume (also lifts a lineage credit-cap pause)
make prod-evolution-report LN=$LN         # runs/$LN/report.json + report.md (partial while it runs)
make prod-lineage-export LN=$LN [GEN=2]   # runs/$LN/{lineage.json,playbooks/,gen-<g>/...}
```

- **No defaults on prod:** `GENS`, `DAYS`, `MODE`, `SEED` and `MAX_CREDITS` must be given. `MAX_CREDITS`
  becomes `config.max_credits` (whole lineage, turns + reflections); `MAX_CREDITS_PER_EPISODE` still
  caps each generation. Rough cost with red live and green/blue keyless (as in `ln_f52a3df83c8d`): about
  2.7k credits per red turn on `gpt-5.4-mini` (7–9k on earlier models). With blue's audit live, add about
  4k per day (3,806 and 4,109 in smoke `ep_f9c695b3144f`), so a 5-day generation is now roughly 35k
  plus red's reflection.
- **Per-episode cap vs lineage cap:** `MAX_CREDITS_PER_EPISODE` pauses only the generation's episode
  (the lineage stays `running`); `prod-lineage-wait` exits 3 naming it. Lift it with
  `make prod-resume EP=<ep>`, not `prod-lineage-resume`. The lineage cap (`MAX_CREDITS`) pauses the
  lineage; lift that with `prod-lineage-resume`.
- **Credits shown are a lower bound:** `prod-lineage-status` sums `turn.ended` credits; `/reflect`
  usage counts toward the cap but isn't in those events.
- **Waiting:** `PROD_LINEAGE_WAIT_TIMEOUT` (7200 s) and `PROD_LINEAGE_WAIT_INTERVAL` (30 s; each poll
  scores every generation on the server). A timed-out wait leaves the lineage running.
- **Ground truth:** the export and the report contain `origin`. They are fetched into a temp dir
  outside the repo, secret-scanned by `battlefield/scripts/evolution_report.py` (a key/token shape
  writes nothing, exits 3, and leaves the fetched JSON quarantined outside the repo, like `record`), and
  written under `runs/` (or `RUNS_DIR`), which ignores itself. `prod-lineage-status` bounds its own
  work (~8 min) and marks credits partial if it runs out.
  Never commit or publish them.
- One lineage runs at a time: `prod-evolve` refuses (exit 3) while another is running. If two
  operators race, the loser's lineage is created but not started (409); it just stays `created`.

### Testing prod.sh without prod

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

## 10. Repo and production environment settings

Kept verbatim from the former `deploy/OWNER-CHECKLIST.md` §§1–2 (checkboxes are historical; the commands are current).

### 1. Repo (10 min)

- [ ] Unzip, `git init`, first commit `chore: scaffold`, push `main`.
- [x] `.github/CODEOWNERS` has real handles (Ad=@md-racc, Al=@Alex-Epstein, M=@moterodiaz, R=@RaagaSundar). It is routing/notification only: owners get auto-requested; it gates nothing.
- [x] ⚑ Branch protection on `main`: require a pull request; **0 approvals; code-owner review off** (integration merges; GIT.md §4);
  require status checks by their real job names: `python (agentkit)`, `python (battlefield)`, `python (red)`, `python (green)`, `python (blue)`, `frontend`, `ownership-guard`, `contracts-guard` (skipped = pass);
  do not allow force pushes; do not allow deletions; **include administrators**.
- [x] Ad's machine only: a local, **uncommitted** removal of the `gh pr merge*` deny in `.claude/settings.json` so the orchestrator can merge (`git update-index --skip-worktree .claude/settings.json`). Never commit it; teammates keep the committed denies.
- [x] Integration loop (AGENTS.md §10, GIT.md §4): PR steward subagent polls and assesses; an independent verifier reviews core/cross-area PRs; merge with `gh pr merge --squash --match-head-commit <assessed sha>`; resync PR branches with plain merges of `origin/main`, never force.
- [ ] Settings → General → Pull Requests: allow **squash merging only**; default to PR title + description; **automatically delete head branches**.
- [ ] Settings → Actions → General: allow GitHub Actions; workflow permissions "Read and write" (deploy.yml pushes to GHCR).
- [ ] Add collaborators Al, M, R with Write (not Admin). You stay the only admin.

### 2. Secrets and variables (10 min)

Images carry no secrets. The deploy job renders `/opt/redledger/.env` on the VM from the
`production` environment on every deploy (`deploy/render-env.sh`); nobody edits that file by hand.

Repo → Settings → Secrets and variables → Actions → **Repository** secrets (deploy plumbing only):
- [ ] `VULTR_HOST`, `VULTR_USER` (`deploy`), `VULTR_SSH_KEY` (private key the VM's `deploy` user accepts). Nothing else at repo level.

Repo → Settings → Environments → **New environment** `production`:
- [ ] ⚑ Deployment protection: **required reviewer = Ad**. Deployment branches: `main` only.
- [ ] Environment **secrets**:
  - `AGENT_TOKEN`, `OPERATOR_TOKEN`: `openssl rand -hex 32` each, two different values (render-env refuses equal or empty tokens).
  - `AGENT_TOKEN_RED`, `AGENT_TOKEN_GREEN`, `AGENT_TOKEN_BLUE` (per-agent tokens, #108/#109): create all three at once — `for a in RED GREEN BLUE; do openssl rand -hex 32 | gh secret set AGENT_TOKEN_$a --env production; done` — then redeploy. All three or none: render-env refuses a partial or duplicate set; none → shared `AGENT_TOKEN` (separation off). Rollback: delete all three and redeploy.
  - `FACTORY_API_KEY`: the dedicated prod key. ⚑ It goes here and nowhere else: not in a teammate's `.env`, not in chat. Each dev uses their own key locally.
  - `BLUE_GATE_LLM_API_KEY`, `CRS_API_KEY`, `CARTESIA_API_KEY` (leave unset if unused).
  - `CRS_USERNAME`, `CRS_PASSWORD`: optional CRS **sandbox** login, entered by a human later.
    Both are `production` environment secrets, forwarded only at runtime to Blue (never shared
    agent env, frontend, or image build args). `CRS_API_KEY` remains legacy compatibility
    plumbing and is unused by the identity client. Leave both login secrets unset when unused;
    missing credentials and `DRY_RUN=true` yield neutral unknown evidence, never a block.
- [ ] Environment **variables**:
  - `DROID_MODEL_RED`, `DROID_MODEL_GREEN`, `DROID_MODEL_BLUE`: pinned prod models (never `auto`).
  - `DROID_REASONING_RED`, `DROID_REASONING_GREEN`, `DROID_REASONING_BLUE`: optional reasoning effort, one of `none|off|minimal|low|medium|high|xhigh|max` (leave unset for the model default). A bad value stops that agent at startup.
  - `BLUE_GATE_LLM_PROVIDER`, `BLUE_GATE_LLM_MODEL`.
  - `MAX_CREDITS_PER_EPISODE`: prod uses `375000` (see §6). Battlefield pauses an episode that reaches it; `0` disables.
  - `DOMAIN`: e.g. `example.com` (Caddy serves `api.` and `app.` under it).
  - (`GITHUB_REPO` is not a variable: GitHub reserves the `GITHUB_` prefix, so deploy.yml passes `github.repository`, the same name the build job tags images with. It must be lowercase for GHCR.)
  - `CORS_ORIGINS`: e.g. `https://app.<domain>,https://<pages-project>.pages.dev` (defaults to `https://app.<domain>`).
  - `NEXT_PUBLIC_WS_URL`: `wss://app.<domain>` on prod (the render-env default `wss://api.<domain>` is wrong; see §8).
- [ ] Repo → Settings → Secrets and variables → Actions → **Repository variables**: `DEPLOY_ENABLED=true`, but only once the VM in §3 is up. Until then merges to `main` build and push images and skip the SSH roll.
- [ ] Rotation = change the secret in the environment, then re-run deploy.yml. Rotating `AGENT_TOKEN`/`OPERATOR_TOKEN` restarts every service with the new value; nothing else to touch.
- [ ] CRS live acceptance: **blocked / not run** until sandbox credentials and runtime tooling
  are available and checks are authorized. Check only pinned approved fictional personas
  (`deploy/ENVIRONMENT.md`); never real PII or an EIN lookup. Container smoke and live Factory
  acceptance are also unavailable here; Blue's live SDK guard stays disabled. Do not mark the
  integration live-ready based only on credential wiring or unit tests.
