# Technical track: Cal Hacks "Most Technically Advanced" and Microsoft "Built for the Real World"

Status as of 2026-10-25 ~04:45Z, main @ 53adcb7; prod @ fb829e6.

One doc, two audiences. (a) **Cal Hacks**: Most Technically Advanced Hack, plus the Technical Complexity and
Functionality criteria of the Overall prizes. These judges want depth: hard problems, solved and shown.
(b) **Microsoft**: Built for the Real World (1st) and Customer Impact Award (2nd). These judges want something
that would survive real users and real operations: deployment, security, ops, reliability, rollback, observability.
The facts are the same for both. The emphasis differs (see §2 and §7).

Paths are relative to the repo root. `#NN` is a GitHub PR on md-racc/redledger. "Finding" means a dated line
under Findings in `contracts/CHANGELOG.md`.

**Status legend.** `LIVE` = running on prod (app.redledger.us) with a real model today. `ON MAIN` = merged and
tested, runs keyless, not exercised live on prod. `PLANNED` = not done yet. `NOT DOING` = out of scope.
Infrastructure has no model in it, so for infrastructure `LIVE` means "deployed and serving app.redledger.us"
(prod @ fb829e6). This doc was written from the code. Prod facts that can't be seen in the repo (per-agent
tokens set, the credit cap value, the Cloudflare policy) come from the team's prod operations and are stated as such.

---

## 1. Prize snapshot

