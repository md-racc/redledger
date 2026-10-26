# frontend/ — maintenance guide (original author: R)

Read the root `README.md` and `docs/CONTRIBUTING.md` first. `docs/FRONTEND.md`
documents every endpoint built for you.

## Your job

The arena, reports and local showcase. The backend gives you an ordered event stream (WebSocket + REST
catch-up), a persisted per-episode state you can query any way you like (`/api/fe/...`), and a
control plane (start/pause/step, controller toggle, judge-selected attacks, escalation
approve/block). Preserve the event-driven rendering and local replay.

## Browser and API boundaries

The browser holds neither agent nor operator tokens. REST goes through the same-origin
`/api/bf/*` server proxy; WebSocket uses a 60-second single-use ticket. Never put a secret in
`NEXT_PUBLIC_*`, which is bundled into client JavaScript. API types are generated from
`contracts/ledger-api.yaml` with `npm run gen:api`; do not hand-edit generated API types.
Components consume derived state; WebSocket and replay feed the same event reducer.

## Cloudflare Access check at the origin

`middleware.ts` (+ `lib/access.ts`) verifies the Cloudflare Access JWT on every request except
`/_next/static`, `/_next/image` and `/favicon.ico`: RS256 against
`https://$CF_ACCESS_TEAM_DOMAIN/cdn-cgi/access/certs`, `iss` = `https://$CF_ACCESS_TEAM_DOMAIN`,
`aud` ∋ `$CF_ACCESS_AUD`, `exp`/`nbf` with 60 s skew. Token from `Cf-Access-Jwt-Assertion`, else
the `CF_Authorization` cookie. Failure → `403` (`{"error":"forbidden"}` under `/api/*`, plain
`forbidden` elsewhere). Why: the Caddy IP allowlist admits any Cloudflare zone, including one an
attacker points at our origin IP; only our Access app can mint this JWT. Both vars unset → check
off (local dev, mock, CI; one warning at startup in production). Never log the token or claims.

## Viewers and admins

Server-enforced in `lib/admin.ts`. `/admin` posts `ADMIN_KEY` (server env, never `NEXT_PUBLIC_`) to
`POST /api/admin/login`, which sets `rl_admin` (HttpOnly, SameSite=Strict, Secure in production, 7 days,
HMAC-SHA256 keyed by `ADMIN_KEY`; rotating the key logs everyone out). `POST /api/admin/logout` clears it,
`GET /api/whoami` → `{role}`. The `/api/bf` proxy lets a viewer GET/HEAD only (anything else → `403
{"error":"viewer"}` before battlefield is contacted) and rate limits viewers per address
(`lib/ratelimit.ts`; ws-ticket too, which must name an episode for a viewer). The proxy also keeps ground truth from viewers: reads
that say which rows are red's are admins-only (`OPERATOR_ONLY` in `lib/proxy.ts`) and `origin` keys are stripped from every other JSON
a viewer reads (`stripGroundTruth`); a new screen that needs one of those reads is an admin screen. `/api/sync` (both ways) and
`POST /api/voice/transcribe` (it spends the speech credits) are admin-only, and any new
route that calls a paid or external service must be too. Failed logins are capped per address and
globally (20/min, then every login 429s until the minute ends); open `/api/sync/stream`s are capped at 500.
`ADMIN_KEY` unset: everyone is admin outside production (`next dev`, mock dev); in production (`NODE_ENV=production`)
nobody is, and a key under 32 characters counts as unset; a runtime `NEXT_PUBLIC_MOCK` is never trusted. The UI reads `useRole()` (`lib/role.ts`) and disables what a
viewer can't do; every window (arena, backstage, /ops) joins the active run on load
(`lib/arena/useActiveRun.ts`) and never creates one for a viewer.

## Data model in one paragraph

