# ENVIRONMENT.md — credentials and environment refactor (agent brief)

> **Status (2026-10-24):** implemented on branches `contracts/env-tokens`, `battlefield/env-tokens`,
> `frontend/env-proxy`, `docs/env`. Where the code differs from this spec, the code (and
> `contracts/`) wins:
> - `GET /api/events` is operator-only (agents get 403), enforcing `AGENTS.md` invariant 11.
>   The two-token rule became `AGENTS.md` invariant **12** (11 was already taken).
> - The deploy `roll` job runs only when the repo variable `DEPLOY_ENABLED` is `true`; until then
>   merges build and push images and skip the SSH roll.
> - `docker-compose.prod.yml` fails closed: compose refuses to start if `AGENT_TOKEN` /
>   `OPERATOR_TOKEN` are unset, instead of falling back to the base file's `change-me` defaults.
> - `GITHUB_REPO` is not an environment variable: GitHub reserves the `GITHUB_` prefix, so
>   `deploy.yml` passes `github.repository` (the same name the build job tags images with).
> - `/api/bf/ws-ticket` returns `{ticket, expires_at, ws_url}`; `ws_url` is `NEXT_PUBLIC_WS_URL`
>   read at request time on the server, so one frontend image serves every environment
>   (`lib/ws.ts` does not read `NEXT_PUBLIC_WS_URL` itself).
> - The frontend proxy refuses cross-site mutations (`Sec-Fetch-Site: cross-site` → 403) and
>   forwards only `content-type`/`accept`; the browser's `Authorization`, cookies and `X-*` never
>   reach battlefield.

Owner: Dev Ad. Hand this file to an orchestrator agent working in the Red Ledger repo. It is a
complete task spec: goal, target state, file-by-file work split into PRs, acceptance checks.
Read `AGENTS.md` (§10 especially), `GIT.md`, and `README.md` §§0, 13, 16, 17 before planning.

---

## 1. Goal

1. **Images carry no secrets and no environment-specific values.** One build serves every
   environment; credentials arrive at container start from the host's `.env`.
2. **One source of truth for prod credentials:** a GitHub Environment named `production`. The
   deploy job renders `/opt/redledger/.env` on the VM from it. Nobody edits the VM's `.env` by
   hand.
3. **The browser never holds a write-capable token.** Today `NEXT_PUBLIC_INTERNAL_TOKEN` is
   compiled into the frontend bundle, so anyone loading the page can act as an agent. Fix that.
4. **Split the single `INTERNAL_TOKEN` into two scopes** so a frontend compromise cannot
   impersonate red/green/blue.
5. **Separate Factory credit pools.** Each dev uses their own Factory key locally; prod uses a
   dedicated key that only exists in the `production` environment. Add a per-episode credit
   ceiling so a runaway loop can't drain prod before judging.

## 2. Target state

### Tokens

| Token | Who holds it | What it authorizes |
|---|---|---|
| `AGENT_TOKEN` | battlefield, red, green, blue containers | Agent routes (any request carrying `X-Agent`), battlefield → agent `/turn` `/gate` `/audit` `/schemes`, green → blue `/gate` mirror |
| `OPERATOR_TOKEN` | battlefield, frontend **server** (Next route handler), Makefile/curl, the owner | Control plane, `/api/fe/*`, `/api/events` reads, `/api/inputs`, `/api/ws/ticket` |
| WS ticket | browser, ≤60 s lifetime | One WebSocket connection for one episode |
| none | anyone | `battlefield/extensions/fe_*` routes deliberately marked public |

Rules battlefield enforces:
- A request with `X-Agent` must present `AGENT_TOKEN`. `OPERATOR_TOKEN` + `X-Agent` → 401.
- A request without `X-Agent` must present `OPERATOR_TOKEN`. `AGENT_TOKEN` without `X-Agent` → 401.
- `/api/ws` accepts `?ticket=` (HMAC-signed with `OPERATOR_TOKEN`, payload `{episode_id|*, exp}`), or `?token=<OPERATOR_TOKEN>` for curl/debug.

