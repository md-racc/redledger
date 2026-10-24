# The arena: redledger's 3D front door

`/` is a cinematic WebGL experience (React Three Fiber on Next.js); the original data-path dashboard is at `/ops`.

```
loading → intro (auto flight, ~7 s, title lockup) → scroll tour (5 chapters) → arena (orbit, HUD, 30 agents, dossier)
```

- **Intro:** the camera skims the north colonnade, crosses the lagoon and rises into an establishing shot while `red` and
  `ledger` rise out of a mask on either side of the Palace.
- **Tour:** scroll drives a camera rail past the three groups: guards (blue), clients (green), fraudsters (red).
- **Arena:** the rotunda opens, the agents pathfind in from the perimeter, and a click on any of them opens its dossier.
- **Backend:** `attack.*`, `gate.verdict`, `flag.raised` and `vendor.*` events drive the animation; "Run episode" goes live
  if a battlefield answers and replays `public/mocks/sample.jsonl` if not.

- **Show:** press `S` for the 90-second tour of the whole site, controller off vs on, compare and evolution; then launch your own
  attack. **Backstage:** press `B` for the hidden per-team consoles (red, green, blue, battlefield) for the other laptops.

```bash
cd frontend && npm install
NEXT_PUBLIC_MOCK=true npm run dev        # no backend needed
npm run dev:live                         # a stand-in battlefield, the live path with no Docker
```

Everything is documented in [`docs/`](docs/README.md): architecture, agents and events, the dossier modal and its
placeholders, the camera and tour, the Palace model and pathfinding, performance, and development notes. The model's
licence and credit are in [`public/models/ATTRIBUTION.md`](public/models/ATTRIBUTION.md).
