# frontend/ — working guide for Dev R and any coding agent in this directory

Read the root `README.md` (§§1, 3, 5, 7) and `GIT.md` first. `FRONTEND-API.md` in this directory
documents every endpoint built for you.

## Your job

Everything a judge sees. The backend gives you an ordered event stream (WebSocket + REST
catch-up), a persisted per-episode state you can query any way you like (`/api/fe/...`), and a
control plane (start/pause/step, controller toggle, judge-selected attacks, escalation
approve/block). Presentation, information design, demo choreography and the pitch deck are
yours; nothing in the backend dictates look or tone.

## Boundaries

- You own `frontend/`. Branch prefix `frontend/`.
- You render from events and the `/api/fe` read API. You never read ledger tables and never
  need a database connection.
- Need a new aggregate or field? Ask Ad for a `/api/fe` endpoint, or open a `battlefield/` PR
  yourself with Ad as reviewer (`battlefield/app/api/frontend.py` is read-only SQL; adding an
  endpoint there is low-risk). Need a new event type? That's a `contracts/` PR.
- The browser never holds a token. Every REST call goes same-origin to `/api/bf/*`, a Next
  route handler that mirrors battlefield `/api/*` and adds `OPERATOR_TOKEN` server-side
  (`app/api/bf/[...path]/route.ts`). The socket uses a 60 s single-use ticket from
  `/api/bf/ws-ticket`. The app is private behind Cloudflare Access or a VPN for the hackathon;
  don't build user auth.
- **Never put a token in a `NEXT_PUBLIC_` var.** `NEXT_PUBLIC_*` referenced from client code is
  inlined into the JS bundle at build. Server-only vars (`BATTLEFIELD_URL`, `OPERATOR_TOKEN`)
  are read per request in route handlers (`dynamic = "force-dynamic"`), so one image serves
  every environment.

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
- `app/page.tsx` — the 3D arena front door (see `ARENA.md`). The old throwaway skeleton that proves the data path now lives at `app/ops/page.tsx` (`/ops`).

## Demo-critical surfaces (README §15)

1. Headline money panel (stolen / blocked / FP cost).
2. Controller toggle with visible mode (off / shadow / enforce). Note `shadow` still produces
   verdicts (with `enforced=false`): you can show "would have blocked" during the baseline run.
3. Attack cards from `attack.launched` + outcome from `attack.outcome`.
4. Verdict cards from `gate.verdict` (reason text is written for humans; rules_fired are ids).
5. Escalation modal: `escalation.opened` → approve/block via `api.resolve` → `escalation.resolved`.
6. Agent reasoning panels from `agent.thinking` (concatenate deltas per agent per day).
7. End-of-day report viewer: `report.posted` → `api.fe.report(id)` returns markdown.
8. Replay: `api.replays()` + `api.playReplay()` streams a recorded episode under a virtual
   episode id; same socket, same reducer. This is the stage fallback.
9. Compare view: `api.fe.compare(a, b)` for the same seed off vs enforce.

## Local loop

```
cd frontend && npm install
NEXT_PUBLIC_MOCK=true npm run dev            # zero backend, zero other env
# or against a battlefield (local `make mock-agents`, or the shared box); see .env.example:
BATTLEFIELD_URL=http://localhost:8000 OPERATOR_TOKEN=<operator token> NEXT_PUBLIC_WS_URL=ws://localhost:8000 npm run dev
npm run gen:api                              # regenerate REST types from contracts/ledger-api.yaml
```

## Conventions

- Next.js 15 app router, TypeScript strict, Tailwind. Add shadcn/ui or any library you want;
  note it in the PR. Design system, fonts, motion: your call.
- No global store beyond the reducer. Components take derived state.
- `npm run typecheck && npm run lint && npm test` must pass; CI runs them on `frontend/**` changes.

## Extension points (grow without a contracts PR)

See README §16. For the frontend specifically:
- Ad-hoc reads: `POST /api/fe/query {sql}` (single SELECT, 5 s cap) while exploring; promote stable queries to an `fe_*` extension route.
- Your own server-side routes on battlefield: `battlefield/extensions/fe_<name>.py` with `router = APIRouter()`, mounted at `/api/x/fe/...`. `fe_*` is the only prefix allowed to expose no-token public routes (a QR crowd page, a kiosk). `fe_example.py` shows the shape.
- Your own tables: `contracts/ext/fe/<nn>_<name>.sql`, prefixed `fe_`.
- Push into the sim: `POST /api/inputs {episode_id, target: red|blue|green, source, payload}` lands in that agent's next turn as `options.inputs`. Whether an agent reacts is up to Al/M; coordinate the payload shape with them in DEVLOG.
- Custom events: extensions can `bus.emit(..., "x.fe.<name>", {...})`; the reducer keeps them in `state.custom`.
CI allows exactly `frontend/`, `battlefield/extensions/fe_*.py`, `contracts/ext/fe/`, `DEVLOG.md` on a `frontend/` branch.

Crowd page sketch (not built): Next route `/play` → public `POST /api/x/fe/crowd/join` (team, project) and
`POST /api/x/fe/crowd/act` (side, action) → extension writes `fe_crowd_*` rows + an `inputs` row for red or blue +
`x.fe.crowd` event → red/blue read `options.inputs` and adapt → leaderboard from `fe_crowd_*`. All on your branch.

## Paste this to your coding agent as its first message

```
You are working in the Red Ledger repo, directory `frontend/`, as Dev R's coding agent.
Before any edit: read `frontend/AGENTS.md`, `frontend/FRONTEND-API.md`, `GIT.md` §7,
`README.md` §§0,1,3,7,16, and `contracts/events.md`. Confirm `git branch --show-current`
starts with `frontend/`; if not, create `frontend/<topic>` from origin/main. Edit only inside
`frontend/`, `battlefield/extensions/fe_*.py`, `contracts/ext/fe/`, and append to `DEVLOG.md`.
Never force-push, never merge, never touch another directory; if you need a new event type,
write the proposal into the PR description and stop. `npm run typecheck && npm run lint && npm test`
before each push. Everything must work with NEXT_PUBLIC_MOCK=true against public/mocks/sample.jsonl.
Goal for this session: <fill in>
```

## Don't

- Don't poll `/api/events` in a loop when the socket is available; use the socket and catch up once.
- Don't compute scores client-side; `score.updated` is authoritative.
- Don't show `origin` to the audience during the live run; it's the ground truth the agents
  don't have. (It's available in `/api/fe` for the reveal and the compare view.)