Compatibility: `AgentSettings.internal_token` keeps its attribute name but reads
`AGENT_TOKEN` first, falling back to `INTERNAL_TOKEN` (pydantic `AliasChoices`). Battlefield's
`Settings` gets `agent_token` and `operator_token`, each falling back to `INTERNAL_TOKEN` if
unset, and logs a warning when the two are equal. **This is what keeps `red/`, `green/`, `blue/`
untouched:** they already read `settings.internal_token` and keep working.

### Frontend

- New server-side proxy `frontend/app/api/bf/[...path]/route.ts`: forwards GET/POST/PUT/PATCH/DELETE
  to `${BATTLEFIELD_URL}/api/<path>` with `Authorization: Bearer ${OPERATOR_TOKEN}`, streams the
  body back, copies the status and content-type. `BATTLEFIELD_URL` and `OPERATOR_TOKEN` are
  **server** env vars (no `NEXT_PUBLIC_` prefix), read at request time, never at build time.
- New `frontend/app/api/bf/ws-ticket/route.ts`: `GET ?episode_id=` → calls battlefield
  `POST /api/ws/ticket` with the operator token, returns `{ticket, ws_url}`.
- `lib/api.ts`: base becomes same-origin `/api/bf`; remove token handling.
- `lib/ws.ts`: fetch a ticket, connect to `${NEXT_PUBLIC_WS_URL}/api/ws?episode_id=&ticket=&after_id=`;
  on reconnect fetch a new ticket.
- `NEXT_PUBLIC_MOCK=true` path unchanged and still works with zero backend and zero env.
- Remove `NEXT_PUBLIC_INTERNAL_TOKEN` and `NEXT_PUBLIC_BATTLEFIELD_URL` everywhere.
  `NEXT_PUBLIC_WS_URL` stays (a URL, not a secret).
- Public crowd routes: the browser may call `${NEXT_PUBLIC_WS_URL→https}/api/x/fe/...`
  directly, or go through the proxy. Either works, because those routes need no token.

### Credentials by environment

