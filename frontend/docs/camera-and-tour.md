# Camera and the scroll tour

All camera work is in `components/arena/CameraRig.tsx`; chapter text and positions are in `lib/arena/timeline.ts`.

## The intro flight (time-driven, 7.5 s; 5.8 s in the show)

A `CatmullRomCurve3` (centripetal) through five waypoints, with a separate curve for where the camera looks. Progress is
`smootherstep(introTime / timeline.introLen)`, so it eases in and out. The lens also eases from 54° to 40°.

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

Scroll progress (0..1 over the 780vh spacer) is damped (λ = 4.2) into `timeline.scroll`, passed through the pacing curve
(next section) into `timeline.rail`, which indexes a second CatmullRom rail. The camera chases the rail point with exponential smoothing (λ = 7), so a wheel flick or a jump to a
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

## Landing the Palace in the title

"red" is shorter than "ledger", so the gap between the two words sits left of the screen centre. `TitleOverlay` measures the
gap (the right edge of "red" and the left edge of "ledger", on load, when fonts finish loading and on resize) and publishes
its centre as `timeline.gapX`. As the intro flight ends, and for as long as the title is up (until the first tenth of
scroll), `CameraRig` slides the projection with `camera.setViewOffset` by `(0.5 - gapX)` of the screen width, so the
rotunda lands exactly in the gap. The slide ramps in over the last 45 % of the flight and out as the title leaves; on phones,
where the words are stacked, it is off.

## Pacing: slow where there is something to read, fast where there is not

Page scroll (a 780vh spacer) is linear, the camera is not (`lib/arena/pacing.ts`). The camera's speed along the rail is a profile over the
rail parameter `u`: **slow (0.22)** inside a reading zone of ±0.05 around each chapter and **fast (2.6)** everywhere else (about 12x),
with a flat core and a smooth shoulder so there is no visible kink. Scroll fraction `s` is the normalised integral of
`1 / speed`; `scrollOf(u)` reads it from a lookup table and `railOf(s)` inverts it.

| | scroll fraction | roughly (780vh page) |
|---|---|---|
| each interior chapter's reading zone (02, 03, 04) | 20 % | ~135 vh of scrolling for ~0.1 of the rail |
| the first and last zones (01 The Palace, 05 The Arena) | 10 % | ~70 vh |
| each stretch between chapters | 3-6 % | ~22-42 vh covering ~0.15-0.28 of the rail |

So the camera crawls through a chapter for a couple of wheel flicks (captions stay fully visible while the camera is within
0.03 of the chapter, and fade by 0.075), then sweeps through the empty stretch about 12x faster. Everything tied to a chapter
reads `timeline.rail`, not `timeline.scroll`: caption opacity, the faction banners, the "on" state of the progress ticks. The
ticks themselves sit at `scrollOf(chapter.at)` and clicking one scrolls there. The title lockup's exit stays on raw scroll.

Tuning: `SLOW`, `FAST` and `DWELL_HALF` in `pacing.ts`; the page length is `SCROLL_VH` in `ArenaExperience.tsx`.
`lib/arena/pacing.test.ts` checks that the curve is monotonic and invertible, that every chapter gets at least 6 % of the
scroll, that dwelling takes 50-80 % of it overall, that no transit is a blink, and that the camera moves at least 3.5x
faster between chapters than inside one.

## The arena orbit

When the rail lands, `ArenaOrbit` mounts drei's `OrbitControls` (target `(0, 4, 2)`): rotate by dragging, zoom
disabled (so the wheel still scrolls the page back up), no pan, polar angle 17°-72°. Left alone for 4.5 s the camera
drifts slowly around the target (frame-rate independent). Selecting an agent moves the orbit target onto it and dollies in
to 26 m; deselecting eases back out.

At the same moment the rotunda is "opened": a clipping plane slices everything above 11 m (`CUT_Y`; the outer columns end
near 23.5 m, so the piers are left as stumps that still read as architecture) and the dome shell, ceiling and inner piers
fade out (`components/arena/cutaway.ts`), with a faint scan ring at the cut height. The orbit camera sits at about 60°
elevation so the whole floor is visible over what is left of the piers.

In a narrow or portrait window (the pane beside the chat, a phone) the rail's pose is pulled back to fit the three groups
side by side, which would leave the ring tiny in the middle of the arena. On landing, the arena camera comes in until the
36 m red ring fills the width (about 54 m across, never closer than 60 m away).

## Auto-cam: framing the interactions

The rotunda is a fixed size, so the three rings can only grow so far (they now sit at r = 7 / 12.5 / 18 m inside the 23.85 m
outer colonnade). The wide view shows the walk-up; the **moment itself** gets a quick cut-in (`lib/arena/cinema.ts`, written by
`ArenaWorld` every frame from the sim, read by `orbitFocus` in `CameraRig.tsx`):

1. when the fraudster reaches the client and starts the pitch, the orbit target snaps to the centre of the action
   (a fast ease, about 0.2 s)
2. the camera closes to 20-32 m (more in a narrow window, which sees less sideways), at a low three-quarter angle that only
   just clears the cut rim, with a longer lens (the field of view narrows by 7 degrees, so the background compresses), and
   swings and pushes in a little while it plays
3. when the guard sprints in (or the money starts to flow) the guard is added to the frame
4. 0.9 s after the outcome the camera eases back out to the full-arena view

It yields to the visitor: it backs off for 4.5 s after any drag, a selected agent (the dossier dolly) takes priority, and
the HUD's **Auto-cam on/off** switch turns it off for good (`cinematic` in the store, on by default).

## Portrait screens

`aspect < 1.5` widens the lens (up to +22°) and dollies the camera back along its view line (up to ×1.9) so the three groups
still fit side to side. The chapter caption, the title lockup (stacked) and the HUD (score tiles on top, controls at the
bottom, the dossier a bottom sheet) all have a phone layout under 760 px.

## Editing

- Move a waypoint: edit `INTRO` / `RAIL` at the top of `CameraRig.tsx`. Check it at scroll positions 0, 0.2, 0.43, 0.71, 1.
- Retime the intro: `INTRO_SECONDS` in `timeline.ts`.
- Change how long a chapter lingers: `SLOW` / `DWELL_HALF` in `pacing.ts`.
- Change the final framing: the last `RAIL` key and `ARENA_LOOK`.
- Change spawn points: `SPAWN` in `config.ts`; run `npm test` (it asserts a clear path from every spawn) and look at the
  chapter that shows that group.
