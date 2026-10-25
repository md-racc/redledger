# Frontend

`frontend/` is a Next.js 15 app (app router, TypeScript strict, Tailwind, React Three Fiber, no shadcn/ui). It renders from the
battlefield event stream and the `/api/fe` read API, never touches a database, and the browser never holds a token. Events are
defined in `contracts/events.md`; the code wins over this file.

## What the site shows

| Route | What it is |
|---|---|
| `/` | The 3D arena: a flight over the Palace of Fine Arts, a five-chapter scroll tour of the three teams, then the rotunda where 30 agent figures act out the run. The HUD holds the money tiles, the controller toggle, the attack console, escalation cards and the Compare / Evolution / Report / Lenders cards. `S` (or `?show=1`) plays the 90-second show and `?pitch=1` starts pitch mode on a live episode. The show runbook is in `OPERATIONS.md`. |
| `/ops` | A plain data-path page: reducer state from the socket or the fixture, with admin-only controls. It's useful for debugging, not for the stage. |
| `/backstage`, `/backstage/[team]` | Raw consoles for the other laptops (`red`, `green`, `blue`, `battlefield`), all monospace with no styling. They're evidence that the backend is running, not a dashboard. Nothing links to them. |
| `/report/[ep]` | The printable controls assessment for one run, built from `GET /fe/episodes/{ep}/controls` (`components/report/`). Viewers see it only once the run is final. |
| `/admin` | The admin login, which posts `ADMIN_KEY`. Nothing links to it. |

Every window joins the active run on load (`lib/arena/useActiveRun.ts`) and never creates one for a viewer.

## Data flow

```
battlefield ──WS (ticket) / REST fallback──► lib/ws.ts ─┐
public/mocks/*.jsonl ───────► lib/mock.ts ───────────────┤
                                                         ▼
                                        useFeed (lib/arena/useFeed.ts)
                                         ├─ lib/reducer.ts ─► UIState ─► HUD, cards, dossier, consoles
                                         └─ subscribe(event) ─► Director ─► ArenaSim ─► figures
```

- **Proxy.** REST goes same-origin to `/api/bf/<path>`, which `app/api/bf/[...path]/route.ts` + `lib/proxy.ts` forward to
  `${BATTLEFIELD_URL}/api/<path>`, adding `Authorization: Bearer $OPERATOR_TOKEN` on the server. Headers pass through an
  allowlist, so the browser's `Authorization`, cookies and `X-Agent` never reach battlefield. Errors: `502` (unconfigured or
  unreachable), `504` (timeout: 30 s, 300 s for `POST /episodes/{id}/step`), `400` (`..` or encoded slashes), `403` (cross-site
  mutation).
- **WebSocket ticket.** `GET /api/bf/ws-ticket?episode_id=` (which calls battlefield `POST /api/ws/ticket`) returns
  `{ticket, expires_at, ws_url}`: valid 60 s, single use, scoped to the episode. `lib/ws.ts` opens
  `${ws_url}/api/ws?episode_id=&ticket=&after_id=` and fetches a fresh ticket before every reconnect (close `4401` = bad
  ticket), resuming from `after_id`. With `NEXT_PUBLIC_WS_URL` unset the address comes from the page host (`lib/wsurl.ts`).
- **REST fallback (#212).** When two socket attempts in a row deliver nothing (a venue network drops the upgrade, the dev
  server has no `/api/ws`), `lib/ws.ts` polls `GET /events?after_id=` through the proxy every 1.5 s until a socket frame
  arrives. Refusals (400/401/403/404) aren't worked around. Status lines say "via REST (socket blocked)".
- **Reducer.** `lib/reducer.ts` folds every event into `UIState` and is idempotent on catch-up (it skips ids it has already
  seen). The socket, the REST fallback, fixture replay and the show all feed the same function. Event-derived state lives
  only there. Two zustand stores hold UI-local state: `lib/arena/store.ts` (stage, panel, hover and selection, auto-cam) and
  `lib/role.ts` (viewer or admin).