| Prize | Value | What judges want (source) |
|---|---|---|
| Cal Hacks: Most Technically Advanced Hack | NuPhy Air60 HE keyboard per member | Not published in what we could read; the title is all we have. Confirm on Devpost |
| Cal Hacks: First / Second / Third Overall | per Devpost | General judging, from search snippets the team collected (devpost.com itself couldn't be fetched): **Application, Intentionality, Functionality (a smooth live demo), Creativity, Technical Complexity**. Confirm on Devpost |
| Microsoft: Built for the Real World (1st) | $3,800 + a Surface laptop per member | Published criteria not found. Our reading of the title: something real users and real operations could live with. Confirm on Devpost |
| Microsoft: Customer Impact Award (2nd) | a presentation slot + mentorship with Microsoft FDEs (forward-deployed engineers) | Same: criteria not found. Our reading: a clear customer and a credible path to impact for them. Confirm on Devpost |

**Confirm on Devpost** for every row: the team couldn't fetch the prize pages. Values come from the team's
research.

---

## 2. Our angle in one sentence, and the 30-second versions

**One sentence:** Red Ledger is a crash-test lab for finance agents: a live attacker agent, a clerk agent and a
controller agent share one ledger, and a single API enforces every control, records every action, and scores
dollars stolen against dollars blocked against the cost of blocking honest work.

### (a) Cal Hacks, 30 seconds (technical depth)

> Three agents, five containers, one enforcement point. Every payment an agent attempts goes through one Ledger API.
> That API asks the controller agent for a verdict, holds the request while a human decides on escalations, and
> commits the result with a compare-and-set, so parallel tool calls can't pay an invoice twice. Idempotency keys come
> from the Droid SDK's tool-call ID. The Droid CLI never hands that ID to tool code, so we recover it from permission
> requests and the event stream. A verdict can be prepared ahead of execution, bound to a state fingerprint, and
> claimed exactly once. After a crash the system pauses itself, expires held decisions, and never re-runs the
> attacker's day. The attacker and the controller's daily audit run live on Factory's Droid SDK; the clerk runs
> keyless on the same harness. It's backed by 911 Python test functions and 202 frontend tests.

### (b) Microsoft, 30 seconds (built for the real world)

> Before a CFO lets an AI pay bills, they need proof. We built the place that produces it, and we run it like a
> product. Each deploy is approval-gated and renders secrets on the server, refusing bad token sets. The origin only
> answers Cloudflare. The browser never holds a credential, and each agent holds only its own. The site is public and
> read-only: anyone can open it and watch, and only an admin, checked on the server, can act. Operators drive prod through a script that keeps the operator token
> on the VM. A credit guard pauses runaway agent spend. Restarts are recovered automatically and visibly. Every event
> can be recorded, secret-scanned and replayed.

---

## 3. Criteria → evidence matrix

| Track | Criterion / thesis point | What we have | Status | Evidence |
|---|---|---|---|---|
| (a) | Technical complexity | Single enforcement point with per-key single flight, CAS state transitions, preparations claimed once under row locks, escalation holds that close exactly once, restart recovery, and tool-call identity recovered from SDK side channels | ON MAIN; the gate is LIVE on prod against live red (verdicts from blue's deterministic rules) | `battlefield/app/gate/gatekeeper.py`, `battlefield/app/api/green_writes.py`, `agentkit/agentkit/invocation.py`; #33, #39, #52, #84, #87, #89 |
| (a) | Functionality (smooth live demo) | 90-second show, backstage consoles on three more laptops that join the active run (#146), judge-picked attacks, judge words typed or spoken that steer the attacker (#154, #165), approve/block on escalations, replay with recorded fallback | ON MAIN (frontend); prod runs the show from the recording by default (§6) | `frontend/docs/show-mode.md`, `frontend/docs/backstage.md`, `frontend/docs/pitch-script.md` (#132) |
| (a) | Intentionality | Contracts-first design (`contracts/` beats code), enforced by CI; ownership by directory; every non-trivial PR independently verified before merge | ON MAIN | `AGENTS.md` §3 inv. 6, `.github/workflows/ci.yml`, `GIT.md` §4 |
| (a) | Creativity | Adversarial co-evolution: lineages, debriefs, playbooks, after-action reviews | ON MAIN; recorded on prod with live red (`ln_f52a3df83c8d`, P1 done) | `battlefield/app/orchestrator/lineage.py`, `battlefield/app/evolution/*`; §10 |
| (a) | Application | A finance controller that gates an autonomous clerk, measured against a live attacker | Red and blue's daily audit LIVE; green keyless on prod by decision | Finding 2026-10-24 (gpt-5.4-mini); #157; #78 |
| (b) | Deployment | Image build with no secrets → approval-gated SSH roll → `.env` rendered from a GitHub Environment → compose pull/up → in-container health probe | LIVE (infra) | `.github/workflows/deploy.yml`, `deploy/render-env.sh`, README §17 |
| (b) | Security | Public read-only site with a server-enforced viewer/admin split, origin IP lock, per-agent tokens and a 401 matrix, operator token kept server-side, HMAC single-use WS tickets, compose network isolation, `origin` hidden from agents; Cloudflare Access + origin JWT verification built and run until P7 | LIVE (read-only mode since 2026-10-25, IP lock, networks, per-agent tokens); origin JWT check ON MAIN, off on prod since P7 | `deploy/Caddyfile` (#47), `frontend/lib/access.ts` (#50), `battlefield/app/auth.py` (#109), `docker-compose.yml` (#15), #152, #159 |
| (b) | Operations | `make prod-*` runbook that never moves the operator token; credit guard; one active run at a time; recording with a secret scan | LIVE (tooling used on prod; see #118's evidence) | `deploy/prod.sh`, `deploy/PROD-OPS.md`, #95, #122 |
| (b) | Reliability | Timeouts on every hop; blue unreachable → escalate (timeout = block); restart recovery; active-turn guard; turn loop isolation | ON MAIN; prod incidents fixed in #81, #118, #122, #176 | `battlefield/app/main.py:44`, `battlefield/app/turns.py`, #79 |
| (b) | Rollback | `git revert` + merge, or re-run an older deploy (that SHA's images); token rollback by deleting secrets | ON MAIN (procedure documented; not rehearsed in a PR we found) | README §17, `deploy/ENVIRONMENT.md` §2 |
| (b) | Observability | Append-only `events` + `audit_log` for every agent call; structlog JSON; `/health` aggregates agent health; backstage LIVE CHECKS; Timescale hypertables + `score_timeline` | LIVE (events, audit, health); Timescale ON MAIN (CI), PLANNED on prod (P5) | `battlefield/app/events/bus.py`, `battlefield/app/timescale.py`, #100 |
| (b) | Customer impact | Gives a finance team evidence before it trusts an agent: dollars extracted vs. blocked vs. false-positive cost, with plain-English verdict reasons | Scoring ON MAIN, running on prod | `battlefield/app/scoring/score.py`, README §4 |

---

## 4. What we have, in detail

### 4.1 Contracts-first architecture, enforced by CI — `ON MAIN`

- **Shape.** There are five containers (`battlefield`, `red`, `green`, `blue`, `frontend`) plus Postgres (README §1–§2).
  Only battlefield has `DATABASE_URL` (AGENTS.md §3 inv. 1). Agents reach the books only through
  `agentkit.LedgerClient` → the Ledger API over HTTP.
- **The contract is the source of truth.** `contracts/` holds `schema.sql` (23 tables), `ledger-api.yaml` (64
  paths, two security schemes, `agentBearer` and `operatorBearer`), `events.md`, `agent-service.md` and `CHANGELOG.md`.
  "If code disagrees with `contracts/`, the code is wrong" (AGENTS.md §3 inv. 6). The pydantic models in
  `agentkit/agentkit/models.py` mirror the contract. The frontend generates its API types from `ledger-api.yaml`
  (`npm run gen:api`, `openapi-typescript`).
- **`ownership-guard`** (`.github/workflows/ci.yml:138-163`). Every PR branch is `<area>/<topic>`. The job derives
  an allowed-path regex from the prefix and fails the PR if the diff touches anything outside it. A red branch may touch
  `red/`, `battlefield/extensions/red_*.py`, `contracts/ext/red/` and devlog fragments. A `contracts/` branch may touch
  only `contracts/` and `agentkit/agentkit/models.py`. An unknown prefix fails outright.
- **`contracts-guard`** (`ci.yml:34-46`, `.github/scripts/check_contracts.py`). Any change to core `contracts/` without
  a `contracts/CHANGELOG.md` line fails CI. The team extension trees `contracts/ext/{red,green,blue,fe}/` are exempt.
- **Extension points instead of contract churn** (README §16). Each team gets `battlefield/extensions/<area>_*.py`,
  auto-mounted at `/api/x/<area>/...`, and `contracts/ext/<area>/*.sql` tables. A broken extension is logged and
  skipped rather than taking battlefield down. Examples on main: `battlefield/extensions/blue_crs.py`, `fe_example.py`.
- **Other CI jobs.** `changes` path-filters the run. `python` runs ruff and pytest per service as a 5-way matrix
  against a `postgres:16-alpine` service container. `battlefield-timescale` runs the same battlefield suite on
  `timescale/timescaledb:latest-pg16` with `EXPECT_TIMESCALE=1`. `frontend` runs typecheck, lint and vitest.
  Caveat: `GIT.md` §9's required-check list doesn't name `battlefield-timescale`, so it is not a merge gate.
- **Merge discipline** (`GIT.md` §4). Authors never merge their own PRs. Before a merge: CI green, a read-only PR
  steward's READY, and an independent verifier's PASS for anything touching `battlefield/`, `agentkit/`, `contracts/`,
  `deploy/` or compose. Merges are pinned with `gh pr merge --squash --match-head-commit <assessed sha>`, so a
  push after assessment voids it.

### 4.2 The single enforcement point — `LIVE` (gate against live red; blue's rules decide) / details `ON MAIN`

Every green mutation (`invoices.match|approve|reject|pay`, `vendor_changes.approve|reject`, `expenses.approve|pay`,
`gl.post`) runs through `gatekeeper.check()` inside battlefield (`battlefield/app/gate/gatekeeper.py:1-25`):

1. Read the episode's `controller_mode`. In `off`, allow and record nothing.
2. Call `POST blue/gate` with the idempotency key, the action, the amount and a context battlefield assembles from the
   books (vendor, PO, recent bank changes, paid history, flags; `green_writes.py:56-131`). The context is
   provenance-stripped (`db.HIDDEN_COLUMNS = {origin, attack_id, origin_of_source, created_by}`, `battlefield/app/db.py:22`).
3. Persist the verdict (`verdicts` row with `rules_fired`, `latency_ms`, `cause`) and emit `gate.verdict`.
4. In `shadow`, record `enforced=false` and allow. In `enforce`: `allow` → proceed; `block` → 403
   `{verdict, reason, verdict_id}` and the entity is marked `blocked`; `escalate` → open an escalation and hold the
   HTTP request for a human, up to `ESCALATION_TIMEOUT_SEC` (90 s). A timeout is a block.
- **Blue down fails safe.** If `/gate` errors or exceeds `GATE_TIMEOUT_SEC` (8 s), the fallback is `escalate` in
  enforce (so a human, or a timeout = block, decides) and `allow` in shadow. It is tagged `rules_fired=["gate_timeout"]`
  and `cause: gate_unavailable` (`gatekeeper.py:327-330`, `:177-179`).
- **Green never calls blue.** The old green → blue mirror was removed (D1, #80). Blue's `/gate` is called only by
  battlefield (`contracts/agent-service.md` "Tokens").
- **Agents read the books, never the scoreboard.** `GET /api/events`, `/api/ws`, `/api/fe/*` and every
  control-plane route reject agent tokens (AGENTS.md inv. 11, 12). Agent-facing `GET /audit_log` is filtered
  server-side to green/blue rows, with no `attacks.*`, `playbook.*` or `auth.*` rows (`battlefield/app/api/reads.py:134-148`, #31).
  A stub-blue capture of 93 gate requests found no provenance fields in any of them (#29 verifier).

### 4.3 Hard correctness and concurrency problems we solved — `ON MAIN`

Droid can issue parallel tool calls, retries race their originals, and humans answer escalations late. Each item below
is a real failure mode, with the mechanism that closes it.

**1. Idempotency keys bound to their first action (#33).** The key is the Droid `tool_use_id`, or `<tool_use_id>:<n>`
for a tool call's n-th ledger write. Same key + same action replays the stored verdict. Same key + a different
action, entity, amount (≥ 1 cent) or, for `invoices.match`, a different `po_id` → audited `409 idempotency key reused
for a different action`, never replayed (`gatekeeper.same_action`, `:275-291`). Without this, an "approve" verdict
could have authorized a "pay".

**2. Per-key single flight + race-safe verdict insert.** Concurrent requests with one key run one at a time through an
in-process lock map keyed `(episode_id, key)`. The map is reference-counted and dropped when idle
(`_single_flight`, `:129-145`). As a backstop, the verdict insert is `ON CONFLICT (episode_id, idempotency_key) DO
NOTHING`: the loser asks blue but persists and emits nothing, then replays the winner's row. If that row is an
escalation, the loser waits up to 2 s for the winner's escalation row and joins it instead of opening a second card
(`:182-262`). This replaced a 500 on the unique index (#39).

**3. Compare-and-set state transitions (#39).** Every green transition is one transaction whose first statement is
`UPDATE … WHERE status = ANY(allowed) RETURNING *` (`green_writes._cas`, `:170`). Only the winner writes the payment,
bank line and PO update and emits `ledger.mutation`. Losers get an audited `409 "<entity> is <status>"`. Blocks are
conditional the same way, so a late block can't overwrite a paid invoice. While a payment waits out an escalation hold
(up to 90 s), the vendor's frozen status and bank account are re-read `FOR UPDATE` inside the transaction
(`green_writes.py:538`, `:655` for employees). A vendor frozen during the hold gets a 409. A changed account means the
payment goes to the current account. **Proof (#39):** 3 or 12 parallel pays → exactly 1 payment, 1 bank line and
1 mutation, in off, shadow and enforce. 20 concurrent `gl.post` under one key → 1 row, without starving the
10-connection pool.

**4. Gate preparations, claimed first (package A: #80, #86, #87, #89).** Green can run the gate half of an action
ahead of execution with `POST /api/preparations`. That validates, asks blue once, persists the verdict, marks an
enforced block, and holds an enforced escalation. The response says `effective: allow|block`. The preparation stores
the binding (action, entity, amount, exact body), mode, day, and a SHA-256 **state fingerprint** over the
provenance-stripped fields the action reads (`battlefield/app/api/preparations.py:56`). Its lifetime is a fixed
120 s from creation and is never extended (`PREPARATION_TTL_SEC`, `agentkit/agentkit/models.py:194`). Battlefield
refuses to boot if `ESCALATION_TIMEOUT_SEC + GATE_TIMEOUT_SEC + 15 > 120`, so a human decision can't arrive after its
preparation died (`gatekeeper.check_preparation_budget`, `:488-495`; currently 90 + 8 + 15 = 113).
When the gated route later runs with the same `X-Tool-Use-Id`, it **consumes** the preparation instead of asking blue
again (`green_writes._prepared`, `:241`, and `_consume`, `:281`). The checks run in this order:
  1. binding mismatch → 409 key conflict (every mode)
  2. already consumed → 409 `preparation_consumed`
  3. still pending → 409 `preparation_pending` (never joins or opens an escalation)
  4. mode or day changed → 409 `preparation_stale` (every mode)
  5. enforce only: expired → 409 `preparation_expired`; a stored block → 403 with `decided_by` and `cause`

  Then, inside the execution transaction: read the mode `FOR SHARE` (a controller toggle can't land mid-commit),
  **claim** the row with `UPDATE preparations SET consumed_at=now() … WHERE consumed_at IS NULL AND (NOT enforce OR
  clock_timestamp() < expires_at)`, recompute the fingerprint under `FOR UPDATE`, and only then run the CAS. Claiming
  first is the design point. Concurrent same-key calls queue on the preparation's row lock. The losers see it consumed
  (409), never the winner's own writes misread as state drift. In enforce, drift rolls the whole transaction back. In
  shadow and off, drift and expiry are audited and the call proceeds (D4). **Proof (#89):** 5 concurrent identical
  payments → exactly one payment. A late human approval after `expires_at` is recorded as `block / timeout`
  (`_record_decision`, `:619-633`).

**5. Escalation holds that close exactly once, plus startup recovery (#52).** An escalation is a DB row plus an
in-process future registered *before* the row is inserted (`_escalate`, `:380-431`). So an open row with no waiter in
this process is by definition an orphan of a restart. Closing is a compare-and-set on `status='open'`
(`_close`, `:356-373`): the resolver, the timeout and the orphan sweep race, and exactly one wins. The future is
shielded, so joiners (retries of the same key) are never cancelled by the holder's timeout. Resolving an orphan
returns 409 and times it out. On startup, `recover_after_restart` (`battlefield/app/main.py:44-73`):
  - expires orphaned escalations
  - sweeps pending preparations to `block / timeout`
  - marks running episodes `paused` with `error{where:"orchestrator"}` (never auto-resumed)
  - pauses running lineages
  - fails running replays

  On resume, the day is idempotent (`runner.py:140-176`). Legit traffic isn't re-injected. Red and blue aren't re-run
  once started, because their writes aren't idempotent. Green re-runs, and its interrupted `turn.started` is closed
  with a synthetic `turn.ended` so the event stream stays balanced. **Verified (#52):** three independent verifier rounds
  with live kill/restart harnesses, plus `battlefield/scripts/escalation_smoke.py` (approve, block, timeout, edge cases).

**6. Active-turn guard (#52).** `battlefield/app/turns.py`. The orchestrator marks `(episode, agent, day)` active for
exactly as long as it waits on that agent. Any agent write outside its active turn gets an audited
`409 no active turn for this agent` (`auth.caller`, `battlefield/app/auth.py:168-174`). A turn battlefield gave up on
(its `/turn` wait timed out), or one orphaned by a restart, can't keep writing into the books.

**7. One active run per battlefield (#122, #123).** Agents serve one turn at a time. On prod, a frontend-started episode
collided with a lineage, and every red turn of the lineage got `409 turn already in progress` and recorded nothing (#122).
Now episode `start|resume|step` and lineage `start|resume` return `409 {"error":"another run is active", episode_id,
lineage_id}` while another non-replay run is active (`battlefield/app/orchestrator/active.py`). The check runs under
the lineage control lock, so two concurrent starts can't both pass. As a backstop, battlefield retries an agent's busy
409 with backoff for up to 10 s (`orchestrator/agents.py:18-40`). `prod.sh evolve` checks the same thing before it
creates anything.

**8. Credit guard.** After every turn, battlefield adds that turn's `factory_credits` to a running total. The total is
lazily re-seeded from the episode's `turn.ended` events after a restart. When the total reaches
`MAX_CREDITS_PER_EPISODE`, battlefield pauses the episode and emits `error{where:"credit_guard"}`
(`runner.py:298-366`). A trip disarms the guard for the rest of that day. Resume or step re-arms it, so an
over-limit episode gets exactly one more paid turn. Zero-credit DRY_RUN turns never trip it. Lineages add a
whole-lineage cap (`config.max_credits`, turns + reflections), and `prod-evolve` refuses to start without one (#95).
Gap found on prod: when blue's audit went live, `/audit` returned no usage, so its ~4k credits per audit counted as 0.
#174 (contract) and #176 (code) add `usage` to the `/audit` response; blue's credits count from the deploy containing
6640354.

**9. Tool-call identity the SDK doesn't hand you (#33, #34, #84).** Finding (Ad, 2026-10-24): the Droid CLI calls
in-process MCP tools with `_meta: {assemblySessionId, caller}` only, never the `tool_use_id`. The ID only appears in the
permission request (`McpToolAction.tool_use.id`) and in the stream (`ToolCall.tool_use_id`).
`agentkit/agentkit/invocation.py` links each execution to its ID, in this order:
  - an explicit ID (tests, DRY_RUN)
  - an `_meta` value equal to an already-registered ID
  - the oldest approved, not-yet-executed registration of the same tool with identical canonical arguments

  At `Autonomy.OFF` only permission-approved entries are claimable. For "strict" agents (#84) a live call that can't be
  verifiably linked never runs, and `LedgerClient._write` refuses before sending (`UnverifiedInvocation`). Red runs at
  HIGH autonomy, best-effort: when the race is lost, it falls back to a UUID4 and logs it.

**10. Keeping the agent service responsive (#9, #20, #79, #81).**
  - In-process MCP tools that `await` stalled every Droid run. `DroidAgent._offload` runs each tool on a small thread
    pool (#9; Finding, Al).
  - Each live turn now runs on its own thread and event loop (`agentkit/agentkit/sync.py`, `run_on_turn_loop`), with a
    bounded 2 s join on cancel. **Proof (#79):** while a tool freezes its loop for 2 s, the service loop's worst gap
    and `/health` latency stay ≤ 50 ms (≥ 1.5 s on the old path), and 300 turns leave fds and threads flat.
  - #81 fixed a prod-observed `Task was destroyed but it is pending!` by cancelling leftover turn-loop tasks,
    bounded at 2 s.

**11. WebSocket catch-up without duplicates or gaps (#42).** `/ws` subscribes *before* reading history, then drops only
live frames whose exact ID was already sent from history. It doesn't use a high-water mark, because BIGSERIAL IDs can
commit out of order and a stale `after_id` must not swallow newer events (`battlefield/app/api/events_api.py:52-85`).

**12. Verdicts don't outlive their day or mode (#147, #151).** A stored verdict is replayed only on the same day and
under the same enforcement it was judged with. Otherwise the caller gets an audited `409 stale verdict` and blue is not
asked again, on the inline gated routes, `gl.post` and `POST /preparations`. Before this, a shadow-mode block came back
as an enforced 403 after a switch to enforce, and a human's escalation decision could carry over to a later day. Of
#151's 11 new tests, 7 fail without the fix. #151 also audits every `PUT /state/{key}` (key and size, never the value).

### 4.4 Security layers — `LIVE` (infra)

From the internet inward:

1. **Cloudflare proxy, public read-only since 2026-10-25 (P7).** `app.redledger.us` sits behind Cloudflare's proxy.
   Until ~04:30Z on 2026-10-25 Cloudflare Access (an email-PIN policy for the four team members) gated it. Now the
   Access app has a bypass-everyone policy, both `CF_ACCESS_*` are blank and `ADMIN_KEY` is set (rotated at the
   switch), so anyone can watch and only admins can act (#152, #159; item 5). The policy is configured in Cloudflare,
   not in the repo. `render-env.sh` accepts only full Access or that mode (a partial Access config, or Access off
   without an `ADMIN_KEY` of ≥ 32 characters, refuses).
2. **Origin IP lock (#47).** `deploy/Caddyfile` serves only Cloudflare's 22 published ranges (15 IPv4, 7 IPv6) and
   returns 403 to everything else. Before this, a direct-to-origin `GET /api/bf/health` returned 200: the VM's IP
   was in the public git history, and a direct connection skipped Access (#47). ACME HTTP-01 renewal still works.
3. **Origin-side Access JWT verification (#48, #49, #50; ON MAIN, off on prod since P7 because `CF_ACCESS_*` are
   blank).** While Access gated the site, an attacker could front our origin with their *own*
   Cloudflare zone, arriving from Cloudflare IPs without ever passing our Access app. So `frontend/middleware.ts` +
   `frontend/lib/access.ts` verify the Access JWT on every page and every `/api/bf/*` call:
   - RS256 against the team JWKS
   - `iss`, `aud`, required `exp`, `nbf`, with 60 s skew allowed
   - tokens over 8 KiB rejected; header or `CF_Authorization` cookie accepted

   It fails closed: a misconfigured team domain or unreachable keys means 403, and token contents are never logged.
   `deploy/render-env.sh:66-77` refuses to render a public deploy (`DOMAIN` set) with only one of `CF_ACCESS_TEAM_DOMAIN`
   and `CF_ACCESS_AUD`, or with both blank and no `ADMIN_KEY`, so a renamed variable can't silently reopen the operator
   proxy (#49, #152). #50 added 18 tests (header, cookie,
   wrong aud/iss, expired, nbf, no exp, bad sig, tampered, HS256/none, JWKS failure).
4. **No public battlefield REST API.** Caddy routes `app.$DOMAIN` `/api/ws*` → battlefield (which still demands a
   ticket) and everything else → frontend (`deploy/Caddyfile:21-27`). Battlefield, agents and Postgres publish no host
   ports in prod (`docker-compose.prod.yml`, `ports: !reset []`).
5. **The frontend proxy holds the only browser-facing credential.** `frontend/app/api/bf/[...path]/route.ts` +
   `frontend/lib/proxy.ts` forward `/api/bf/<path>` to `${BATTLEFIELD_URL}/api/<path>` and add `OPERATOR_TOKEN`
   server-side. Both are server env vars, read per request. Header allowlists apply in both directions: only
   `content-type`/`accept` go up, and the browser's `Authorization`, cookies and `X-*` never reach battlefield. Path
   rewriting rejects `..`, encoded slashes, schemes, empty segments and control characters. Cross-site mutations
   (`Sec-Fetch-Site: cross-site`) get 403. Timeouts are 30 s, or 300 s for `/step`. The rule "never put a token in a
   `NEXT_PUBLIC_*` var" is AGENTS.md inv. 9. **Roles (#159):** `/admin` posts the key to `POST /api/admin/login`
   (constant-time compare, rate-limited, ≤ 20 failures a minute globally), which sets an HMAC-signed HttpOnly,
   SameSite=Strict, Secure cookie. Viewers can only GET or HEAD through the proxy; anything else is 403 before
   battlefield is contacted. The ground-truth lineage export and the paid voice route are admin-only. In production an
   unset or short `ADMIN_KEY` means nobody is admin. #159's adversarial review found a fail-open path through a
   runtime mock flag and it was fixed before merge.
6. **HMAC single-use WS tickets (#41, #42).** Format `<scope>.<exp>.<nonce>.<sig>`:
   - `sig = HMAC-SHA256(OPERATOR_TOKEN, scope|exp|nonce)`
   - 16-hex-character nonce, 60 s lifetime, single use
   - canonical form enforced so one ticket has exactly one spelling
   - a bad ticket closes with `4401` (`battlefield/app/auth.py:218-274`)

   The browser gets one via `GET /api/bf/ws-ticket` (frontend server → battlefield `POST /api/ws/ticket`).
7. **Per-agent tokens and the 401 matrix (#108, #109, #110).** Battlefield holds `AGENT_TOKEN_RED/GREEN/BLUE`. Each
   agent container gets only its own, as `AGENT_TOKEN` (`docker-compose.yml:96,112,128`; prod overlay fails closed with
   `:?`). Comparisons are constant-time (`hmac.compare_digest`). Matrix (`auth._authenticate`, `:63-76`;
   `contracts/agent-service.md` "Tokens"):
   - `X-Agent: a` + a's token → authenticated (then 403 if the role may not call that route)
   - `X-Agent: a` + b's token, or + `OPERATOR_TOKEN` → **401**, audited as `auth.refused` with `presented_by`
     (never the token); the refusal row is operator-only
   - no `X-Agent` + any agent token → **401**
   - an unknown token → 401, logged only, so unauthenticated requests never write to the DB (#110)
   - battlefield calls each agent's `/turn`, `/gate`, `/audit`, `/schemes`, `/reflect` with that agent's own token

   `render-env.sh` takes the three tokens all-or-none, pairwise distinct, and distinct from both the operator token and
   the shared token (`:33-56`). **On prod since ~19:00Z 2026-10-24**: the three per-agent secrets are set and
   working. (With no per-agent secrets, render-env would fall back to the shared token with a warning.)
8. **Compose network isolation (#15).**
   - `edge`: frontend + caddy ↔ battlefield
   - `agents`: red/green/blue ↔ battlefield, with internet egress for model APIs
   - `data`: postgres ↔ battlefield only, `internal: true`, no egress

   Only battlefield joins more than one. Agents can't reach the frontend's operator proxy or Postgres. #15 checked this
   live on the VM with a throwaway project: from red/green/blue, frontend and postgres were unreachable.
9. **Secrets never in images.** The `build` job has no environment and no build args. App secrets live only in the
   GitHub `production` environment (required reviewer: Ad), and only the `roll` job sees them
   (`.github/workflows/deploy.yml:1-7`).
10. **Secret scanning on everything we publish.** `prod.sh record` refuses a fixture (exit 3, moved to a quarantine
    dir outside the repo) on `sk-`, `fk-`, `ghp_`/`github_pat_`, `AKIA`, `AIza`, `xox?-`, JWTs, PEM keys,
    `Bearer <long>`, or a `[REDACTED]` marker. It warns on long hex/base64 runs. Hits print only line number, first
    4 characters and length (`deploy/PROD-OPS.md` "Record the demo fixtures"). Lineage exports and evolution reports go
    through the same kind of scan (`battlefield/scripts/evolution_report.py`) and land in a git-ignored `runs/`.
    Caveat: local `make record` (Makefile:97) does not scan; only the prod path does.

### 4.5 Operations — `LIVE` (prod tooling)

- **Deploy pipeline** (`.github/workflows/deploy.yml`). On push to `main`, or by `workflow_dispatch`, with
  `concurrency: deploy` and no cancel-in-progress:
  1. `build` (5-way matrix) pushes `ghcr.io/<repo>/<svc>:latest` and `:<sha>`.
  2. `roll` runs only if `vars.DEPLOY_ENABLED == 'true'`, in the `production` environment (an approval gate). It SSHes
     to the VM, `git reset` to `origin/main`, and runs `sh deploy/render-env.sh .env` (atomic, mode 600, values never
     printed). Then `IMAGE_TAG=<sha>`, `docker compose … pull` and `up -d --remove-orphans`, and a 10 × 3 s probe of
     battlefield from inside its container.
- **render-env refuses bad token sets** (`deploy/render-env.sh`). It refuses:
  - empty or equal `AGENT_TOKEN`/`OPERATOR_TOKEN`
  - whitespace-only tokens
  - partial or duplicate per-agent tokens
  - values containing a quote or newline
  - a public `DOMAIN` with a partial Access config, or with Access off and no `ADMIN_KEY` (≥ 32 characters)

  It also pins `POSTGRES_IMAGE=postgres:16-alpine` for prod. `docker-compose.prod.yml` fails closed if any token is unset.
- **Rollback** (README §17). Either `git revert` + merge (redeploys), or re-run an older successful deploy: that run
  pulls its SHA's images with current `main`'s compose and env render. Token rollback: delete the three per-agent
  secrets and redeploy (`deploy/ENVIRONMENT.md` §2).
- **`make prod-*` runbook without moving the token** (`deploy/prod.sh`, `deploy/PROD-OPS.md`, #30, #95).
  - Every operation is a fixed Python program run *inside* the battlefield container (`docker compose exec -T battlefield
    python3 -c …`). It reads `OPERATOR_TOKEN` from the container's own env and calls `localhost:8000`.
  - The program and every argument travel base64-encoded, so user input never reaches the remote shell or the program
    source as code. JSON arguments are parsed and type-checked remotely. Arguments are capped at 64 KiB.
  - Before printing, the program replaces any env value whose name matches `TOKEN|KEY|SECRET|PASS` (including its
    `repr` forms) with `[REDACTED]`.
  - Every hop has a timeout. `PROD_DRY=1` prints what would run.
  - Prod targets take no defaults, so a bare `make prod-episode` fails with usage instead of acting on prod. #30's
    verifier caught that a bare `make prod-episode` used to start a 10-day prod episode.
  - Targets: `health`, `ps`, `logs`, `episode`, `wait`, `step`, `pause`, `resume`, `toggle`, `attack`, `escalations`,
    `resolve`, `score`, `credits`, `record`, `fixtures`, `evolve`, `lineage-status|pause|resume|wait|export`,
    `evolution-report`.
- **Going live one agent at a time.** `DRY_RUN_RED/GREEN/BLUE` override `DRY_RUN` per agent through compose,
  render-env and deploy. Red went live first (`deploy/PROD-OPS.md` "Going live: red, then blue's audit"); blue's audit
  followed on 2026-10-25. Prod today: `DRY_RUN=false`, `DRY_RUN_GREEN=true`, `DRY_RUN_BLUE=false`, visible as
  `dry_run` in `make prod-health`. Blue's `droid_ok` always read false before #176; from the deploy containing 6640354
  it is truthful. #169 fails the blue image build if the Droid CLI or SDK is missing, so a live flip can't land on a
  broken image.
- **Record / replay** (#43). `POST /api/replays/{id}/play` re-emits a fixture as a real `replay_*` episode with fresh
  event IDs, so WebSocket catch-up, `GET /events` and the event-derived `/fe` views all work. Safeguards:
  - fixture names must match the listing, and symlinks can't escape the fixtures dir
  - a malformed line gets a 422 naming it before any row is created
  - agents get 403 on any `replay_*` episode
  - shutdown cancels replays and marks them failed

  On main: one episode fixture (`battlefield/fixtures/episodes/sample-enforce-4d.jsonl`, a mock run), the
  golden lineage fixtures (`battlefield/fixtures/lineages/sample-{report,timeline}.json`), and the live-red
  controller off/on pair recorded on prod with `make prod-record` (`docs/recordings/`, #136; seed 42, 10 days: off
  $10,284.61 extracted, enforce $1,824.22). The pair is secret-scanned; to replay it, copy it into the fixtures dir.
- **TimescaleDB (#98, #100)** — `ON MAIN` (CI-proven), prod `PLANNED` (P5).
  - `events` and `audit_log` are keyed `(id, ts)`. At startup, `battlefield/app/timescale.py` makes them hypertables
    on `ts` (`migrate_data`).
  - It creates the `score_timeline` continuous aggregate (1-minute buckets of `score.updated` per episode,
    real-time, 1-minute refresh policy, 30-day start offset).
  - All setup is bounded by `lock_timeout 5s` / `statement_timeout 120s`, and it never raises. Log lines:
    `timescale_unavailable` on plain Postgres, `timescale_restart_required` when the extension isn't preloaded, and
    `timescale_setup_failed`.
  - CI runs the whole battlefield suite on both images.
- **Prod incidents found and fixed on the running system.** All three are evidence of operating it, not just deploying it:
  - #81: a prod log error between live turns
  - #118: `gemini-3.8-flash` stalled every live red turn at the 170 s stream timeout; fixed by switching only
    `DROID_MODEL_RED` (Finding)
  - #122: a frontend episode collided with a lineage
  - #174/#176: blue's first live audits on prod were recorded as 0 credits, so the credit guard didn't see them, and
    blue's `droid_ok` always read false (fixed from the deploy containing 6640354)

### 4.6 Developer experience — `ON MAIN`

- **DRY_RUN everywhere** (AGENTS.md inv. 8). Every agent runs with no Factory or LLM key: canned turns, and blue's gate
  runs rules only. CI never needs a model key (`GIT.md` §9).
- **Mock agents** (`battlefield/mock_agents/server.py`, `make mock-agents`). One stub app, with `AGENT_NAME` selecting
  red, green or blue. A believable episode at zero credits. The mocks adapt across generations: red climbs an evasion
  ladder, blue learns `learned:*` rules. A 5-day keyless generation takes about 1.3 s (README §15).
  `MOCK_BLUE_ESCALATE` forces escalations for demos.
- **Docker-free local stack (#107, #116).** `make local-stack [AGENTS=mock|real] [RED=|GREEN=|BLUE=mock|real]` runs
  Postgres 16 via pgserver, battlefield on :8000 and the agents on :8001-8003 as process groups. It generates three
  distinct agent tokens plus an operator token into `.local-stack/env` (mode 600). It also runs on stock macOS bash
  3.2 without `setsid`. #116 verified this under a source-built bash 3.2.57, not on a real Mac.
- **Frontend with no backend.** `NEXT_PUBLIC_MOCK=true npm run dev` replays `public/mocks/sample.jsonl`.
  `npm run dev:live` runs `tools/fake-battlefield.mjs` (`frontend/docs/backstage.md`).
- **Operator fixtures (#124, #130).** `POST /api/episodes/{id}/fixtures` seeds legit employees and expenses in one
  transaction for acceptance runs. It is never agent-callable, and refused while a run is active.
- **Tests at 53adcb7** (`def test_` / `it(`/`test(` counts; parametrized cases expand at run time):
  - agentkit 126 in 14 files
  - battlefield 392 in 39 files
  - red 103 in 11
  - green 107 in 13
  - blue 183 in 20
  - frontend 202 in 27

  That is 911 Python test functions. PR bodies report higher *pass* counts after parametrization, e.g. "battlefield
  555 passed" (#151), blue "422 passed" (#176), red "132 passed" (#166) and frontend "214 tests" (#154).

### 4.7 Independent verification caught real bugs before merge — `ON MAIN` (process)

A fresh subagent that didn't write the code verifies every core PR (`GIT.md` §4). Specific catches, from PR bodies and
the CHANGELOG:

- **#52:** three verifier rounds with live kill/restart harnesses found three blockers: same-key concurrent
  escalations, red re-running on resume, and orphaned writes after a restart. All fixed and re-verified.
- **#62:** first pass FAIL with three information-leak/scoring blockers:
  - listing legit freezes let blue deduce the unlisted frozen vendors were red
  - vendor-change attribution over a subset leaked a pending red item and corrupted scoring
  - post-reveal freezes inflated `dollars_blocked`
- **#57:** blocker. `/audit_log` would have shown green's `PUT /playbook` args to blue; `playbook.*` rows became
  operator-only.
- **#30:** two rounds caught make expanding `$(shell …)` inside user input, a bare `make prod-episode` starting a
  10-day prod episode, an unscrubbed traceback on a malformed token, and three smaller issues.
- **#87:** an orphaned escalation on a cancelled holder, plus a contract gap: `GET /preparations` during a hold failed
  model validation, fixed in #86.
- **#84:** red's tool listing could fail a live turn on prod. Fixed before merge.
- **#72:** demo creation could wait ~9 min on reflection, far past Cloudflare's 100 s. Now bounded.
- **#130:** refuse seeding fixtures into a running episode.
- **#109 verification:** led to the contract change that only known callers' refusals are audited (#110; CHANGELOG
  2026-10-24).
- **#39:** the held-payment re-read (`FOR UPDATE` on vendor status and bank account) was added after review.
- **#142, #151:** each had a separate reviewer; the withholding test fails with #142's fix reverted, and 7 of #151's
  11 new tests fail without its fix.
- **#159:** the adversarial security review found a fail-open path to admin through a runtime mock flag, fixed before
  merge, then re-reviewed against a production build (method tricks, header smuggling, cookie forging, CSRF).
- **#154:** the PR steward found the paid voice route reachable by viewers; it became admin-only before merge (#156).

---

## 5. What's in flight / planned (relevant to this track)

| ID | What | Owner | Status | If it doesn't land, say |
|---|---|---|---|---|
| P1 | Live-red evolution lineage `ln_f52a3df83c8d` (5 gens × 8 days, enforce, ~109k red credits, ran to completion under one-active-run, #122) | Ad | DONE | Red adapted (re-weighted to `threshold_split`, extraction $19,076 → $97,734); blue's learned controls never fired on a split. Say that plainly |
| P2 | Live-red off/on recordings (`docs/recordings/`) | Ad | DONE (#136) | Not wired into the show: "the compare beat uses the recorded mock episode; the controller-off act is a projection, and the UI says so" (`frontend/docs/show-mode.md`); the live-red pair can be replayed via `POST /replays/{id}/play` |
| P3 | Evolution view in the frontend from real data | R (#117) | PARTIAL: the EvolutionCard loads the real `/fe/lineages/{id}/report` (on prod, `ln_f52a3df83c8d`), with fallback to `public/mocks/lineage-report.json` | "The evolution card shows the latest real lineage report." Say which label showed |
| P4 | Agents live on Droid | M | Blue audit LIVE (#157); green NOT DOING (Ad's decision, #78) | "Red and blue live on Droid; green on the same harness, keyless" |
| P5 | Prod on the TimescaleDB image | Ad | NOT DOING for the hackathon unless it lands (#100: `migrate_data` takes an ACCESS EXCLUSIVE lock) | "TimescaleDB proven in CI; prod on Postgres 16" |
| P6 | CRS live demo | M / Ad | PASSED on prod with blue's live audit (ep_9cbc3362d44e, #197); local acceptance earlier (ep_0181eda1c921); live at the table still to do | "Recorded on prod 2026-10-25 (ep_9cbc3362d44e); live at the table on request" |
| P7 | Public read-only site (no Access) | Ad | DONE, LIVE since ~04:30Z 2026-10-25 (#152, #159) | — |
| P8 | Invoice threshold-split control in blue | M (#175) | ASKED | "Red found a gap in invoice split detection; the expense version is shipped (#173)" |
| P9 | Short live lineage after P8 to show blue closing the gap | Ad | PLANNED after P8 | Keep the P1 story: "the sandbox surfaced a real gap" |
| — | A recorded rollback rehearsal | Ad | not done | Don't claim "tested rollback"; say "documented rollback path" |

---

## 6. Demo beats for this track

R's pitch (`frontend/docs/pitch-script.md`) and the 90-second show (`frontend/docs/show-mode.md`) are the spine. The
technical beats ride on them. Nothing here changes the script; these are what to point at, or what to show if a
judge stops by the table.

**Important about prod:** the show runs live only if every agent is keyless (`components/arena/useShow.ts`
`wantLive`; viewers always get the recording). Prod red and blue are live, so on app.redledger.us the show
**defaults to the recording**, and the controller-off act is a
projection. `?show=live` forces live acts, but each act steps 4 days with live red turns of about 11 s each, which
doesn't fit the act windows. Since #146/#159 every window joins the running episode or lineage, so during a recorded
show the consoles show the live run, not the show's events. Rehearse with that in mind (§9 Q9). The judge's free-play
attack at the end does hit the real backend, and only from a window logged in as admin (`/admin`).

| When (pitch / show) | On screen | Technical point (a) | Real-world point (b) |
|---|---|---|---|
| 0:27–0:43 show IV/V (off → on) | money walks out, then the red number stays at zero | the same enforcement point, toggled by `PATCH /episodes/{id}/controller` | "controls are a switch you can measure" |
| ~0:55 "Your decision" card | Approve / Block on an escalation | held HTTP request; escalation closes exactly once; timeout = block | human in the loop with a fail-closed default |
| Blue's minute (laptop 4, `/backstage/blue`) | verdicts, rule board, confusion matrix, escalations | verdict reasons + `rules_fired` persisted per idempotency key | auditor-readable reasons; false-positive cost is scored |
| Green's minute (laptop 3) | gated attempts and blue's answers | CAS transitions; preparations; 403 body with `verdict_id` | no double payments under parallel calls |
| Any laptop, `/backstage/battlefield` | `/health` of every service, control plane, API TRAFFIC log | one choke point; every call proxied and logged | observability without a dashboard product |
| Close: "Pick an attack" | judge launches a scheme via `POST /episodes/{id}/attack` | live red on the Droid SDK, queued for its next turn | real system, real backend, right now |
| Close, optional: "or say one" | judge speaks or types an attack in any language (#154) | speech-to-text server-side, words to red as quoted data via `POST /inputs`, which set the forced scheme's params (#165) | a judge can direct the attacker without any access to it; voice is admin-only and untested against the real ElevenLabs service |

**Table-side extras for technical judges** (pre-record as terminal clips; don't run against prod live):
- On `make local-stack`: a red-token request claiming `X-Agent: green` → 401. Then `GET /audit_log` as the operator
  shows the `auth.refused` row.
- Double-pay race: the #39/#89 tests (`battlefield/tests/test_green_writes_db.py`,
  `test_consume_preparation_db.py`): 5–12 concurrent pays → 1 payment.
- Kill battlefield mid-escalation, restart: the episode is `paused` with an `error` event, and the escalation is
  timed out (`battlefield/scripts/escalation_smoke.py`, `test_runner_resume_db.py`).
- For Microsoft: the Actions run with the `production` approval gate, `render-env` refusing an equal token pair (show it
  locally: `AGENT_TOKEN=x OPERATOR_TOKEN=x sh deploy/render-env.sh x.env` exits non-zero and writes nothing), and
  `PROD_DRY=1 make prod-score EP=…` showing that no token appears.

**Fallbacks.** If the backend is down, the show and consoles fall back to the recording, and the first LIVE CHECK reads
`[FAIL]`, so a rehearsal can't be mistaken for live (`backstage.md`). If live red stalls, the credit guard and the
170 s stream timeout fail the turn, not the episode (AGENTS.md inv. 10). Say so, and continue on the recording.
If a judge's attack doesn't land during the pitch, point at any block already on screen (pitch-script, Blue's minute).

---

## 7. Devpost copy, paste-ready

Sentences that depend on a planned item are tagged `[only if P#]`.

**Inspiration**
Before a car goes on the road, someone crashes it. Before an AI agent touches a company's money, people mostly hope.
Finance teams are being asked to let agents match invoices, pay vendors and reimburse expenses, and nobody can show
them what happens when someone is actively trying to trick that agent. We wanted a place that produces that evidence.

**What it does**
Red Ledger simulates a small company, Coastal Supply Co., through business days, with three AI agents working on one
shared ledger. Red is an attacker that commits invoice and payroll fraud from eight schemes: ghost vendors,
bank-account swaps, duplicate invoices, threshold splits, ghost employees, inflated expenses, over-PO invoices and
creeping recurring amounts. A judge can steer it by typing or saying an attack. Green is a finance clerk doing real
accounts-payable work. Blue is a
controller that gates every money-moving action and audits the books. Every action goes through one Ledger API that
enforces blue's verdict, holds escalations for a human, logs every call, and scores the run: dollars extracted,
dollars blocked, and the cost of blocking honest work. Turn the controller off and on with the same seed and you see
what the controls are worth. Run several generations and the agents learn from debriefs and rewrite their playbooks.

**How we built it**
Five containers plus Postgres:
- a FastAPI "battlefield" holding the Ledger API, orchestrator, gate, event bus and scoring
- three agent services on a shared Python kit over Factory's Droid SDK
- a Next.js frontend with a 3D arena and raw backstage consoles

The contract (OpenAPI, SQL schema, event and agent-service specs) came first. CI enforces that each teammate's branch
only touches their own directory, and that every contract change carries a changelog entry. Correctness under parallel
agent tool calls comes from four mechanisms:
- idempotency keys bound to the Droid tool-call ID and to their first action
- compare-and-set state transitions
- gate decisions prepared ahead of time and claimed exactly once under row locks
- escalation holds that close exactly once and are recovered after a restart

Prod is one Vultr VM. GitHub Actions builds secret-free images, and an approval-gated job renders the server's
environment from a GitHub Environment and rolls Docker Compose. Caddy terminates TLS and only answers Cloudflare.
The site is public and read-only: anyone can watch, and only an admin, checked on the server, can start runs or act.

**Challenges we ran into**
- The Droid CLI never passes the tool-call ID to tool code, which we need as the idempotency key. We recover it from
  permission requests and the event stream, and refuse calls we can't link.
- In-process tools that awaited I/O stalled every agent run. We moved tools, and then whole turns, onto their own loops.
- Parallel tool calls could pay an invoice twice. Now every transition is a compare-and-set, and 3–12 concurrent pays
  produce exactly one payment in tests.
- We found our origin reachable around Cloudflare Access. We locked it to Cloudflare's IP ranges and added origin-side
  JWT verification.
- On prod, one model started stalling every live attacker turn. We recorded the finding and switched models.
- Reviewing our own spec, we found a stored verdict could be replayed on a later day or after a shadow-to-enforce
  switch. Now a verdict is bound to its day and mode, and a stale replay is refused.

**Accomplishments that we're proud of**
- Two live Droid agents on prod: the attacker runs a full attack in about 11 s for about 2.6k credits a turn, and
  the controller's daily audit runs with strict tool-call identity for about 4k credits a day.
- One enforcement point, with race-safe, exactly-once semantics that independent reviewers tried to break with
  kill/restart harnesses before we merged them.
- 911 Python test functions and 202 frontend tests, including real-concurrency and real-Postgres tests, and the full
  backend suite also running on TimescaleDB in CI.
- An operator toolkit that drives prod without the operator token ever leaving the server. With it we ran a
  five-generation, 40-turn lineage with the live attacker on prod under a credit guard, one run at a time.
- The whole system runs with no model keys at all, which is how four people built it in parallel in one weekend.

**What we learned**
- Agent tooling needs the same discipline as payment systems: idempotency, compare-and-set, and fail-closed defaults.
  Agents retry, run in parallel, and hang.
- "Contracts beat code" let four people and their coding agents build against each other without stepping on each other.
- Verify your edge: an access proxy in front of an origin is only as good as the origin's refusal to talk to anyone else.

**What's next**
- Close the control gap our live five-generation lineage found: the attacker learned to split invoices across an
  established vendor. The expense version of the split control shipped; the invoice version is next `[only if P8:
  "shipped"]`, then a short live re-run `[only if P9]`.
- Run the clerk live on the Droid SDK after its acceptance matrix.
- Move prod to TimescaleDB.
- Turn the scoreboard into a pre-deployment report a controller could hand an auditor.

**Built with**
python, fastapi, asyncpg, pydantic, structlog, httpx, uvicorn, postgresql, timescaledb, factory-droid-sdk, mcp,
next.js, react, typescript, three.js, react-three-fiber, zustand, tailwindcss, jose, vitest, elevenlabs, docker,
docker-compose, caddy, cloudflare, github-actions, ghcr, vultr, uv, ruff, pgserver

(Drop `elevenlabs` if voice isn't working on prod.)

**Why this fits "Most Technically Advanced Hack"**
Red Ledger's hard part is invisible on purpose: one API sits between three autonomous agents and the money, and it
stays correct when agents call tools in parallel, retry, time out, or the server restarts in the middle of a human
decision. We bound idempotency keys to the Droid SDK's tool-call IDs, even though the CLI never hands those IDs to tool
code. We made every payment a compare-and-set, let the clerk prepare a gate decision ahead of execution that can be
claimed exactly once under row locks, and made escalations close exactly once across resolvers, timeouts and crash
recovery. The attacker and the controller's daily audit run live on Factory's Droid SDK. Every mechanism has
real-concurrency tests, and independent reviewers tried to break each one before it merged.

**Why this fits "Built for the Real World" / "Customer Impact"**
The customer is a finance team deciding whether to let an AI agent touch accounts payable. Red Ledger gives them
evidence: what a real attacker extracts with controls off, what the controls block with them on, and what blocking
honest work costs. Every verdict comes with a reason an auditor can read. We run it like a production service:
- approval-gated deploys from secret-free images
- an origin that only answers Cloudflare
- a public read-only site: no credential in the browser, a server-enforced viewer/admin split, and each agent holding
  only its own token
- a spend guard on agent credits, single-active-run protection, and restart recovery that pauses instead of guessing
- recordings that are secret-scanned before they can be shared

---

## 8. Claims ledger

### Safe to say
- Red runs live on Factory's Droid SDK on prod (`gpt-5.4-mini`, reasoning low): a full attack in about 11 s, about
  2.6k credits per turn (Finding 2026-10-24; ep_568aef023d7c).
- Every agent action goes through one Ledger API, and agents never touch the database (`docker-compose.yml` `data`
  network is internal; AGENTS.md inv. 1).
- Parallel pays of one invoice produce exactly one payment, in tests with 3, 5 and 12 concurrent calls (#39, #89).
- Escalations close exactly once. After a restart, held escalations are timed out and running episodes are paused,
  never auto-resumed (#52; `battlefield/app/main.py:44`).
- The browser never holds a token. The frontend server adds the operator token (`frontend/app/api/bf/[...path]/route.ts`).
- The origin only serves Cloudflare IP ranges (#47).
- The site is public and read-only: anyone can watch at app.redledger.us, and only an admin signed in at `/admin` can
  start runs, launch attacks, use voice or resolve escalations; viewers get 403 on anything but GET/HEAD (#152, #159).
- Deploys are approval-gated, and images carry no secrets (`.github/workflows/deploy.yml`).
- CI runs the backend suite on both plain Postgres 16 and TimescaleDB (`ci.yml` `battlefield-timescale`).
- Everything runs without model keys (DRY_RUN, mock agents, local stack).
- Per-agent tokens: no agent can act as another; another agent's token is a 401 (#108–#111), deployed on prod.
- Blue's daily audit runs live on Droid on prod (#157; ep_f9c695b3144f, 3,806 and 4,109 credits). In the prod CRS run ep_9cbc3362d44e it called `crs_identity_check`, raised the CRS finding, and the gate blocked that employee's next expense (#197; one 2-day run).
- A stored gate verdict is never replayed on another day or under another mode (#147, #151).
- 911 Python test functions and 202 frontend tests at 53adcb7.

### Say with this caveat
- "Blue's /gate answers in ~8 ms p95." Caveat: measured on a local stack during a live blue audit session (#119:
  p95 8.04 ms, max 56.6 ms, 1,817 samples), not on prod.
- "Green runs its full logic." Caveat: keyless on prod (`DRY_RUN_GREEN=true`) by decision (P4). Blue's audit is live;
  blue's gate verdicts come from its deterministic rules either way.
- "The origin re-verifies the Cloudflare Access JWT." Built and tested (#50), but off on prod since the site went
  public read-only (P7). Say "it did, while Access gated the site".
- "A credit guard caps spend." Caveat: blue's audit credits are counted only from the deploy containing 6640354 (#176).
  For the smoke episode quote `turn_usage` (3,806 / 4,109); `make prod-credits` shows blue as 0 there.
- "TimescaleDB hypertables and a continuous aggregate." Caveat: CI-proven; prod is plain Postgres 16 (P5).
- "Agents learn across generations." Caveat: with live red on prod (`ln_f52a3df83c8d`), red adapted and blue's bounded
  learning didn't keep up. The closed-loop numbers (blue catches 5/5 in g3) are a keyless mock-agent lineage
  (`ln_fbdfbd2d74cc`) and must be labelled mock.
- "Controller off vs. on, same crime, different ending." Caveat: on prod the show plays the mock recording, and the off
  act is a projection (`show-mode.md`). The live-red pair (#136) is $10,284.61 off vs. $1,824.22 enforce, not zero,
  and red's live choices differ between the two runs.
- "Rollback in one step." Caveat: the procedure is documented (README §17) but we found no recorded rehearsal.
- "Secret-scanned recordings." Caveat: true for `make prod-record` and lineage exports. Local `make record` doesn't scan.
- "Independent verification before merge." Caveat: the verifiers are AI subagents run by the integration orchestrator,
  not human reviewers (`GIT.md` §4, `AGENTS.md` §10).

### Do NOT say
- "Green is a live AI agent in production" or "three live agents." Not true (P4). Say red and blue's audit.
- "Runs on TimescaleDB in production." Not true (P5).
- "The agents sharpen each other" with the live attacker: in `ln_f52a3df83c8d` red got better and blue didn't.
- "Horizontally scalable." Battlefield must run as a single uvicorn worker. The turn guard, escalation waiters and WS
  ticket used-set are in-process (`battlefield/app/turns.py` docstring), and the frontend sync hub is one Node process
  (`backstage.md` "Limit").
- "Zero-downtime deploys." A redeploy restarts battlefield and kills any running episode's loop. The episode is left
  `running`/`paused` and needs a resume (`deploy/PROD-OPS.md` "Credit cap").
- "Per-user authentication." The site is public; the proxy acts with one operator token, and #159's viewer/admin
  split uses one shared admin key, not per-user accounts (`deploy/ENVIRONMENT.md` §5
  lists per-user auth as out of scope).
- "Automated migrations." The schema is `CREATE TABLE IF NOT EXISTS`, and a column change means `make db-reset`
  (README §17).
- Any prod IP, hostname other than app.redledger.us, or key-file path.

---

## 9. Likely judge questions → answers

1. **"What stops two parallel tool calls from paying the same invoice twice?"** Each transition is one transaction
   that starts with `UPDATE invoices SET … WHERE id=$ AND status = ANY(allowed) RETURNING *`. Only one request can win.
   The loser gets an audited 409 and writes nothing else. Tested with up to 12 concurrent pays → 1 payment (#39).
2. **"What's an idempotency key here, if the SDK doesn't give tools the call ID?"** It's the Droid `tool_use_id`. The
   CLI only exposes it in the permission request and the stream (Finding). agentkit registers it from those sources
   and links the execution by identical canonical arguments. Strict agents refuse any call they can't link (#84).
   A key is bound to its first action, so reusing it for a different action is a 409, never a replay (#33).
3. **"What happens if the controller (blue) is down?"** In enforce, the gate defaults to `escalate`: a human decides,
   or after 90 s it's a block. In shadow it allows and records `cause: gate_unavailable` (`gatekeeper.py:327-330`).
4. **"What if the server restarts while a human is deciding an escalation?"** The held request died with the process.
   On startup, open escalations with no waiter are timed out (= block). Pending preparations become `block / timeout`.
   Running episodes are paused with an error event, never auto-resumed. Resuming won't re-run red's day (#52).
5. **"How do you keep agents from cheating, e.g. reading the answer key?"** Ground truth (`origin`, `attack_id`) is
   stripped from every agent response (`db.HIDDEN_COLUMNS`). Agent tokens can't reach the event stream, `/fe/*` or the
   control plane. Agent-facing `audit_log` is filtered server-side. Agents can't reach each other or Postgres at the
   network layer (#15).
6. **"Why prepare a gate decision ahead of executing it?"** Green's Droid permission handler needs the verdict
   *before* the SDK runs the tool, but the ledger has to stay the enforcement point. The preparation stores the
   verdict, bound to the exact action and a state fingerprint, for 120 s. Execution claims it exactly once under a row
   lock and re-checks the fingerprint. Blue is asked once per key (#80, #87, #89).
7. **"How does a judge in the room not get the operator token?"** The browser never has it. The Next server adds it.
   The origin refuses non-Cloudflare IPs, and the WebSocket uses a 60 s single-use HMAC ticket. The site is public
   read-only (P7, live): a viewer can only GET or HEAD through the proxy, and only an admin cookie (HMAC-signed, from a
   constant-time key check) can act. Before P7, Cloudflare Access gated the site and the frontend re-verified its JWT.
8. **"Is per-agent token separation on in prod?"** Yes, since ~19:00Z on 2026-10-24: battlefield holds all three
   tokens and each agent container only its own (#108–#111). render-env refuses partial or duplicate sets.
9. **"Is the demo live?"** The attacker and blue's daily audit are live on prod. On prod the 90-second show plays a
   recording by default, because it only runs live when every agent is keyless (and a viewer always gets the recording). A judge's attack from the console
   hits the real backend, and the consoles follow the live run. Green runs keyless there.
10. **"How do you control model spend?"** A per-episode credit guard pauses the episode at `MAX_CREDITS_PER_EPISODE`,
    with exactly one more paid turn after a resume. Prod runs `MAX_CREDITS_PER_EPISODE=375000`; a live-red 10-day
    episode spends ~25k of red credits, plus ~4k a day for blue's live audit (counted by the guard from the deploy
    containing 6640354; before #176 it was recorded as 0). Lineages need their own cap (`prod-evolve` refuses without `MAX_CREDITS=`). One active run at a time.
11. **"How do you deploy and roll back?"** Merge to `main` builds five images tagged with the SHA. An approval-gated
    job renders `.env` from the `production` environment and rolls compose. Roll back with `git revert` + merge, or by
    re-running an older deploy run (README §17).
12. **"How did four people build this in a weekend without breaking each other?"** Through contracts first, CI
    ownership and changelog guards, extension points per team, everything runnable keyless, and an independent verifier
    on every core PR. The verifiers caught real bugs: same-key concurrent escalations and orphaned writes after restart
    (#52), and info leaks in debriefs (#62).
13. **"Why one VM and not Kubernetes or Cloudflare Containers?"** For one integrator on a 36-hour clock, Compose is the
    portable truth. README §13 records the trade-off. The in-process single-worker design is a known limit, listed above.
14. **"What would a real customer get?"** A measured answer to "would you let this agent pay bills, and with which
    controls": dollars extracted vs. blocked vs. false-positive cost, per rule, with readable reasons and a full audit
    trail.

---

## 10. Numbers sheet

| Number | Value | Source | Date |
|---|---|---|---|
| Live red turn (prod) | 11.2 s, 2,635 Factory credits, full attack | Finding (Ad), `contracts/CHANGELOG.md`; ep_568aef023d7c; #118 | 2026-10-24 ~21:05Z |
| Live blue audit (prod) | 3,806 and 4,109 credits, day 0 / day 1, `gpt-5.4-mini`, ep_f9c695b3144f | #78 | 2026-10-25 ~03:48Z |
| gemini-3.8-flash stall | stream timeout at 170 s; one `ToolSearch` after 80–140 s | same Finding | 2026-10-24 ~20:30Z on |
| Earlier live red (local, mock battlefield) | 14 s / 79 s turns, ~6.7k credits/turn, $11,004.37 extracted in 2 days, controller off, seed 34 | #9; Finding (Al) | 2026-10-24 |
| Blue `/gate` latency during a live audit (local stack) | p95 8.04 ms, max 56.6 ms, 1,817 samples, zero errors; session 9,834 credits | #119 | 2026-10-24 |
| Service loop responsiveness | worst gap and `/health` ≤ 50 ms during a 2 s tool freeze (old path ≥ 1.5 s); 300 turns, fds/threads flat | #79 | 2026-10-24 |
| Concurrency proofs | 3 or 12 parallel pays → 1 payment; 20 concurrent `gl.post` → 1 row; 5 concurrent identical prepared payments → 1 payment | #39, #89 | 2026-10-24 |
| Timeouts | `TURN_TIMEOUT_SEC` 180, stream 170, `GATE_TIMEOUT_SEC` 8, `ESCALATION_TIMEOUT_SEC` 90, preparation TTL 120, boot check 90 + 8 + 15 = 113 ≤ 120, headless escalation 5 s, busy-retry 10 s, lost-race wait 2 s | `docker-compose.yml`; `agentkit/agentkit/models.py:194`; `gatekeeper.py`; `orchestrator/agents.py:21` | main @ 119fbf6 |
| WS ticket | 60 s, single use, 16-hex-character nonce, HMAC-SHA256 | `battlefield/app/auth.py:33,219-274` | main |
| Access JWT (off on prod since P7) | RS256, 60 s skew, max 8,192 chars | `frontend/lib/access.ts` | main |
| Proxy timeouts | 30 s default, 300 s for `/step`, 10 s for ws-ticket | `frontend/lib/proxy.ts:9-11`; ws-ticket route | main |
| Cloudflare ranges in the origin lock | 22 (15 IPv4 + 7 IPv6), fetched 2026-10-24 | `deploy/Caddyfile:13-17` | main |
| Timescale bounds | `lock_timeout` 5 s, `statement_timeout` 120 s; `score_timeline` 1-minute buckets, 30-day start offset, 1-minute schedule | `battlefield/app/timescale.py` | main |
| prod.sh limits | HTTP 30 s, step 900 s, wait 3,600 s, lineage wait 7,200 s, 64 KiB argument cap, 5,000 events per page | `deploy/prod.sh:35-58`; PROD-OPS | main |
| Credit cap | 375,000 per episode on prod (`deploy/PROD-OPS.md` "Credit cap": 1.25 × 30 turns × 10k, from the older 6.7k–10k/turn measurement) | prod config; PROD-OPS | 2026-10-24 |
| Live-red recordings | off: $10,284.61 extracted, 0/10 caught; enforce: $1,824.22 extracted, 1/10 caught, $100 FP; 26,230 / 24,449 red credits; seed 42, 10 days | `docs/recordings/README.md` (#136) | 2026-10-24 ~22:30Z |
| Live-red lineage `ln_f52a3df83c8d` | 5 gens × 8 days, enforce, seeds 502–506; extracted $19,076 / $35,423 / $86,510 / $53,619 / $97,734; blocked $6,214 / $4,380 / $0 / $0 / $0; caught 3/7, 5/7, 2/8, 5/8, 1/8; red credits 20,402 / 20,744 / 22,831 / 22,974 / 22,313 (~109k) | lineage report (operator export, not committed) | 2026-10-24 |
| Tests (functions at 53adcb7) | agentkit 126, battlefield 392, red 103, green 107, blue 183 (Python total 911); frontend 202 in 27 files | `grep` of `def test_` / `it(`/`test(` | 2026-10-25 |
| Test pass counts in PRs (parametrized) | battlefield 555 (#151); blue 422 (#176); red 132 (#166); frontend 214 (#154) | PR bodies | 2026-10-25 |
| Contract size | 64 API paths; 23 tables | `contracts/ledger-api.yaml`, `contracts/schema.sql` | main |
| CI / CD jobs | ci.yml: `changes`, `contracts-guard`, `python` (×5), `battlefield-timescale`, `frontend`, `ownership-guard`; deploy.yml: `build` (×5), `roll` | workflow files | main |
| Commits on main | 153 | `git rev-list --count` at 53adcb7 | 2026-10-25 |
| Keyless 5-day generation | ~1.3 s | README §15 | main |
| Keyless **mock-agent** lineage ln_fbdfbd2d74cc (base seed 42, enforce, 5 days/gen) | Gen 1: 5/5 caught, $28,768 blocked, $0 extracted. Gen 2: 1/5 caught, $5,631 extracted. Gen 3: 5/5 caught, $8,663 blocked. Demo gens 4–5: 3/3 caught each | a keyless mock-agent lineage run (local) | 2026-10-24 |
| Early mock smoke (historical, pre-hardening) | seed 42, 4 days: enforce 4/4 caught, $26,023.14 blocked, $0 extracted; off $24,240.03 extracted | DEVLOG 2026-10-24T03:32Z | 2026-10-24 03:32Z. Don't use as a current number |
| Frontend first load | `/` ~104 kB first-load JS before the 3D chunk; ~57 fps at quality level 3 on an AMD Radeon 880M iGPU | `frontend/docs/architecture.md`, `performance-and-quality.md` | main |

### Contradictions found while writing (for Ad and R)
Items 1 (README part), 3, 4 and 5 (README part) are fixed by the companion repo-docs refresh
(`docs/refresh-repo-docs`); the rest stand until someone edits those files.
1. README §13, `deploy/OWNER-CHECKLIST.md` §2–§3 and the header of `docker-compose.prod.yml` describe Caddy serving
   `api.<domain>` → battlefield and the frontend on Cloudflare Pages. `deploy/Caddyfile` serves only `app.$DOMAIN`
   (`/api/ws` → battlefield, everything else → frontend), and its comment says battlefield's REST API has no public
   hostname. This doc follows the Caddyfile. The Caddyfile's own comments still say both routes are "behind Access",
   stale since P7.
2. `docker-compose.yml`'s header comment and `agentkit/agentkit/invocation.py`'s docstring still mention the green →
   blue mirror. D1 / #80 removed it (`contracts/agent-service.md` "Tokens").
3. AGENTS.md inv. 11 says blue's `audit_log` filter is "Not enforced". `battlefield/app/api/reads.py:134-148` enforces
   it server-side (#31).
4. `battlefield/AGENTS.md:63` still lists "one shared `AGENT_TOKEN`" as a known gap, stale since #109.
5. README §11 and OWNER-CHECKLIST suggest `MAX_CREDITS_PER_EPISODE` "e.g. 40". PROD-OPS says that pauses every
   episode after its first turn and recommends 375,000.
6. `deploy/PROD-OPS.md` says gemini red turns cost "about 7–9k" credits; the Finding (PR #9) measured ~6.7k.
