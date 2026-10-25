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