- **Scores.** Live scores come only from `score.updated`. A few files compute projected or offline numbers, labelled as such
  in the UI (for example the Compare card's controller-off projection in `lib/arena/compare.ts` and the no-backend attack
  script in `lib/arena/localAttack.ts`).
- **Replay.** `POST /replays/{id}/play` re-emits a fixture as a real, persisted episode with id `replay_<fixture>_<8hex>`. Its
  events are in `/api/events` like any other, and the frames carry no `replay` flag (`RLEvent.replay` is optional and unset).
- **Mock mode.** With `NEXT_PUBLIC_MOCK=true` (a build-time switch read by `lib/arena/useFeed.ts` and `app/ops/page.tsx`), the
  app replays `public/mocks/sample.jsonl` with no backend and no other env. Without mock mode, "Run episode" goes live when a
  battlefield answers and otherwise says so and replays the sample.
- **Viewers and admins.** The site is public and read-only. Anyone is a **viewer**. A browser that logged in at `/admin` with
  `ADMIN_KEY` is an **admin**, holding the `rl_admin` cookie (HttpOnly, SameSite=Strict, 7 days, HMAC-keyed by `ADMIN_KEY`).
  This is enforced on the server in `lib/admin.ts`:
  - For viewers, the proxy forwards GET/HEAD only (`403 {"error":"viewer"}` otherwise) and rate-limits them per address
    (`lib/ratelimit.ts`). A viewer's ws-ticket must name an episode.
  - The proxy refuses viewers the reads that reveal which rows are red's (`OPERATOR_ONLY` in `lib/proxy.ts`):
    `/attacks*`, `/audit_log`, `/state*`, `/fe/compare`, `/fe/episodes/{ep}/attacks`, `.../entities/*`, `.../state/*`,
    `.../verdicts/rules|confusion` and `/lineages/{id}/export`.
  - The proxy strips `origin`, `entity_origin` and `origin_of_source` from every other JSON answer a viewer gets
    (`stripGroundTruth`). `/fe/episodes/{ep}/controls` reaches viewers only once `final` is true.
  - `/api/sync` and `POST /api/voice/transcribe` are admin-only.
  - With `ADMIN_KEY` unset, everyone is admin under `next dev`. In production nobody is, and a key shorter than 32
    characters counts as unset.

  The UI reads `useRole()` and disables what a viewer can't do.
- **Cloudflare Access (optional).** When both `CF_ACCESS_TEAM_DOMAIN` and `CF_ACCESS_AUD` are set, `middleware.ts` (with
  `lib/access.ts`) requires a valid Access JWT on every request and returns `403 {"error":"forbidden"}` otherwise. Both are blank
  on prod, local and CI, so the check is off.

## Key components

**Arena and the Palace model.** `app/page.tsx` loads `ArenaClient` (`next/dynamic`, `ssr: false`), which loads
`ArenaExperience`: the stage machine (`loading → intro → scroll ⇄ arena`), the feed, and `window.redledger`
(`converge`, `disperse`, `select`, `run`, `show`, `pitch`). The `<Canvas>` holds the Palace, `ArenaWorld` (sim loop, 30 figures),
`CameraRig`, `Picking` and post-processing; DOM overlays sit above it.

Per-frame data bypasses React: `lib/arena/sim.ts`, `timeline.ts`, `popBus.ts` and the `figures` map feed overlays that write
CSS variables directly.

The Palace is two meshopt/KTX2 glb files (`public/models/palace-arch.glb`, 4.6 MB, and `palace-ground.glb`, 2.0 MB) with the
Basis transcoder in `public/basis/`. They are albedo only, and `Atmosphere.tsx` lights them. Coordinates are metres, with the
origin at the centre of the rotunda floor and the lagoon toward −Z.

