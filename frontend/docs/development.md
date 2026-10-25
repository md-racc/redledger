# Development

## Run

```bash
cd frontend
npm install
NEXT_PUBLIC_MOCK=true npm run dev      # no backend at all
npm run dev                            # with BATTLEFIELD_URL / OPERATOR_TOKEN (server-only) set: live episodes
```

Open <http://localhost:3000/>. `NEXT_PUBLIC_MOCK=true` is a build-time switch (it is read in client code), exactly like the
rest of the frontend; without it, "Run episode" tries the live battlefield first and falls back to the sample.

| URL | what |
|---|---|
| `/` | the arena |
| `/?q=0..3` | pin the render quality |
| `/?show=1` | start the 90-second show on load (`?show=live` / `?show=recorded` force its data source), see [show-mode.md](show-mode.md) |
| `/backstage`, `/backstage/{red,green,blue,battlefield}` | the raw consoles for the other laptops. Hidden: nothing links to them. See [backstage.md](backstage.md) |
| `/ops` | the original data-path dashboard (episodes, attacks, verdicts, escalations, thinking) |

Keys: `S` starts the show (`space` pauses, `←` `→` jump, `esc` leaves), `B` (or three quick clicks on the brand) opens the backstage in a new tab. Controls: scroll or the rail to tour; *Skip intro*; in the arena drag to orbit, click an agent for its
dossier (`Esc` closes), *Roster* lists every agent, *Run episode*, *Send agents in / back*, controller `off | shadow |
enforce`, *Auto-cam* (frames each fraud attempt), *Back to tour*.

## Checks

```bash
npm run typecheck && npm run lint && npm test && npm run build
```

`npm test` (vitest) has no browser or GPU:

| file | covers |
|---|---|
| `lib/arena/sim.test.ts` | nav grid facts (lagoon / hall / rotunda), a clear path from every spawn, column push-out, spawn on walkable ground, convergence onto slots, an extraction and a block scene, holding an attack until its outcome, dispersal |
| `lib/arena/director.test.ts` | event mapping, outcome without a launch, vendor freeze binding, rule aliases, dossier placeholders, live stats, overrides, vendor binding, per-day ledger tallies |
| `lib/arena/pacing.test.ts` | the scroll pacing curve: monotonic, invertible, dwell share per chapter, slow-vs-fast ratio |
| `lib/arena/show.test.ts` | the 90-second show: beat table, order, tour scroll, pause, jumps, captions (with a fake host) |
| `lib/arena/showScripts.test.ts` | the script runner (holds for a human), the controller-off projection, the escalation and its approve / block outcomes |
| `lib/arena/localAttack.test.ts`, `headlines.test.ts`, `pacer.test.ts`, `compare.test.ts` | the offline attack simulator by mode, feed headlines, the live event pacer, the compare pair |
| `lib/markdown.test.ts`, `lib/arena/report.test.ts`, `thinking.test.ts`, `provenance.test.ts`, `liveRuns.test.ts` | the markdown reader (no markup leaks), the report days and fallback summary, reasoning per agent, the LIVE / RECORDED badge, and the real-run summary against the recordings it came from |
| `lib/pitch.test.ts` | the pitch is two pages (word budget, four voices in order), names every sponsor, never says TimescaleDB runs in production, and says the numbers the Real run tab shows |
| `lib/voice/*.test.ts` | the voice feature: WAV encoder, the ElevenLabs call and its errors, the closest-scheme matcher (eight schemes, accents), the pause detector, the example sentences, the admin-only route |
| `components/backstage/derive.test.ts`, `raw.test.ts` | what the backstage consoles derive from the event stream; their event / traffic lines, which lines the arena's selection points at, the live checks |
| `lib/sync/hub.test.ts`, `lib/wsurl.test.ts` | the cross-laptop relay (state, ordering, sanitising, bounds, who is on stage); the same-domain socket address |
| `lib/reducer.test.ts`, `lib/proxy.test.ts`, `lib/access.test.ts` | the existing suites |

There are no automated browser tests; the visual path (intro, tour, arena, click-to-open, replay) was checked by hand in
the Claude browser pane.


## Connecting to the backend

The arena and the backstage consoles go through the same-origin proxy (`/api/bf/*`, token held server-side), and all four laptops use the **same domain**: the socket address is derived from the page host (`lib/wsurl.ts`) unless `NEXT_PUBLIC_WS_URL` is set to something else that is not localhost, and the cross-laptop relay (`/api/sync`, see [backstage.md](backstage.md)) is a route of the same server. Server-only env
(see `.env.example`): `BATTLEFIELD_URL`, `OPERATOR_TOKEN`, and `NEXT_PUBLIC_WS_URL` for the socket. The HUD says what it found:
**Ledger open · agents keyless** (the show may run live), **open** (live agents: the show stays on the recording to save credits),
**closed** (everything falls back to the recording and says "recorded").

