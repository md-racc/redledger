# Red Ledger

Adversarial sandbox for autonomous finance. A synthetic small business runs through simulated
business days while three agents operate on the same ledger: a red-team agent commits fraud, a
finance-ops agent does legitimate work, and a controller agent gates every money-moving action
and audits the books. Every action is logged, every verdict is explained, and a scoreboard
tracks dollars extracted vs. blocked and the cost of false positives.

Cal Hacks 13.0. Primary tracks: Hyphenate (Autonomous Systems for Finance), Factory (Droid SDK).
Secondary: Armadin, CRS, Tiger Data, Vultr, Figma, MLH Gemini. Sponsor integration status,
ownership and build order: `INTEGRATIONS.md` (temporary, deletes itself when the work is done).

Repo owner: start with `deploy/OWNER-CHECKLIST.md`. Everyone else: your directory's `AGENTS.md`.

This README is the architecture source of truth. `AGENTS.md` is the working agreement,
`GIT.md` the git protocol, `DEVLOG.md` the shared progress ledger, `contracts/` the
machine-readable truth that wins any disagreement with prose. Each service directory has its
own `AGENTS.md` written for the developer who owns it.

---

## 0. Who owns what

| Dev | Directory | Responsibility |
|---|---|---|
| **Ad** (repo owner) | `battlefield/`, `agentkit/`, `contracts/`, compose, Makefile, CI, deploy | The center spoke: Ledger API, gatekeeper, orchestrator, event bus, scoring, mock agents, frontend read API, hosting |
| **Al** | `red/` | Attacker: scheme catalog, red tools, red Droid session |
| **M** | `green/`, `blue/` | Finance-ops agent (gated AP workflow, Droid permission-handler mirror) and controller (gate rules + LLM, audit Droid session). Also tunes seed/legit-traffic realism via PRs to Ad |
| **R** | `frontend/` + presentation | Everything a judge sees: dashboard, demo choreography, pitch deck. Consumes the event stream and `/api/fe` |

Branch prefixes match directories (`GIT.md` §1). CI blocks a PR that touches files outside its
branch's area.

---

## 1. System overview

```
                         ┌─────────────────────────────┐
   browser ──HTTPS/WS──▶ │  frontend  (Next.js)        │   Dev R
                         └──────────────┬──────────────┘
                                        │ REST + WebSocket (edge: HTTPS/WSS)
                                        ▼
┌───────────────────────────────────────────────────────────────────────┐
│  battlefield  (FastAPI)                                   Dev Ad      │
│  • Ledger API      — the only way to read/write the books             │
│  • Orchestrator    — runs the clock: one tick = one business day       │
│  • Gatekeeper      — routes green's mutations through blue             │
│  • Event bus       — append-only events table + WS broadcast           │
│  • Scorekeeper     — $ extracted / blocked, latency, false positives   │
│  • /api/fe         — derived read views for the frontend               │
└──────┬─────────────────────┬─────────────────────┬────────────────────┘
       │ POST /turn          │ POST /turn          │ POST /gate, /audit     (internal: plain HTTP)
       ▼                     ▼                     ▼
  ┌─────────┐          ┌───────────┐         ┌───────────┐
  │   red   │ Dev Al   │   green   │ Dev M   │   blue    │ Dev M
  │ Droid   │          │ Droid     │         │ rules+LLM │
  │ session │          │ session   │         │ + Droid   │
  └─────────┘          └───────────┘         └───────────┘
       │                     │                     │
       └──── all ledger reads/writes go back through battlefield ─────┘

                         ┌─────────────┐
                         │  postgres   │  (only battlefield connects)
                         └─────────────┘
```

Five containers plus Postgres. Agent containers never touch the database. They call
battlefield's Ledger API over HTTP with an `X-Agent` header, and battlefield decides what each
agent may do. That single choke point is what makes the controller story true and what lets
four people build in parallel against one contract.