| Variable | Local dev (each dev's own `.env`) | Prod (GitHub Environment `production` → VM `.env`) |
|---|---|---|
| `AGENT_TOKEN`, `OPERATOR_TOKEN` | any two different strings | `openssl rand -hex 32` each, secrets |
| `FACTORY_API_KEY` | **the dev's own key** (R and Al confirmed; M and Ad same pattern) or empty with `DRY_RUN=true` | prod key from the second source; secret |
| `DROID_MODEL_RED/GREEN/BLUE` | a Droid Core / low-multiplier model | pinned prod models; variables |
| `DROID_REASONING_RED/GREEN/BLUE` | blank (model default) or `none\|off\|minimal\|low\|medium\|high\|xhigh\|max` | optional; variables (a bad value stops that agent at startup) |
| `BLUE_GATE_LLM_PROVIDER/_MODEL` | optional | variables |
| `BLUE_GATE_LLM_API_KEY`, `CRS_API_KEY`, `CARTESIA_API_KEY` | own keys or empty | secrets |
| `CRS_USERNAME`, `CRS_PASSWORD` | own sandbox login or both empty | optional environment secrets; passed only to Blue at runtime |
| `MAX_CREDITS_PER_EPISODE` | `0` (disabled) | e.g. `40`; variable |
| `DOMAIN`, `GITHUB_REPO`, `CORS_ORIGINS` | n/a | variables |
| `DATABASE_URL`, `POSTGRES_*` | compose default | compose default (Postgres not exposed) |

GitHub Actions *repository* secrets keep only the deploy plumbing: `VULTR_HOST`, `VULTR_USER`,
`VULTR_SSH_KEY`. Everything the app reads lives in the `production` *environment*, which
requires reviewer approval (Ad).

### CRS sandbox credentials (runtime prerequisite)

The CRS identity client uses `CRS_USERNAME` and `CRS_PASSWORD`, not `CRS_API_KEY`.
A human may later add both as **secrets in the GitHub `production` environment**, never
repository variables, build args, `NEXT_PUBLIC_*` values, or values committed to the repo.
The SSH roll step forwards both to `deploy/render-env.sh`; its existing safe `emit` function
writes them single-quoted into the mode-600 runtime file. Compose supplies them only to Blue,
not the shared agent environment, battlefield, or frontend. The legacy `CRS_API_KEY` plumbing
remains for compatibility but is obsolete for this client.

The client logs in at `https://api-sandbox.stitchcredit.com/api/users/login` and uses
`/transunion/identity-manager-verification/basic` only for pinned, approved fictional personas.
This is identity verification, not a vendor EIN lookup; the public API has no EIN business
endpoint. Missing credentials or `DRY_RUN=true` produce neutral unknown evidence, never a
verification-based block. Leave the credentials unset when unused.

This prerequisite does not provision credentials, enable Blue's disabled live SDK path, or
establish live acceptance. Live CRS login/persona checks, container smoke, and live Factory
acceptance remain **blocked / not run** until authorized credentials and tooling are available.
Do not print rendered values or response tokens during those later checks.

### Credit guard

`battlefield/app/orchestrator/runner.py`: after each `_turn`, sum `factory_credits` from this
episode's `turn.ended` events (or keep a running total on `EpisodeState`). If
`MAX_CREDITS_PER_EPISODE > 0` and the total reaches it: pause the episode and emit
`error {where: "credit_guard", message: "episode paused at <n> credits (limit <m>)"}`. A human
resumes it explicitly. Agents in `DRY_RUN` report `None` credits; treat that as 0.

## 3. Work split (PRs in this order; one orchestrator, subagents per AGENTS.md §10)

Each PR is its own branch and worktree. No two subagents edit the same file. Merge each PR
before starting the next one that depends on it.

### PR 1 — `contracts/env-tokens` (reviewers: all four devs)

Files:
- `contracts/agent-service.md`: replace "Bearer $INTERNAL_TOKEN" with `AGENT_TOKEN`; add the token table above.
- `contracts/ledger-api.yaml`: two security schemes (`agentBearer`, `operatorBearer`), mark routes; add `POST /ws/ticket {episode_id?} → {ticket, expires_at}`; `/ws` takes `ticket` or `token`.
- `contracts/events.md`: document the `error` event's `where: "credit_guard"` case.
- `contracts/CHANGELOG.md`: one entry.

### PR 2 — `battlefield/env-tokens` (reviewer: Ad)

First, `.github/workflows/ci.yml` ownership-guard: add `deploy/` and `ruff.toml` to the
`battlefield` prefix's ALLOWED regex. This PR needs them and they belong to Ad.

Subagent A (auth + config):
- `battlefield/app/config.py`: `agent_token`, `operator_token` with `INTERNAL_TOKEN` fallback; `max_credits_per_episode: float = 0`; warn if tokens equal.
- `battlefield/app/auth.py`: enforce the two rules in §2; `bearer` → operator-only; `caller` checks agent token when `X-Agent` is present.
- `battlefield/app/api/events_api.py`: `POST /api/ws/ticket` (operator), HMAC-SHA256 over `episode_id|exp` with `operator_token`, 60 s TTL; `/ws` accepts `ticket` or `token`.
- `battlefield/app/orchestrator/agents.py`: outbound headers use `agent_token`.
- `battlefield/app/gate/gatekeeper.py`: outbound call to blue uses `agent_token`.
- `battlefield/tests/test_auth.py` (new): operator token + `X-Agent` → 401; agent token without `X-Agent` → 401; valid/expired/wrong-episode ticket cases. Use FastAPI `TestClient` and stub the DB dependency, or mark DB-needing tests with `@pytest.mark.db` and skip without `DATABASE_URL`.

Subagent B (agentkit + mocks):
- `agentkit/agentkit/config.py`: `internal_token` alias `AliasChoices("AGENT_TOKEN", "INTERNAL_TOKEN")`.
- `agentkit/tests/test_models.py`: add a test for the alias precedence.
- `battlefield/mock_agents/server.py`: no code change needed if it uses `AgentSettings`; verify.

Subagent C (orchestrator credit guard):
- `battlefield/app/orchestrator/runner.py`: guard as specified.
- `battlefield/tests/test_credit_guard.py` (new): pure-function test of the threshold logic (factor the check into a function that takes totals and returns pause/no-pause).

Subagent D (deploy + config surface):
- `docker-compose.yml`: replace `INTERNAL_TOKEN` with `AGENT_TOKEN` in `x-agent-env` and battlefield; add `OPERATOR_TOKEN` and `MAX_CREDITS_PER_EPISODE` to battlefield; frontend service gets `BATTLEFIELD_URL=http://battlefield:8000`, `OPERATOR_TOKEN`, `NEXT_PUBLIC_WS_URL` (runtime env, not build args).
- `docker-compose.prod.yml`: no secrets; confirm nothing reintroduces build args.
- `.env.example`: new variables with comments; delete `INTERNAL_TOKEN` (fallback still works for stale local files). Add the comment "each dev uses their own FACTORY_API_KEY locally".
- `frontend/.env.example`: belongs to R; **do not edit here**. Note it for PR 3.
- `Makefile`: `TOKEN` reads `OPERATOR_TOKEN` from `.env`.
- `deploy/render-env.sh` (new): reads the variables listed in §2 from its environment, writes `.env` atomically (`umask 077`, write to temp, `mv`), refuses to write if `AGENT_TOKEN == OPERATOR_TOKEN` or either is empty, never echoes values.
- `.github/workflows/deploy.yml`:
  - `roll` job: `environment: production`.
  - Pass every runtime variable to `appleboy/ssh-action` via `env:` + `envs:`.
  - The script runs `deploy/render-env.sh` before `compose pull/up`.
  - Remove the frontend `build-args` block entirely.
  - The `build` job stays environment-free; it never sees app secrets.
- `deploy/bootstrap.sh`: stop generating `INTERNAL_TOKEN`; the first deploy renders `.env`. Keep the `GITHUB_REPO`/`DOMAIN` lines or move them to environment variables.
- `deploy/OWNER-CHECKLIST.md` §2–§3: rewrite for the `production` environment (create it, set required reviewer = Ad, list of secrets vs variables per §2, the prod Factory key goes here and nowhere else).

### PR 3 — `frontend/env-proxy` (reviewer: R; Ad co-reviews)

Single subagent. Files:
- `frontend/app/api/bf/[...path]/route.ts` (new)
- `frontend/app/api/bf/ws-ticket/route.ts` (new)
- `frontend/lib/api.ts`, `frontend/lib/ws.ts`
- `frontend/app/page.tsx`: only if it references removed env vars.
- `frontend/Dockerfile`: drop the `ARG NEXT_PUBLIC_*` line except `NEXT_PUBLIC_WS_URL` and `NEXT_PUBLIC_MOCK` if needed at build; prefer runtime.
- `frontend/.env.example`: `BATTLEFIELD_URL`, `OPERATOR_TOKEN`, `NEXT_PUBLIC_WS_URL`, `NEXT_PUBLIC_MOCK`.
- `frontend/AGENTS.md`, `frontend/FRONTEND-API.md`: document the proxy (`/api/bf/*` mirrors `/api/*`), the ticket flow, and "never put a token in a `NEXT_PUBLIC_` var".
- `frontend/lib/proxy.test.ts` (new, optional): unit-test the path/header rewrite logic if it's factored out.

Note: `NEXT_PUBLIC_*` values are inlined at build time; `process.env.X` in a route handler is
read at runtime only when the route is dynamic. Export `const dynamic = "force-dynamic"` from
both route files.

### PR 4 — `docs/env` (reviewer: Ad)

- `README.md` §11 (point at `.env.example` + this file's table), §13 (token scopes, proxy), §17 (environment-based deploy, render step, rollback unchanged).
- `AGENTS.md` invariant 9: secrets live in local `.env` or the `production` environment, never in images, never in `NEXT_PUBLIC_*`; add invariant 11 for the two-token rule.
- `red/AGENTS.md`, `green/AGENTS.md`, `blue/AGENTS.md`: one line each under "Local loop": `AGENT_TOKEN` replaces `INTERNAL_TOKEN`; use your own `FACTORY_API_KEY`. These are doc-only edits in other owners' directories. Allowed on a `docs/` branch, but tag Al and M.
- Move this file to `deploy/ENVIRONMENT.md` and link it from README §17.
- `DEVLOG.md`: one line per PR (orchestrator writes them as Ad).

## 4. Acceptance checks (verifier subagent runs all of these)

1. `make lint test` passes.
2. `grep -rn "NEXT_PUBLIC_INTERNAL_TOKEN\|NEXT_PUBLIC_BATTLEFIELD_URL" .` → no hits outside CHANGELOG/DEVLOG history.
3. `grep -rn "INTERNAL_TOKEN" --include=*.py --include=*.yml --include=*.ts .` → hits only in the documented fallback aliases.
4. `docker build -f battlefield/Dockerfile .` and `docker build frontend/` succeed with **no** `.env` present and no build args. `docker history --no-trunc` on each image shows no token or key values.
5. `make mock-agents` with `AGENT_TOKEN=a OPERATOR_TOKEN=o` → `make episode MODE=enforce DAYS=2` completes; score has ≥1 attack caught.
6. With the stack up, both must return 401:
   - `curl -H "Authorization: Bearer o" -H "X-Agent: red" -H "X-Episode: x" -H "X-Day: 0" localhost:8000/api/vendors`
   - `curl -H "Authorization: Bearer a" localhost:8000/api/episodes`
7. Frontend against the stack: `OPERATOR_TOKEN=o BATTLEFIELD_URL=http://localhost:8000 NEXT_PUBLIC_WS_URL=ws://localhost:8000 npm run dev`. Creating an episode and seeing live events works. In the browser's devtools, no request carries `Authorization`, and the built JS (`.next/static`) contains neither token (`grep -r "o\b"` is useless here; grep for a distinctive test token like `OPTEST123`).
8. `NEXT_PUBLIC_MOCK=true npm run dev` with an empty env still replays the fixture.
9. Credit guard: set `MAX_CREDITS_PER_EPISODE=0.001` and fake a `turn.ended` with `factory_credits: 1` (unit test); the episode pauses and emits `error` with `where: credit_guard`.
10. `deploy/render-env.sh` with `AGENT_TOKEN=x OPERATOR_TOKEN=x` exits non-zero and writes nothing.
11. `deploy.yml` passes `actionlint` (`docker run --rm -v $PWD:/repo -w /repo rhysd/actionlint`).

## 5. Out of scope

- Any change inside `red/`, `green/`, `blue/` source code (the alias fallback makes it unnecessary).
- Secrets managers other than GitHub Environments.
- Per-user auth on the frontend. Cloudflare Access in front of `app.` and `api.` covers the weekend.
- Rotating keys already shared in chat. Ad does that by hand after PR 2 lands.

## 6. When to stop and ask Ad

- Any test on `main` fails before you start.
- The proxy can't stream an endpoint correctly (e.g. something large or chunked); report which one.
- Anything would require editing a non-doc file in `red/`, `green/`, `blue/`.
- `appleboy/ssh-action` cannot pass a variable cleanly (multiline, special characters). Report it. Do not base64-hack secrets into logs.
