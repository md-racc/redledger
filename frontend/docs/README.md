# redledger frontend: documentation

The frontend's front door (`/`) is a cinematic 3D experience: a flight over the Palace of Fine Arts, a scroll tour of
the three factions, and an arena where 30 agents converge on the rotunda and can be clicked for a dossier. The previous
data-path dashboard still lives at `/ops`.

| Doc | Read it for |
|---|---|
| [architecture.md](architecture.md) | the stage machine, the render loop, the file map, how state flows without re-rendering at 60 Hz |
| [agents-and-events.md](agents-and-events.md) | who the 30 agents are, the backend ids they answer to, event → animation mapping, the sim's state machine |
| [show-mode.md](show-mode.md) | the 90-second show, its beats and data sources, the focus spotlight, and what a judge can do |
| [backstage.md](backstage.md) | the hidden consoles for the other laptops: red, green, blue and battlefield, live |
| [agent-design.md](agent-design.md) | what each of the 30 figures looks like (team base + role kit), how it is built and animated, how to add one |
| [dossier-modal.md](dossier-modal.md) | the click-to-open modal: placeholders, live data, catalogs, host overrides, every field key |
| [camera-and-tour.md](camera-and-tour.md) | the intro flight, the scroll rail, chapters, the arena orbit, how to edit waypoints |
| [backdrop.md](backdrop.md) | the ledger crown wired to verdicts, skyline, searchlights, motes |
| [palace-model.md](palace-model.md) | the glb files, coordinate system, generated site data, pathfinding, the cutaway, licence |
| [performance-and-quality.md](performance-and-quality.md) | the quality ladder, `?q=`, what costs what, known limits |
| [development.md](development.md) | running, env switches, tests, regenerating site data, troubleshooting |

## Quick start

```bash
cd frontend
npm install
NEXT_PUBLIC_MOCK=true npm run dev     # zero backend: "Run episode" replays public/mocks/sample.jsonl
```

With a battlefield running, set `BATTLEFIELD_URL`, `OPERATOR_TOKEN` and `NEXT_PUBLIC_WS_URL` (see `.env.example`) and
"Run episode" creates a live episode instead; if it cannot connect it says so and replays the sample.

## What was added in this branch

- `app/page.tsx` the arena, `app/ops/page.tsx` the old skeleton, `app/arena.css` all overlay styling, `app/layout.tsx` fonts
- `components/arena/**` the R3F scene (including the backdrop) and the HTML overlays
- `lib/arena/**` simulation, pathfinding, event director, dossier data, scroll pacing, ledger tallies, store, quality, generated site data (+ tests)
- `public/models/**` the two Palace glb files and their attribution; `public/basis/**` the KTX2 transcoder
- `tools/gen-site-data.py` regenerates `lib/arena/siteData.ts`
- `ARENA.md` a one-page overview, this `docs/` folder the detail
- `package.json` / `package-lock.json`: Next 15.0.3 → 15.5.28 and React 19 RC → 19 stable (React Three Fiber 9 needs
  stable React 19); new dependencies `three`, `@react-three/fiber`, `@react-three/drei`, `@react-three/postprocessing`,
  `postprocessing`, `zustand`, `three-mesh-bvh`; dev: `@types/three`, newer `@types/react*` and `eslint-config-next`.
- `AGENTS.md` and `Dockerfile` comments updated for the moved page. Nothing outside `frontend/` was touched.

Suggested `devlog/` line for the PR (not committed, because this branch only touches `frontend/`):

```
- 2026-10-24T04:56Z · R · frontend: cinematic 3D arena at / (R3F: Palace of Fine Arts glb, intro flight, scroll tour, 30 agents pathfinding into the rotunda, click-to-dossier with source-named placeholders; events drive it via lib/arena/director.ts; old dashboard moved to /ops); bumped next to 15.5.28 + react 19 stable for R3F 9; next: wire real /schemes + vendor catalogs; blocked: none
```