**Transport.** Yes, every team is a separate container. Inside the Docker network they speak
plain HTTP to each other (`http://battlefield:8000`, `http://blue:8003`); there is no reason
to terminate TLS between containers on one host. HTTPS/WSS exists only at the public edge
(browser → battlefield, browser → frontend), terminated by Caddy or Cloudflare. Agents
authenticate to battlefield with `AGENT_TOKEN`; the operator and the frontend server use a
separate `OPERATOR_TOKEN` (§13).

### Why this shape

- **One enforcement point.** Fraud is caught where money moves: the Ledger API. Blue's verdict
  is consulted there. Green's Droid permission handler mirrors the same verdict for the
  Factory-native demo, but the ledger is the source of truth.
- **Agents are black boxes to each other.** Red, green, and blue share only the ledger. They
  never call each other (one exception: green's permission handler → blue `/gate`). The
  orchestrator sequences them. Each team owns one container end to end and honors two
  contracts: the Ledger API and the `/turn` endpoint.
- **Ground truth is hidden.** Battlefield tags red-originated rows with `origin='red'`
  internally and strips provenance from every response to an agent. Scoring uses it; agents
  can't.
- **Everything is replayable.** Every event is persisted. A recorded episode replays to the
  frontend with no agents running: stage fallback and frontend dev fixture.

---

## 2. Containers

| Service       | Tech                                     | Port | Owner | Talks to                        |
|---------------|------------------------------------------|------|-------|---------------------------------|
| `battlefield` | Python 3.11, FastAPI, asyncpg            | 8000 | Ad    | postgres, red, green, blue      |
| `red`         | Python 3.11, Droid SDK, FastAPI          | 8001 | Al    | battlefield                     |
| `green`       | Python 3.11, Droid SDK, FastAPI          | 8002 | M     | battlefield, blue (mirror gate) |
| `blue`        | Python 3.11, Droid SDK + direct LLM API  | 8003 | M     | battlefield                     |
| `frontend`    | Next.js 15, TypeScript, Tailwind         | 3000 | R     | battlefield                     |
| `postgres`    | Postgres 16 (Timescale image optional)   | 5432 | Ad    | —                               |

Shared Python package `agentkit/` (Ad; imported by red/green/blue): `LedgerClient`,
`EventEmitter`, `DroidAgent` base, `make_agent_app`, and the pydantic models mirroring
`contracts/`. The center spoke in code form.

---

## 3. Simulation model

- **Company:** Coastal Supply Co. ~40 employees, ~60 vendors. Seeded with 90 days of clean
  history (POs, invoices, payments, payroll, bank feed, GL) from a deterministic `seed`.
- **Episode:** one run with a fixed `controller_mode` and seed. Default 10 business days.
  Controller-off and controller-on demos are two episodes with the same seed.
- **Day (tick):** orchestrator runs, in order:
  1. inject scripted legitimate traffic (new POs, invoices, expenses, bank lines)
  2. `POST red/turn` — red picks (or is told) a scheme and executes it
  3. `POST green/turn` — green works the AP queue; every mutation goes through the gate
  4. `POST blue/audit` — blue runs periodic audit, may flag/freeze, posts a report
  5. resolve attack outcomes, compute score, emit `day.ended`
- **Controller modes:**
  - `off` — gate never consulted.
  - `shadow` — gate consulted, verdicts recorded with `enforced=false`, nothing blocked.
  - `enforce` — `block` → 403 to the agent; `escalate` → waits for a human decision.
- **Escalation:** blue returns `escalate`; battlefield opens an escalation, emits an event, and
  holds the mutation up to `ESCALATION_TIMEOUT_SEC` (90) for `POST /escalations/{id}/resolve`.
  Timeout = block.

---

## 4. Data model (summary — `contracts/schema.sql` is canonical)

All rows carry `episode_id`. Provenance: `origin ∈ sim | red | green | blue`; red rows also
carry `attack_id`. Both are stripped from agent responses.

| Table | Purpose | Key columns |
|---|---|---|
| `episodes` | one run | id, seed, controller_mode, days, status, current_day, attack_plan |
| `vendors` | counterparties | id, name, ein, bank_account, bank_routing, category, created_day, status(active/frozen), origin |
| `vendor_changes` | requests to change vendor details (bank swaps) | id, vendor_id, field, old_value, new_value, requested_day, status, origin |
| `employees` | payroll population | id, name, role, salary, bank_account, start_day, status, hr_record, origin |
| `purchase_orders` | approved spend | id, vendor_id, amount, created_day, status |
| `invoices` | bills | id, vendor_id, po_id?, amount, invoice_number, received_day, due_day, status(pending/matched/approved/paid/rejected/blocked), status_day, origin, attack_id |
| `payments` | money out | id, invoice_id?, expense_id?, amount, to_account, paid_day, paid_by, origin_of_source |
| `expenses` | reimbursements | id, employee_id, amount, category, submitted_day, status, origin, attack_id |
| `bank_transactions` | bank feed | id, day, amount, counterparty, memo, matched_payment_id |
| `gl_entries` | general ledger | id, day, account, debit, credit, memo, posted_by, ref_type, ref_id |
| `attacks` | red's declared attempts (ground truth) | id, scheme_id, display_name, story, day_launched, params, target_amount, outcome, amount_extracted, detected_day |
| `verdicts` | every gate decision | id, idempotency_key, day, agent, action, entity_type, entity_id, amount, verdict, reason, confidence, rules_fired, enforced, latency_ms |
| `escalations` | human-in-the-loop queue | id, verdict_id, status, expires_at, resolved_by |
| `flags` | blue's suspicions | id, day, entity_type, entity_id, severity, reason, raised_by |
| `reports` | end-of-day controller reports | id, day, markdown |
| `audit_log` | every agent call | ts, agent, action, tool_use_id, args, result, http_status, verdict_id |
| `events` | everything the frontend sees | id, ts, day, type, agent, payload |

Scoring (`battlefield/app/scoring/score.py`, emitted as `score.updated`):

- `dollars_extracted` = Σ payments whose source has `origin='red'`
- `dollars_blocked` = Σ red-origin invoice/expense amounts blocked or rejected, plus red invoices whose vendor was frozen before payment
- `false_positive_cost` = Σ legit amounts blocked × `FP_PENALTY_RATE` + (legit blocks + legit escalations) × `FP_FLAT_PENALTY`
- `detection_latency_days` = mean(detected_day − day_launched) over detected attacks
- `attacks_caught / attacks_launched`, `legit_blocked`, `legit_processed`

---

## 5. Ledger API — `contracts/ledger-api.yaml` is canonical; live docs at `/docs`

Base `http://battlefield:8000/api`. Every request: `Authorization: Bearer <token>`, where the
token is `AGENT_TOKEN` for agents (requests with `X-Agent`) and `OPERATOR_TOKEN` for the
operator / frontend server (no `X-Agent`); the wrong token for the role is a 401 (§13).
Agent requests also carry `X-Agent`, `X-Episode`, `X-Day`, and on writes `X-Tool-Use-Id`
(the idempotency key). Battlefield 403s any agent calling a route it isn't allowed.
`GET /events` is operator-only: agents emit events, they never read them (`AGENTS.md` inv. 11).

| Group | Routes | Who |
|---|---|---|
| Reads | `GET /vendors /vendors/{id} /vendor_changes /employees /purchase_orders /invoices /invoices/{id} /payments /expenses /bank/transactions /gl/entries /reports/{id}`; `GET /flags` (green, blue); `GET /audit_log` (blue); `GET /attacks` (red) | agents + operator |
| Red writes | `POST /attacks` (declare before executing), `PATCH /attacks/{id}`, `POST /vendors /vendor_changes /invoices /expenses /employees` | red |
| Green writes (gated) | `POST /invoices/{id}/match\|approve\|reject\|pay`, `/vendor_changes/{id}/approve\|reject`, `/expenses/{id}/approve\|pay`, `POST /gl/entries` | green |
| Blue writes | `POST /flags`, `/vendors/{id}/freeze\|unfreeze`, `/reports` | blue |
| Events (write) | `POST /events` (agents: `agent.*` and `x.*` only) | agents |
| Events (read) | `GET /events?episode_id=&after_id=`, `POST /ws/ticket {episode_id?}` → `{ticket, expires_at}`, `WS /ws?episode_id=&ticket=&after_id=` (or `&token=<OPERATOR_TOKEN>` for curl) | operator only |
| Control plane | `POST /episodes`, `GET /episodes[/{id}]`, `/episodes/{id}/start\|pause\|resume\|step`, `GET /episodes/{id}/score`, `PATCH /episodes/{id}/controller`, `POST /episodes/{id}/attack`, `GET /schemes`, `GET /escalations`, `POST /escalations/{id}/resolve`, `GET /replays`, `POST /replays/{id}/play`, `GET /health` | operator / frontend server |
| Frontend read API | `GET /fe/episodes/{ep}/snapshot \| timeline \| ap_aging \| entities/{type}/{id} \| vendors \| attacks \| attacks/leaderboard \| verdicts \| verdicts/rules \| verdicts/confusion \| agents/activity \| agents/{agent}/thinking \| feed \| search \| reports \| escalations`, `GET /fe/compare?a=&b=` | operator / frontend server (browser via `/api/bf/*`); see `frontend/FRONTEND-API.md` |

Gated routes return `403 {verdict:"block", reason, verdict_id}` on block, or hold for the
escalation then return 200 or 403. In `shadow` they succeed and record the verdict anyway.

---

## 6. Agent service contract — `contracts/agent-service.md` is canonical

Every agent: `GET /health`, `POST /turn {episode_id, day, controller_mode, options}` →
`{ok, summary, duration_sec, usage}` within `TURN_TIMEOUT_SEC`. Agents narrate via
`POST /events` (`agent.thinking`, `agent.tool_call`, `agent.tool_result`). Red adds
`GET /schemes`. Blue adds `POST /gate` (≤ `GATE_TIMEOUT_SEC`, idempotent on key for 120 s) and
`POST /audit`. All three must run under `DRY_RUN=true` with no model calls.

---

## 7. Events — `contracts/events.md` is canonical

Envelope `{id, ts, episode_id, day, type, agent, payload}`. Types: `episode.*`,
`controller.changed`, `day.*`, `turn.*`, `attack.launched|outcome`, `agent.thinking|tool_call|tool_result`,
`ledger.mutation`, `gate.verdict`, `escalation.opened|resolved`, `flag.raised`,
`vendor.frozen|unfrozen`, `report.posted`, `score.updated`, `error`. Frontend renders from
events plus `/api/fe`; it never reads ledger tables.

---

## 8. Red scheme catalog (Al) — reference implementation: `red/schemes/ghost_vendor.py`

`ghost_vendor` (done), `bank_swap`, `duplicate_invoice`, `threshold_split`, `ghost_employee`,
`expense_inflation`, `po_mismatch`, `amount_drift`. Each is a class with `viable / plan /
execute` and catalog fields (`display_name`, `story`, `params_schema`, `expected_impact`).
The mock red in `battlefield/mock_agents/` implements four of these crudely so the stack can
be exercised before Al's are ready.

## 9. Blue control catalog (M) — reference implementation: `blue/gate/rules.py`

Deterministic rules shipped: vendor age < 7d, near threshold, duplicate invoice, recent bank
change, bank change with open invoices, no-PO from PO-only vendor, over PO amount, recurring
drift, employee bank matches vendor / no HR record, already flagged high. Decision policy in
`blue/gate/engine.py`; optional LLM judgment in `blue/gate/llm.py`; audit Droid session in
`blue/audit/agent.py`.

---

## 10. Repository layout

```
redledger/
├── README.md  AGENTS.md  GIT.md  DEVLOG.md          ← truth, working agreement, git protocol, shared log
├── docker-compose.yml  docker-compose.dev.yml  docker-compose.mock.yml
├── Makefile  .env.example  ruff.toml  .gitignore
├── .github/   workflows/ci.yml  CODEOWNERS  pull_request_template.md
├── contracts/ schema.sql  ledger-api.yaml  events.md  agent-service.md  CHANGELOG.md
├── agentkit/  agentkit/{models,config,ledger_client,events,tools,droid_agent,server}.py  tests/
├── battlefield/  AGENTS.md  app/{main,config,db,auth}.py  app/api/*  app/gate/*  app/orchestrator/*  app/scoring/*  app/events/*
│              seed/company.py  mock_agents/server.py  fixtures/episodes/*.jsonl  Dockerfile
├── red/       AGENTS.md  agent.py  tools.py  server.py  schemes/{base,ghost_vendor,__init__}.py  prompts/system.md  tests/  Dockerfile
├── green/     AGENTS.md  agent.py  tools.py  server.py  prompts/system.md  tests/  Dockerfile
├── blue/      AGENTS.md  server.py  gate/{rules,engine,llm,cache}.py  audit/agent.py  prompts/audit.md  tests/  Dockerfile
└── frontend/  AGENTS.md  FRONTEND-API.md  app/  lib/{types,reducer,api,ws,mock}.ts  public/mocks/sample.jsonl  Dockerfile
```

---

## 11. Environment variables

See `.env.example`; every variable is there with a comment. Add a variable → add it there and
in your service's `AGENTS.md`. Frontend-only vars for `npm run dev` are in `frontend/.env.example`.
Where each credential comes from per environment: the second table below (full spec:
`deploy/ENVIRONMENT.md` §2).

New with the token split:

| Variable | Read by | Meaning |
|---|---|---|
| `AGENT_TOKEN` | battlefield, red, green, blue | Bearer for agent ↔ battlefield calls (any request with `X-Agent`) and green → blue `/gate`. Replaces `INTERNAL_TOKEN`, which still works as a fallback for both tokens |
| `OPERATOR_TOKEN` | battlefield, frontend server, Makefile | Bearer for everything without `X-Agent`: control plane, `/fe/*`, `GET /events`, `/inputs`, `POST /ws/ticket`. Must differ from `AGENT_TOKEN` |
| `MAX_CREDITS_PER_EPISODE` | battlefield | Pause an episode once its summed `factory_credits` reach this (`error` event, `where: credit_guard`; resume by hand). `0` = off |
| `BATTLEFIELD_URL` | frontend **server** (`/api/bf/*` proxy) | Where the proxy forwards. Compose sets `http://battlefield:8000`; `.env.example` value is for `npm run dev` on the host |

Removed: `NEXT_PUBLIC_BATTLEFIELD_URL`, `NEXT_PUBLIC_INTERNAL_TOKEN`. `NEXT_PUBLIC_WS_URL` stays
(a URL, not a secret). Never put a token in a `NEXT_PUBLIC_*` var.

| Variable | Local dev (your own `.env`) | Prod (GitHub Environment `production` → VM `.env`) |
|---|---|---|
| `AGENT_TOKEN`, `OPERATOR_TOKEN` | any two different strings | `openssl rand -hex 32` each; secrets |
| `FACTORY_API_KEY` | **your own key**, or empty with `DRY_RUN=true` | dedicated prod key; secret; exists nowhere else |
| `DROID_MODEL_RED/GREEN/BLUE` | a cheap / low-multiplier model | pinned prod models; variables |
| `BLUE_GATE_LLM_PROVIDER/_MODEL` | optional | variables |
| `BLUE_GATE_LLM_API_KEY`, `CARTESIA_API_KEY` | own keys or empty | secrets |
| `CRS_USERNAME`, `CRS_PASSWORD` | CRS sandbox login credentials, or empty (Blue returns `unknown`) | secrets; passed only to Blue at runtime |
| `CRS_API_KEY` | legacy placeholder, unused by the CRS identity client | legacy compatibility only |
| `MAX_CREDITS_PER_EPISODE` | `0` (off) | e.g. `40`; variable |
| `DOMAIN`, `CORS_ORIGINS`, `NEXT_PUBLIC_WS_URL` | n/a / `.env.example` defaults | variables (`CORS_ORIGINS`, `NEXT_PUBLIC_WS_URL` default from `DOMAIN`) |
| `GITHUB_REPO` | n/a | not settable (GitHub reserves `GITHUB_`); `deploy.yml` passes `github.repository` |
| `DATABASE_URL`, `POSTGRES_*` | compose default | compose default (Postgres not exposed) |

Repository-level Actions secrets hold only deploy plumbing: `VULTR_HOST`, `VULTR_USER`,
`VULTR_SSH_KEY`; repository variable `DEPLOY_ENABLED` (§17).

CRS uses username/password login, not an API key. Its REST sandbox is
`https://api-sandbox.stitchcredit.com/api`; the CalHacks signup portal is not the API base.
Blue checks only explicitly bound, approved fictional employee profiles during audit. Never
send arbitrary seeded identities: unmatched sandbox requests can reach real vendors.
See `blue/CRS.md` for the profile API, neutral fallback, and live-demo readiness checklist.

---

## 12. Running it

> **After pulling the token split:** a local `.env` that still has only `INTERNAL_TOKEN` gets
> compose's default tokens (`change-me-agent` / `change-me`) inside the containers, while the
> Makefile sends your old `INTERNAL_TOKEN`, so `make episode` 401s. Set `AGENT_TOKEN` and
> `OPERATOR_TOKEN` (two **different** values) in `.env`, then `make mock-agents` again.

```
cp .env.example .env            # set AGENT_TOKEN and OPERATOR_TOKEN (two different strings); your own FACTORY_API_KEY + one LLM key when going live
make mock-agents                # postgres + battlefield + stub red/green/blue — no model calls
make episode MODE=enforce SEED=42 DAYS=4
make up-dry                     # real agent containers in DRY_RUN with hot reload
make up                         # live agents (Factory credits)
make record EP=<id>             # dump an episode to battlefield/fixtures/episodes/
make replay FILE=<id> SPEED=4   # stream a fixture to connected UIs
make lint test                  # what CI runs
```

Frontend with zero backend: `cd frontend && NEXT_PUBLIC_MOCK=true npm run dev` replays
`public/mocks/sample.jsonl` (recorded from the scaffold smoke run).

---

## 13. Hosting decision

**Decision: one VM + Cloudflare in front.** Vultr (sponsor credits) or any $20 box. Docker
Compose from this repo, Caddy for TLS on `api.<domain>`, Cloudflare for DNS/proxy and
Cloudflare Pages for the frontend (free, trivial, uses the teammate's credits where they
matter). Domain from GoDaddy (sponsor prize).

Why not Cloudflare Containers for the whole stack: it works (GA April 2026, up to 4 vCPU /
12 GiB, so the Droid CLI subprocess model fits), but every inter-service call has to be
routed through a Worker and Durable Object bindings, disks are ephemeral so Postgres must be
external anyway, and agent containers scale to zero unless pinged. That's a Friday-night
learning curve for the one person who's also the integration point. The compose file is the
portable truth; if someone gets Containers serving `/health` through a Worker in under two
hours, switch — nothing in the code cares.

Edge: `https://api.<domain>` → Caddy → `battlefield:8000`. `wss://api.<domain>/api/ws`
same path. Put Cloudflare Access on `app.` and `api.` during the weekend; bearer tokens are not
user auth.

**Token scopes** (`contracts/agent-service.md` is canonical). Battlefield picks the expected
token by whether the request carries `X-Agent`:

| Token | Held by | Authorizes |
|---|---|---|
| `AGENT_TOKEN` | battlefield, red, green, blue | every Ledger API request with `X-Agent`; battlefield → agent `/turn` `/gate` `/audit` `/schemes`; green → blue `/gate` mirror |
| `OPERATOR_TOKEN` | battlefield, frontend **server**, Makefile/curl, Ad | every request without `X-Agent`: control plane, `/fe/*`, `GET /events`, `/inputs`, `POST /ws/ticket`, `/ws?token=` |
| WS ticket | browser, 60 s, single use | one `/ws` connection for one episode (or `*`) |
| none | anyone | `battlefield/extensions/fe_*` routes deliberately marked public |

`OPERATOR_TOKEN` + `X-Agent` → 401; `AGENT_TOKEN` without `X-Agent` → 401. If either token is
unset it falls back to `INTERNAL_TOKEN`; battlefield logs a warning when the two are equal.

**Frontend proxy.** The browser holds no token. `lib/api.ts` calls same-origin `/api/bf/<path>`,
a Next route handler that forwards to `${BATTLEFIELD_URL}/api/<path>` with
`Authorization: Bearer ${OPERATOR_TOKEN}` added server-side (both server env, read per request).
It forwards only `content-type`/`accept`, streams the response back, and refuses cross-site
mutations (`Sec-Fetch-Site: cross-site` → 403). Details: `frontend/FRONTEND-API.md`. Because the
proxy is a Node route handler, the frontend needs a Node runtime (the `frontend` container);
a static Cloudflare Pages export can't serve `/api/bf/*`.

**WS tickets.** `lib/ws.ts` calls `GET /api/bf/ws-ticket?episode_id=` (Next route → battlefield
`POST /api/ws/ticket` with the operator token) → `{ticket, expires_at, ws_url}`, then opens
`${ws_url}/api/ws?episode_id=&ticket=&after_id=`. Tickets are HMAC-signed with
`OPERATOR_TOKEN`, valid 60 s, single use; a bad one closes with `4401`, and every reconnect
fetches a new ticket. `ws_url` is the server's `NEXT_PUBLIC_WS_URL` (e.g. `wss://api.<domain>`)
read at request time, so one frontend image serves every environment.

---

## 14. Sequencing

| | Friday night | Saturday | Sunday AM |
|---|---|---|---|
| **Ad** | repo live, VM up, `make mock-agents` running a 4-day episode end to end, CI green | escalation path, scoring gaps (battlefield/AGENTS.md), record off/on fixtures with real agents | hardening, demo episodes recorded, replay verified |
| **Al** | `RedAgent` live on Droid in DRY_RUN against mock battlefield; record Droid findings | full scheme catalog; red adaptive selection; baseline run loses real money | tune attack realism against M's rules |
| **M** | green gated call end to end on Droid (verify `Autonomy.OFF` prompts); blue gate blocking mock red | LLM gate wired; audit Droid session; false-positive tuning with `verdicts/confusion`; seed/traffic realism PRs | reason text quality, report quality |
| **R** | Next skeleton against `sample.jsonl`; information architecture decided | all demo surfaces (frontend/AGENTS.md list) against the shared box | replay mode, compare view, deck |

Integration checkpoints: Fri 02:00 one green tool call gated by blue through battlefield,
visible in a browser. Sat 14:00 a full 3-day episode in `shadow` with real agents. Sat 22:00
controller-off and controller-on episodes recorded. Anything not on screen by then is cut.

Demo choreography, visual identity, and pitch narrative are Dev R's; the backend exposes the
on/off toggle, judge-selected attacks, escalation approve/block, replay, and compare so any
of several demo shapes is possible.

---

## 16. Extension points (how teams grow the sandbox without waiting on Ad)

The core (`contracts/schema.sql`, Ledger API routes, event types in `EventType`) changes only
through a `contracts/` PR. Everything below is yours to use on your own branch; CI's
ownership guard allows exactly these paths for your prefix.

| Need | Mechanism | Who edits what |
|---|---|---|
| Remember something across turns | `agent_state` KV: `LedgerClient.get_state(key)` / `put_state(key, value)`; operator view `GET /api/fe/episodes/{ep}/state/{agent}` | nothing to edit |
| Send a message into an agent's next turn (judge, crowd, another agent) | `POST /api/inputs {episode_id, target, source, payload}` → arrives as `options.inputs[]` on that agent's next `/turn` (or `inputs` on blue's `/audit`) | nothing to edit |
| New event the frontend should see | emit `x.<area>.<name>` with any payload: `EventEmitter.custom(name, payload)` or `bus.emit(..., "x.fe.nudge", ...)`. Frontend reducer keeps them in `state.custom` | nothing to edit |
| New table | `contracts/ext/<area>/<nn>_<name>.sql`, `CREATE TABLE IF NOT EXISTS <area>_...`. Applied after the core schema on startup | your branch |
| New HTTP routes on battlefield (reads, writes to your tables, public endpoints) | `battlefield/extensions/<area>_<name>.py` exporting `router = APIRouter()`; auto-mounted at `/api/x/<area>/...`. `fe_*` may expose no-token routes | your branch |
| Ad-hoc data for the frontend | `POST /api/fe/query {sql}` — single SELECT, 5 s timeout, 5000-row cap. Or write an `fe_*` extension route when the query stabilizes | nothing to edit |
| New gated action, new core column, new Ledger API route for agents | contracts PR | Ad (integration); affected owners notified, never blocking |

Rules: extensions never write core tables (that's what the Ledger API is for); extension
tables carry your prefix; a broken extension logs and is skipped, it cannot take battlefield
down. `battlefield/extensions/fe_example.py` + `contracts/ext/fe/00_example.sql` show the shape
end to end (a public POST that records a nudge, writes an `inputs` row for red or blue, and
emits `x.fe.nudge`). That is the full skeleton of a crowd-participation page: the Next.js route
lives in `frontend/`, the server side is one extension file.

---

## 17. CI/CD

**CI** (`.github/workflows/ci.yml`, on every PR): path-filtered lint+tests per service;
`ownership-guard` fails a PR whose branch prefix touched files outside its area;
`contracts-guard` fails a `contracts/` change without a CHANGELOG line.

**CD** (`.github/workflows/deploy.yml`, on merge to `main` or `workflow_dispatch`), two jobs:

| Job | Environment | Does |
|---|---|---|
| `build` | none; sees no app secrets | builds five images to GHCR tagged `latest` and the commit SHA. No build args: images carry no secrets and no per-environment values, so they can be public |
| `roll` | GitHub Environment `production` (required reviewer: Ad) | runs only if repo variable `DEPLOY_ENABLED` is `true`. SSHes to the VM, `git reset` to `origin/main`, renders `/opt/redledger/.env` with `deploy/render-env.sh` from the environment's secrets/variables, then `docker compose -f docker-compose.yml -f docker-compose.prod.yml pull && up -d` with `IMAGE_TAG=<sha>`, and probes battlefield from inside its container |

`render-env.sh` writes atomically with mode 600, never prints values, and refuses to write if
`AGENT_TOKEN` or `OPERATOR_TOKEN` is empty or the two are equal. `docker-compose.prod.yml` fails
closed: compose won't start if either token is unset. Nobody edits the VM's `.env` by hand; the
next deploy overwrites it. Rotation = change the secret in `production`, re-run the workflow.
Until `DEPLOY_ENABLED=true`, merges build and push images and skip the roll.

Rollback = `git revert` + merge (the durable fix; it redeploys), or re-run an older successful
deploy run from the Actions tab: it pulls that commit's images (`IMAGE_TAG` = its SHA) but with
current `main`'s compose files and env render, and the next merge rolls forward again. The
workflow has no `IMAGE_TAG` input.

**VM** (one-time): `deploy/bootstrap.sh <org>/redledger [<domain>]` installs Docker, creates
the `deploy` user, clones the repo to `/opt/redledger`, opens 80/443. It does **not** write
`.env`; the first deploy renders it. Then: `deploy` user's SSH key → repo secrets
`VULTR_HOST / VULTR_USER / VULTR_SSH_KEY`; fill the `production` environment (§11 table);
`docker login ghcr.io` once on the box (or make the packages public); point Cloudflare DNS
`api.<domain>` and `app.<domain>` at the IP; set `DEPLOY_ENABLED=true` and run the workflow.
Caddy (`deploy/Caddyfile`) terminates TLS. The `frontend` container serves `app.<domain>` (it
needs a Node runtime for the `/api/bf/*` proxy, §13). Step by step: `deploy/OWNER-CHECKLIST.md`
§2–§3; design and rationale: `deploy/ENVIRONMENT.md`.

What is not automated: database migrations (schema is `IF NOT EXISTS`; a column change means
`make db-reset` on the box, which wipes episodes — record fixtures first).
