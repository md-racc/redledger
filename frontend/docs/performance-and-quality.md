# Performance and quality

## The ladder (`lib/arena/quality.ts`, applied in `components/arena/Scene.tsx`)

| level | pixel ratio | shadows | shadow refresh | post-processing |
|---|---|---|---|---|
| 3 (default on desktop) | 1 - 1.5 | 2048 | every 2nd frame | bloom, tone map, grade, vignette, grain, SMAA |
| 2 (default on phones / coarse pointers) | 1 - 1.25 | 1024 | every 3rd frame | bloom + tone map |
| 1 | 1 - 1.1 | 1024 | every 6th frame | none (renderer's own ACES tone mapping) |
| 0 | 1 | off | - | none |

- `?q=0` … `?q=3` pins a level and turns the automatic step-down off (useful for comparing, and for slow machines).
- Without `?q`, `lib/arena/governor.ts` (tested) watches the frame rate: it ignores the first 6 s after load, any frame longer
  than 0.5 s (a hidden pane, a window drag) and the loading stage; it steps down one level after 4 whole seconds under 24 fps,
  and back up (at most twice) after 10 s at 52 fps or more, with a 20 s cooldown. If it has to step down again after stepping
  up it stops trying. `document.documentElement.dataset.quality` shows the current level.
- Why: the first rule (under 20 fps for ~1.5 s, one way only) turned a single hiccup into a permanently flatter scene.
- The sun never moves, so the shadow map is refreshed every few frames rather than every frame; only the agents' shadows
  lag slightly.

## What costs what

Measured on an AMD Radeon 880M iGPU in the Claude desktop browser pane: ~57 fps at level 3, 1294×765 CSS px.

| thing | cost / note |
|---|---|
| Palace geometry | ~330k unique triangles plus instancing, about 1.7M triangles and ~480 draw calls per frame including the shadow pass |
| shadow pass | re-renders the Palace; reduced by the refresh cadence above |
| post chain | bloom (`mipmapBlur`), tone mapping, grade, vignette, grain, SMAA; `lite` keeps bloom and tone mapping only |
| backdrop | one 72-instance bar mesh, a 280-instance skyline, four cones and a few hundred sprites; all additive or unlit, no extra shadow casters (see [backdrop.md](backdrop.md)) |
| agents | 30 figures of a few hundred triangles each, 6 beam meshes, 24 instanced coins, 8 shockwave rings |
| DOM overlays | updated by CSS variables / transforms from `requestAnimationFrame`, not React renders |
| first load | the glb decode and KTX2 transcode happen behind the loader; the nav grid is built once |

Things that look like performance problems but are not: a browser pane under viewport emulation, or one that is hidden,
throttles `requestAnimationFrame` hard: the arena measured ~3 fps there against ~57 fps at the real window size, and a trivial page ~26 fps. Test at the real window size.

## Memory

About 52 textures and 96 geometries live after load; the glb files are 6.6 MB over the wire. The agent materials are
per-agent (so each can flash independently); geometries are shared (`components/arena/assets.ts`).

## Knobs if you need more speed

1. Lower `dpr` in `quality.ts` (the biggest lever on high-DPI screens).
2. Drop the shadow map to 1024 for level 3.
3. Remove `Noise` / `HueSaturation` / `BrightnessContrast` from the full chain in `Effects.tsx`.
4. Restrict `Lights`' shadow camera bounds (±140 m) to the area the camera actually frames.

## Known limits

- A level can step back up only twice per page load.
- The fallback palace is much simpler and its shadows are cheap; it is not tuned for looks.
- Touch devices: in the arena the orbit controls take over touch gestures on the canvas, so scrolling back up is by the
  *Back to tour* button or the chapter rail, not a swipe.