No Docker? `tools/fake-battlefield.mjs` is a stand-in for the battlefield **contract** (episodes, start / step / pause, controller,
forced attacks, escalations that hold the day, ws tickets and `/api/ws` with `after_id` catch-up, lineages, the `/api/fe` reads the
consoles use). Its events are the recorded episode re-run per day by controller mode. It is **not the real gate**: use
`make mock-agents` whenever you can.

```bash
npm run dev:live        # fake battlefield on :8000 + next dev on :3000 already pointed at it (BF_PORT / FRONTEND_PORT to move them)
npm run fake:bf         # just the stand-in
```

What this was exercised against: the stand-in above (the full live path through the proxy: ticket, socket, create / step /
resolve / force-attack / controller). It has not been run against a real battlefield from this branch; the first thing to do on
the real stack is open `/backstage/battlefield` and watch the services panel, then run the show with `?show=live`.

## Debug handles

- `window.redledger` → `converge()`, `disperse()`, `select(id)`, `run(mode)`, `show()`, `debug()` (what the spotlight and auto-cam are looking at) (set by `ArenaExperience`)
- `window.__arena` → `project(id)` (agent screen position), `ids()`, `pos(id)`, plus `gl`, `scene`, `camera` while the
  canvas is mounted (set by `Picking.tsx`; handy for `gl.info` and for hiding groups when profiling)

## Regenerating the real-run summary

`node tools/gen-live-runs.mjs` reads `../docs/recordings/*.jsonl` (the live-red off/on pair, #136) and writes `public/mocks/live-runs.json` for
the Compare card's **Real run** tab. Numbers only. `lib/arena/liveRuns.test.ts` fails if the two drift apart.

## Regenerating the site data

```bash
python -I tools/gen-site-data.py /path/to/palace-of-fine-arts-3d/reference/plans/site_local.json \
                                 /path/to/gate5/manifest.json > lib/arena/siteData.ts
```

The manifest is `/assets/gate5/manifest.json` on the Palace project's live walkthrough site (2.7 MB). Then `npm test`: the nav
tests will tell you if a spawn is no longer reachable.

## Dependencies added

| package | why |
|---|---|
| `three`, `@react-three/fiber` (9), `@react-three/drei` (10) | the renderer and helpers (orbit controls, environment, performance monitor) |
| `@react-three/postprocessing`, `postprocessing` | bloom / tone mapping / grade / vignette / grain / SMAA |
| `three-mesh-bvh` | fast raycasts against the Palace for the ground-height grid |
| `zustand` | the small UI store (stage, hover, selection, sim phase) |
| `next` 15.0.3 → 15.5.28, `react` / `react-dom` RC → 19 stable | R3F 9 needs stable React 19 |
| fonts | `next/font/google`, three faces with one job each: **Cinzel** (Roman inscription capitals: the name, labels, buttons, rail numerals), **Bodoni Moda** (every sum of money, the chapter titles, captions in italic), **Jost** (the text you read; geometric, Futura family). Roman modernism: ivory on warm black, bronze hairlines, double rules around anything that holds information, Pompeian red, lapis, verdigris, gold. Rectangles, no radii, no blur, no glow. Colour is information: red fraud, blue controller, green client, gold a decision waiting. All in `app/arena.css` |

Cinzel, Bodoni Moda and Jost are fetched from Google Fonts at build time; a build with no network access needs them swapped for `next/font/local`.

## Troubleshooting

| symptom | likely cause |
|---|---|
| the loader never finishes | the glb failed *and* the fallback did not mount; check the console, `public/models/` and `public/basis/` |
| a stand-in palace appears | `public/models/*.glb` missing or a decode error (warning in the console names it) |
| agents do not move | the page is hidden or throttled (no `requestAnimationFrame`), or `converge()` was never called; try `window.redledger.converge()` |
| "Run episode" says backend offline | `BATTLEFIELD_URL` / `OPERATOR_TOKEN` unset or battlefield not running; it replays the sample on purpose |
| the dome never opens | the material names in a new glb no longer match `HIDE_IN_ARENA`, or `CUT_Y` is above the new model's columns |
| 502s in the console on first Run | expected without a backend: the proxy returns 502 and the arena falls back to the recording |
| the backstage laptops do not see the arena's selection | the relay is in one Node process: more than one `frontend` replica (or `next start` workers) splits it. Check LIVE CHECKS: `relay` and `arena laptop connected` |
| low frame rate | `?q=1`, then see [performance-and-quality.md](performance-and-quality.md) |