An **episode** is one run (seed + controller mode). Each **day**: legit traffic arrives, red
launches an **attack** (a story + target $), green works the AP queue (every money-moving call
produces a **verdict** from blue: allow / block / escalate), blue audits (raises **flags**,
freezes vendors, posts a **report**), scoring updates. `lib/reducer.ts` folds the event stream
into `UIState`; `lib/types.ts` has the shapes; `contracts/events.md` is the authority.

## What's already wired

- `app/api/bf/[...path]/route.ts` + `lib/proxy.ts` — server-side proxy `/api/bf/<path>` →
  `${BATTLEFIELD_URL}/api/<path>` with the operator bearer; streams responses; 30 s upstream
  timeout (300 s for `POST /episodes/{id}/step`); 502 JSON if unconfigured/unreachable.
- `app/api/bf/ws-ticket/route.ts` — `GET ?episode_id=` → `{ticket, expires_at, ws_url}`.
- `lib/ws.ts` — reconnecting socket with `after_id` catch-up; fetches a fresh ticket before
  every (re)connect and takes the socket URL from `ws_url`.
- `lib/reducer.ts` — idempotent reducer; `lib/reducer.test.ts` shows the pattern.
- `lib/api.ts` — every REST route, including `/api/fe/*`, via the same-origin proxy. No token.
- `lib/mock.ts` + `public/mocks/sample.jsonl` — fixture replay with `NEXT_PUBLIC_MOCK=true`.
- `app/page.tsx` — the 3D arena front door (see `docs/FRONTEND.md`). The operator console lives at `app/ops/page.tsx` (`/ops`).

## Local loop

```
cd frontend && npm install
NEXT_PUBLIC_MOCK=true npm run dev            # zero backend, zero other env
# or against a battlefield (local `make mock-agents`, or another explicitly configured backend); see .env.example:
BATTLEFIELD_URL=http://localhost:8000 OPERATOR_TOKEN=<operator token> NEXT_PUBLIC_WS_URL=ws://localhost:8000 npm run dev
npm run gen:api                              # regenerate REST types from contracts/ledger-api.yaml
```

## Conventions

- Next.js 15 app router, TypeScript strict, Tailwind. Document any new dependency and its purpose in the PR.
- No global store beyond the reducer. Components take derived state.
- `npm run typecheck && npm run lint && npm test` must pass; CI runs them on `frontend/**` changes.

## Evolution / lineages

Lineages are chains of episodes in which the agents evolve (docs/ARCHITECTURE.md (Evolution)). For the evolution view:
- `GET /api/bf/fe/lineages/{id}/timeline`: playbook versions with diffs, generation scores, in order.
- `GET /api/bf/fe/lineages/{id}/report`: the evolution report (scores per generation, red tactic
  mix, blue rules incl. `learned:*`, who-beat-whom matrix, playbook diffs).
- Fixtures for mock mode: `battlefield/fixtures/lineages/sample-{timeline,report}.json`.
- Events in a lineage episode: `generation.started|ended`, `playbook.updated`, `debrief.delivered`
  (counts only), `lineage.paused|resumed` (`contracts/events.md`).
- The demo episode is the lineage's next generation; `generation.started.playbook_versions` tells
  you how evolved the agents are. Contract: `contracts/agent-service.md` (Lineages); runbook and design: `docs/ARCHITECTURE.md` (Evolution).

## Don't

- Don't poll `/api/events` in a loop when the socket is available; use the socket and catch up once.
- Don't compute scores client-side; `score.updated` is authoritative.
- Don't show `origin` to the audience during the live run; it's the ground truth the agents
  don't have. (It's available in `/api/fe` for the reveal and the compare view.)

## Maintenance validation

Follow root `AGENTS.md` and `docs/CONTRIBUTING.md`; historical team prefixes are no longer path restrictions.
Preserve browser token isolation and the `NEXT_PUBLIC_MOCK=true` path. Run
`npm run typecheck && npm run lint && npm test` in `frontend/`; build mock mode for UI changes.
