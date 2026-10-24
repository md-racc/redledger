# Camera and the scroll tour

All camera work is in `components/arena/CameraRig.tsx`; chapter text and positions are in `lib/arena/timeline.ts`.

## The intro flight (time-driven, ~12.5 s)

A `CatmullRomCurve3` (centripetal) through five waypoints, with a separate curve for where the camera looks. Progress is
`smootherstep(introTime / 12.5)`, so it eases in and out. The lens also eases from 54° to 40°.

Each key is `[camX, camY, camZ, lookX, lookY, lookZ]` in glb world space (lagoon toward -Z, north colonnade toward -X):

| # | camera | looks at | beat |
|---|---|---|---|
| 0 | -150, 26, -70 | -70, 10, 8 | low over the water, off the north colonnade tip |
| 1 | -105, 20, -88 | -40, 12, 6 | skimming along the colonnade |
| 2 | -52, 20, -104 | -4, 14, 4 | crossing the lagoon toward the classic hero view |
| 3 | -6, 26, -118 | 0, 18, 0 | the rotunda centred, dome in frame |
| 4 | 30, 58, -142 | 0, 10, 0 | rising and pulling back: the establishing shot the title sits over |

The title lockup (`overlays/TitleOverlay.tsx`) starts its letter reveal when the stage leaves `loading`; the *Discover*
pill fades in over the last 20 % of the flight and the lockup slides off as soon as the visitor scrolls.

## The scroll rail

Scroll progress (0..1 over the 640vh spacer) is damped (λ = 4.2) into `timeline.scroll`, which indexes a second
CatmullRom rail. The camera chases the rail point with exponential smoothing (λ = 7), so a wheel flick or a jump to a
chapter never snaps. The mouse adds a few metres of parallax on top, recomputed from the pose every frame so it never
accumulates.

| # | camera | looks at | stop |
|---|---|---|---|
| 0 | 30, 58, -142 | 0, 10, 0 | establishing (chapter 01 The Palace) |
| 1 | 112, 26, -80 | 78, 3, -30 | blue guards on the south shore (02 The Guards) |
| 2 | 120, 44, 30 | 40, 4, 38 | swing round the south colonnade |
| 3 | 22, 28, 86 | -20, 3, 42 | green clients behind the rotunda (03 The Clients) |
| 4 | -70, 46, 88 | -50, 3, 30 | swing toward the north |
| 5 | -124, 26, -56 | -86, 3, -12 | red fraudsters at the north tip (04 The Fraudsters) |
| 6 | -70, 80, -88 | 0, 4, 2 | up and over the lagoon |
| 7 | 0, 72, -40 | 0, 4, 2 | the arena pose (05 The Arena) |

Points are spaced evenly in rail parameter, so the chapter positions in `timeline.ts` (`at: 0, 0.2, 0.43, 0.71, 1`) line
up with rail points 0, ~1.5, 3, 5 and 7. If you move a waypoint, move its chapter and the matching faction banner window
in `overlays/LabelLayer.tsx` (`AT`) with it. The faction banners ("GUARDS", "CLIENTS", "FRAUDSTERS") fade in only while the
rail passes their group.

## The arena orbit

When the rail lands, `ArenaOrbit` mounts drei's `OrbitControls` (target `(0, 4, 2)`): rotate by dragging, zoom
disabled (so the wheel still scrolls the page back up), no pan, polar angle 17°-72°. Left alone for 4.5 s the camera
drifts slowly around the target (frame-rate independent). Selecting an agent moves the orbit target onto it and dollies in
to 26 m; deselecting eases back out.

At the same moment the rotunda is "opened": a clipping plane slices everything above 23.4 m and the dome shell, ceiling
and inner piers fade out (`components/arena/cutaway.ts`), with a faint scan ring at the cut height. The orbit camera sits
at about 60° elevation so the floor is visible over the near piers.

## Portrait screens

`aspect < 1.5` widens the lens (up to +22°) and dollies the camera back along its view line (up to ×1.9) so the three groups
still fit side to side. The chapter caption, the title lockup (stacked) and the HUD (score tiles on top, controls at the
bottom, the dossier a bottom sheet) all have a phone layout under 760 px.

## Editing

- Move a waypoint: edit `INTRO` / `RAIL` at the top of `CameraRig.tsx`. Check it at scroll positions 0, 0.2, 0.43, 0.71, 1.
- Retime the intro: `INTRO_SECONDS` in `timeline.ts`.
- Change the final framing: the last `RAIL` key and `ARENA_LOOK`.
- Change spawn points: `SPAWN` in `config.ts`; run `npm test` (it asserts a clear path from every spawn) and look at the
  chapter that shows that group.
