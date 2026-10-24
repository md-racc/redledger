# Architecture

## The experience in four stages

```
loading ──► intro ──► scroll ◄──► arena
```

The stage lives in the zustand store (`lib/arena/store.ts`, `stage`). Who moves it:

| Transition | Done by | Condition |
|---|---|---|
| `loading → intro` | `ArenaExperience.tsx` | the sim exists and the model has resolved (real glb or fallback), after a 1.8 s floor so the title card is seen; a 35 s ceiling so it can never hang |
| `intro → scroll` | `CameraRig.tsx` | the flight finished (`timeline.introLen`: 7.5 s, 5.8 s in the show), or the visitor pressed *Skip intro*, or `prefers-reduced-motion` |
| `scroll → arena` | `CameraRig.tsx` | smoothed scroll > 0.994 and raw scroll > 0.99 |
| `arena → scroll` | `CameraRig.tsx` | raw scroll < 0.96 (scrolling back up, or *Back to tour*); `ArenaExperience` also sends the agents back to their spawn lawns, and sends them in again on the next arrival |

The page does not scroll while `loading` or `intro` (`ArenaExperience` locks `overflow`). In `scroll` and `arena` the
document is a 780vh spacer (`div.arena-scroll`) under a fixed canvas, so wheel and touch scroll work everywhere, and
`window.scrollY / (scrollHeight - innerHeight)` is the scroll fraction (which the pacing curve turns into a camera position, see
[camera-and-tour.md](camera-and-tour.md)). In the arena the orbit controls have zoom disabled
on purpose, so the wheel still scrolls the page and can take the visitor back to the tour.

## Layers

```
app/page.tsx ─► ArenaClient (next/dynamic, ssr:false)
                  └─ ArenaExperience            stage machine, feed, window.redledger
                       ├─ Scene (<Canvas>)      WebGL
                       │    ├─ Lights / SkyDome / Water         Atmosphere.tsx
                       │    ├─ Palace                           Palace.tsx  (glb + fallback)
                       │    ├─ ArenaWorld                       sim loop, 30 figures, fx
                       │    ├─ CameraRig                        intro / rail / orbit
                       │    ├─ Picking                          THREE.Raycaster
                       │    └─ Effects                          bloom, tone map, grade, grain, SMAA
                       └─ DOM overlays
                            TitleOverlay  Chapters  Hud  AgentModal  LabelLayer  PopLayer  Loader
```

The whole 3D bundle is client-only (`ssr: false`): the first server response is just the black boot screen, and the arena
chunk loads on demand (`/` is ~104 kB first-load JS before the dynamic chunk).

## Per-frame data never goes through React

Rendering at 60 Hz through React state would re-render the overlays every frame, so there are four small side channels:

| Module | Written by | Read by | Holds |
|---|---|---|---|
| `lib/arena/sim.ts` (`ArenaSim`) | the render loop | `ArenaWorld`, tests | agent positions, headings, modes, scenes |
| `lib/arena/timeline.ts` | `CameraRig` | overlays (via `subscribeTimeline`) | `intro`, `scroll`, `arena` progress 0..1 |
| `lib/arena/popBus.ts` | `ArenaWorld` | `PopLayer`, `LabelLayer` | floating text pops, screen anchors for banners / hover tag |
| `components/arena/figures.ts` (`figures` map) | `ArenaWorld` | `Picking`, `CameraRig` | the live three.js object per agent |

Overlays subscribe to these and write CSS variables / transforms straight onto DOM nodes (`el.style.setProperty`), so
the title exit, chapter fades, popups and banners cost no React renders. React state is only for events that change
rarely: the stage, the hovered / selected agent, the sim phase, the episode state.

`bridge.ts` exposes `project(agentId)` (the agent's screen position) so the dossier can draw a connector line to it.

### Frame order

`useFrame` priorities: `ArenaWorld` at -3 (sim step, figure animation, fx, projection), `CameraRig` at -2, then the
post-processing composer renders. The sim step is clamped to 0.1 s and the camera step to 0.05 s, so a hitch never
teleports anything.

## Where state comes from

```
battlefield ──ws/rest──►  lib/ws.ts ─┐
public/mocks/sample.jsonl ─► loadFixture ─┤
                                          ▼
                              useFeed (lib/arena/useFeed.ts)
                               ├─ reducer (lib/reducer.ts) ─► UIState ─► Hud, AgentModal (details.ts)
                               └─ subscribe(event) ─► Director ─► ArenaSim ─► figures
```

`useFeed` is the same reducer the rest of the frontend uses; it adds a reset action, replay pacing
(`paceMs`: quiet events fly by, `attack.outcome` gets 6.5 s so the scene can play) and the live → recorded-sample
fallback. The Director only talks to `ArenaSim`, so the live socket, the sample and the demo loop are interchangeable.

`window.redledger` (set by `ArenaExperience`) exposes `converge()`, `disperse()`, `select(id)` and `run(mode)` for the
host page or the console.

## Conventions followed from `frontend/AGENTS.md`

- No token in the browser: the feed uses the existing `/api/bf` proxy and the ticketed socket.
- Scores are never computed client-side; the HUD renders `score.updated`.
- `origin` (ground truth) is never shown.
- Everything works with `NEXT_PUBLIC_MOCK=true` and no backend.