Pathfinding is A\* on a 1 m grid (`lib/arena/nav.ts`); columns are circles agents are pushed out of. `lib/arena/siteData.ts` is
generated by `tools/gen-site-data.py` (not part of the build), and a stand-in palace is built from it if the glb fails.

In the arena a clipping plane cuts everything above 11 m, and the dome and inner piers fade out (`cutaway.ts`). Licence and
credit are in `frontend/public/models/ATTRIBUTION.md`.

**Agents and events.** The 30 figures are defined in `lib/arena/roster.ts`:

- **8 fraudsters**, `red:<scheme_id>`, one per built scheme.
- **10 guards**, `blue:<rule_id>`, one per gate rule. Aliases cover the mock blue's ids, and an unknown rule still maps to a
  stable guard.
- **12 clients**, `green:client_01..12`, bound to entities by a stable hash. The top 12 vendors by spend fill these slots when
  the vendor read answers.

Figures are built in code (`components/arena/figures.ts`): a team base plus a role kit per scheme, rule or client trade.

`lib/arena/director.ts` maps events to animation: `attack.launched` walks the fraudster up to its client; `gate.verdict`
pulses the guard for `rules_fired[0]` on a block (`WOULD BLOCK` in shadow mode), amber on escalate, a client on allow;
`attack.outcome` streams coins to the fraudster or sends a guard to catch it; `vendor.frozen`/`unfrozen` ices or thaws a client.

Money, mode and escalations come from reducer state. The escalation card says in plain words what's about to happen and why
(`lib/arena/escalation.ts`), with approve and block for admins.

**Camera and tour.** All camera work is in `components/arena/CameraRig.tsx`, and chapter positions are in
`lib/arena/timeline.ts`:

- **Intro.** A 7.5 s Catmull-Rom flight (5.8 s in the show) ends on the establishing shot. The projection is offset so the
  rotunda lands in the gap of the "red ledger" title.
- **Scroll tour.** A 780vh spacer drives a rail through five chapters; `lib/arena/pacing.ts` slows the camera in each
  chapter's reading zone and speeds it about 12x between them.
- **Arena.** Orbit controls take over (zoom off, so the wheel still scrolls back up); selecting an agent dollies in to 26 m.
- **Auto-cam.** `lib/arena/cinema.ts` cuts in on each fraud scene and eases back out; it yields to drags and selection.
- **Portrait screens** widen the lens and pull the camera back; under 760 px the HUD has a phone layout.
- **Editing.** Waypoints are the `INTRO` and `RAIL` arrays in `CameraRig.tsx`. If you move one, move its chapter `at` in
  `timeline.ts` and the banner window in `LabelLayer.tsx` too.

**Dossier modal.** Clicking an agent, or picking it in the HUD roster, opens `components/arena/overlays/AgentModal.tsx`, with
content from `lib/arena/details.ts`. `Picking.tsx` raycasts each figure's pick cylinder (falling back to the nearest head within
30 px); a drag never selects.

Values come from `UIState`, then the catalogs (`GET /schemes`, `GET /fe/episodes/{ep}/vendors?sort=spend`), then the host's
`agentDetails` overrides; later layers win.
A row with no value shows a dashed `○ <source>` pill naming its endpoint or event field. The modal also shows the team agent's
runtime (`lib/arena/runtime.ts`: Droid model from `GET /health`, "keyless (DRY_RUN)" for a dry-run agent, Factory credits from
`turn.ended`, last turn summary), the newest two days of `agent.thinking`, and a raw JSON toggle. `true_blocks`, `false_blocks`, `ein` and
`bank` are never filled live.

**Verdicts.** Verdicts show as guard pulses, money tiles and the ledger crown, and as raw lines on `/backstage/blue` (rule
board, flags, freezes, escalations). Its confusion matrix is the one place the UI shows `origin`, and only to admins.

