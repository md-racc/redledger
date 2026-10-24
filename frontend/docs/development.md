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
| `/ops` | the original data-path dashboard (episodes, attacks, verdicts, escalations, thinking) |

Keys and controls: scroll or the rail to tour; *Skip intro*; in the arena drag to orbit, click an agent for its
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
| `lib/reducer.test.ts`, `lib/proxy.test.ts` | the existing suites |

There are no automated browser tests; the visual path (intro, tour, arena, click-to-open, replay) was checked by hand in
the Claude browser pane.

## Debug handles

- `window.redledger` → `converge()`, `disperse()`, `select(id)`, `run(mode)` (set by `ArenaExperience`)
- `window.__arena` → `project(id)` (agent screen position), `ids()`, `pos(id)`, plus `gl`, `scene`, `camera` while the
  canvas is mounted (set by `Picking.tsx`; handy for `gl.info` and for hiding groups when profiling)

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
| fonts | `next/font/google`: Anton (title lockup, HUD numbers), Instrument Serif (chapter titles, dossier quotes) and IBM Plex Serif (all the small text: HUD, labels, data rows; `--mono` in `app/arena.css`, falling back to Georgia). To change the small font, change that one variable |

Anton, Instrument Serif and IBM Plex Serif are fetched from Google Fonts at build time; a build with no network access needs them swapped for `next/font/local`.

## Troubleshooting

| symptom | likely cause |
|---|---|
| the loader never finishes | the glb failed *and* the fallback did not mount; check the console, `public/models/` and `public/basis/` |
| a stand-in palace appears | `public/models/*.glb` missing or a decode error (warning in the console names it) |
| agents do not move | the page is hidden or throttled (no `requestAnimationFrame`), or `converge()` was never called; try `window.redledger.converge()` |
| "Run episode" says backend offline | `BATTLEFIELD_URL` / `OPERATOR_TOKEN` unset or battlefield not running; it replays the sample on purpose |
| the dome never opens | the material names in a new glb no longer match `HIDE_IN_ARENA`, or `CUT_Y` is above the new model's columns |
| 502s in the console on first Run | expected without a backend: the proxy returns 502 and the feed falls back |
| low frame rate | `?q=1`, then see [performance-and-quality.md](performance-and-quality.md) |