**Backdrop.** `components/arena/Backdrop.tsx` draws the ledger crown (72 bars on an arc, one wedge per day: allowed, blocked,
stolen, tallied from the reducer in `lib/arena/ledgerStats.ts`) plus distant skyline, searchlights and motes.

**Evolution card.** `components/arena/overlays/EvolutionCard.tsx` shows the lineage report as a strip of generations: what red
tried, what blue caught, and what each agent rewrote in its playbook. It's paced by the show's clock, or shown all at once in
free play. `lib/arena/lineage.ts` picks the source (#215):

1. `?lineage=<id>`
2. The pinned showcase lineage `ln_f52a3df83c8d`
3. If that lineage isn't on this battlefield, the newest finished lineage
4. With no backend, the synthetic sample `public/mocks/lineage-report.json`, labelled as such

**Compare card.** `components/arena/overlays/CompareCard.tsx` puts the controller-off run beside the controller-on run, with
the numbers counting up in sequence. The pair comes from the runs finished this session (`lib/arena/compare.ts`). When there is
no real controller-off run, the off side is a labelled projection: the same attacks with nothing gating them.
`GET /fe/compare` is the backend version and is admin-only.

**Report card and controls report.** The HUD's Report card shows blue's end-of-day markdown (`report.posted` →
`GET /reports/{id}`), rendered by the safe reader in `lib/markdown.ts`. With no backend it shows a summary built from the day's
events (`lib/arena/report.ts`). `/report/[ep]` is the full controls assessment (`components/report/`, `lib/report/`).

**Lenders card.** `LendersCard.tsx` shows what five large US lenders have said about outside AI agents, each line sourced
(`lib/arena/lenders.ts`, checked against `frontend/docs/lenders.md`).

**Backstage consoles.** Each console in `components/backstage/` prints a header, seven `[ OK ]`/`[FAIL]` live checks
(`raw.ts`, including whether events arrive by websocket or REST fallback), the demo screen's selection, every proxied API call,
raw team events, derived state (`derive.ts`) and the raw `/api/fe` reads. It follows the running episode, else the newest,
from `after_id=0`, and switches to the recorded loop only when the backend is really gone (a refusal is still an answer).

The laptops share one in-memory relay (`lib/sync/hub.ts`, `POST /api/sync`, `GET /api/sync/stream` SSE with a polling fallback).
It's admin-only, and it holds only as long as there is exactly one `frontend` replica.

Keys: `1`–`4` switch team, `0` lists consoles, `A`/`Esc` returns to the arena; in the arena an admin opens backstage with `B`.
The door hosts `red.<site>` and `blue.<site>` are rewritten to `/backstage/red` and `/backstage/blue` (`next.config.ts`,
`lib/backstage/alias.ts`), and `gate.ts` makes them a 404 for anyone who isn't an admin. With no battlefield, or with
`?replay=1`, these consoles replay `public/mocks/demo-enforce-live.jsonl`. A test keeps that file identical to its source in
`docs/recordings`.

**Voice (ElevenLabs speech-to-text, admin-only).** In the attack console, an admin can speak or type a fraud scheme in any
language:

1. The browser records 16 kHz mono WAV (`lib/voice/recorder.ts`, `wav.ts`). Recording stops itself after 1.6 s of quiet
   (`lib/voice/vad.ts`) or at 45 s.
2. `POST /api/voice/transcribe` sends the audio to ElevenLabs Scribe, which returns `{text, language}`.
3. `lib/voice/intent.ts` keyword-matches the text against red's eight schemes in about a dozen languages. It isn't an LLM or a
   translator, and the console offers a dropdown to change the match.
4. Launching sends `POST /inputs {target: red, payload: {kind: "custom_fraud_scheme", text, language, closest_built_in}}`,
   then `POST /episodes/{id}/attack {scheme_id}`.

Red reads the words as quoted data and uses them to set the forced scheme's parameters. It never runs anything outside its
catalog, so don't claim that red invents a scheme from the words.

A viewer gets `403` before the key is touched; audio is capped at 3 MB and 20 requests a minute per process, and isn't stored.
Without `ELEVENLABS_API_KEY`, typing still works.

## Battlefield /fe API used by the site

Paths are relative to `/api/bf` (mirroring battlefield `/api`); money is in dollars; `lib/api.ts` wraps every call. Viewer
column: "admin" = refused to viewers, "final" = viewers get it once the run is final.

| Route | Returns | Viewer |
|---|---|---|
| `GET /fe/episodes/{ep}/snapshot` | Company at a glance: cash, vendors, AP, controls, exposure, score | yes |
| `GET /fe/episodes/{ep}/timeline` | One row per day: cash, verdict counts, cumulative extracted and blocked, attacks, flags | yes |
| `GET /fe/episodes/{ep}/ap_aging` | AP buckets `current`, `1-30`, `31-60`, `60+` | yes |
| `GET /fe/episodes/{ep}/entities/{type}/{id}` | An entity plus every verdict, escalation, flag, audit row and event that touched it | admin |
| `GET /fe/episodes/{ep}/vendors?sort=risk\|spend\|name\|newest` | Vendor profiles with derived risk signals (`origin` stripped for viewers) | yes |
| `GET /fe/episodes/{ep}/attacks` | Every declared attack with its invoices, expenses, verdicts and flags | admin |
| `GET /fe/episodes/{ep}/attacks/leaderboard` | Per scheme: attempts, extracted, targeted, caught, latency | yes |
| `GET /fe/episodes/{ep}/verdicts?verdict=&action=&day=&rule=` | Filterable verdict list (`entity_origin` stripped for viewers) | yes |
| `GET /fe/episodes/{ep}/verdicts/rules` | Counts by rule, verdict and origin | admin |
| `GET /fe/episodes/{ep}/verdicts/confusion` | Counts and dollars by verdict and origin | admin |
| `GET /fe/episodes/{ep}/agents/activity` | Per agent per day: calls, ok, blocked; credits and seconds per turn | yes |
| `GET /fe/episodes/{ep}/agents/{agent}/thinking?day=` | Thinking text concatenated per day | yes |
| `GET /fe/episodes/{ep}/feed?after_id=` | Card-worthy events with a composed `headline` and `subline` | yes |
| `GET /fe/episodes/{ep}/search?q=` | Free-text matches `[{kind, id, label, status}]` | yes |
| `GET /fe/episodes/{ep}/reports`, `GET /reports/{id}` | Report list with previews, and the full markdown | yes |
| `GET /fe/episodes/{ep}/escalations` | All escalations joined with their verdicts | yes |
| `GET /fe/episodes/{ep}/controls` | The controls assessment behind `/report/[ep]`: per-rule controls, schemes, gaps, false positives, the lost-money split (null for replays), `final` | final |
| `GET /fe/compare?a=&b=` | Two episodes side by side, with deltas on the three money numbers | admin |
| `GET /fe/lineages/{id}/report`, `/timeline` | The evolution report and the playbook-version timeline | yes |

The site also uses these routes through the same proxy:

- **Control plane (admin):** `POST /episodes`, `/episodes/{id}/start|pause|resume|step`, `PATCH /episodes/{id}/controller`,
  `POST /episodes/{id}/attack`, `POST /escalations/{id}/resolve`, `POST /replays/{id}/play` and `POST /inputs`.
- **Reads:** `GET /episodes`, `/episodes/{id}`, `/episodes/{id}/score`, `/schemes`, `/escalations`, `/replays`, `/lineages`,
  `/health` and `/events?after_id=`.

Battlefield's live schemas are at `${BATTLEFIELD_URL}/docs`.

## Development

```bash
cd frontend && npm ci
NEXT_PUBLIC_MOCK=true npm run dev   # zero backend: replays public/mocks/sample.jsonl
npm run dev:live                    # tools/fake-battlefield.mjs + the app pointed at it, live path without Docker
BATTLEFIELD_URL=http://localhost:8000 OPERATOR_TOKEN=<op> NEXT_PUBLIC_WS_URL=ws://localhost:8000 npm run dev   # against make mock-agents
npm run typecheck && npm run lint && npm test   # tsc --noEmit, next lint, vitest; CI runs all three
```

`npm run fake:bf` runs the stand-in battlefield alone. Under `dev:live` other laptops can open port 3104 over the LAN; the dev
server has no `/api/ws`, so they read events over REST.

**Environment** (`frontend/.env.example`):

| Variable | Scope | Purpose |
|---|---|---|
| `BATTLEFIELD_URL`, `OPERATOR_TOKEN` | Server, read per request | Proxy target and bearer |
| `ADMIN_KEY` | Server | Admin login. Needs at least 32 characters in production. |
| `ELEVENLABS_API_KEY`, `ELEVENLABS_STT_MODEL` (default `scribe_v2`), `ELEVENLABS_API_BASE` | Server | Voice transcription |
| `CF_ACCESS_TEAM_DOMAIN`, `CF_ACCESS_AUD` | Server | Optional Access JWT check. Blank on prod. |
| `NEXT_PUBLIC_WS_URL` | Server, read at runtime | Socket base, handed to the browser as `ws_url` |
| `NEXT_PUBLIC_MOCK` | Build time | `true` gives fixture replay with no backend |

Never put a token in a `NEXT_PUBLIC_*` variable; those are inlined into the bundle.

**Fixtures** (`public/mocks/`): `sample.jsonl` (mock mode), `demo-enforce-live.jsonl` (door consoles), `pitch-fallback.jsonl`,
`lineage-report.json` (Evolution sample), `controls-report.json` (report sample), `live-runs.json` (recorded real runs).

**Tests** are vitest, colocated as `*.test.ts(x)`. Some read `frontend/docs/lenders.md`, `pitch-script.md`, `sponsors.md`,
`docs/recordings/` and `public/mocks/`, so keep those paths.

## Performance notes

- **Quality ladder.** `lib/arena/quality.ts` defines levels 3 to 0, applied in `Scene.tsx`. Each level reduces pixel ratio
  (1.5 down to 1), shadow size and refresh rate (every 2nd, 3rd or 6th frame, then off) and the post chain (full chain, then
  bloom plus tone mapping, then none). Phones and coarse pointers start at 2.
- **Overrides.** `?q=0..3` pins a level. Without it, `lib/arena/governor.ts` steps down after 4 s under 24 fps and back up at
  most twice after 10 s at 52 fps or more. It ignores the first 6 s and any long hitch. `document.documentElement.dataset.quality`
  shows the current level.
- **Cost.** About 1.7M triangles and 480 draw calls per frame with shadows; 6.6 MB of glb; about 57 fps at level 3 on an AMD
  Radeon 880M iGPU; `/` is about 104 kB first-load JS before the 3D chunk.
- A hidden or viewport-emulated pane throttles `requestAnimationFrame` (about 3 fps); test at the real window size.
- On touch devices, orbit controls own arena gestures; *Back to tour* or the chapter rail scrolls back up.

## Known issues

- **Verdict cause isn't rendered.** The UI ignores `gate.verdict.cause` and `escalation.opened.cause`, so a fallback block
  (blue unreachable) looks exactly like a control block. Don't narrate a fallback block as blue catching fraud.
- **API types are hand-written.** `lib/types.ts` and `lib/api.ts` are mostly `any` for `/fe/*`. `contracts/ledger-api.yaml`
  covers only 3 of about 16 `/fe/*` routes, so `npm run gen:api` doesn't help yet.
- **`frontend/tsconfig.tsbuildinfo` is committed.** It should be untracked and added to `.gitignore`.
- **The sync hub is per process.** A second `frontend` replica would split the laptops' relay.
