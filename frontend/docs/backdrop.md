# The arena backdrop

What surrounds the rotunda, kept well back from the arena so the agents stay the focus. All of it is additive light or a
distant silhouette. The code is `components/arena/Backdrop.tsx`; the tally logic is `lib/arena/ledgerStats.ts`.

Everything powers up with the tour: `presence()` (in `components/arena/presence.ts`) is 0 during the intro, ramps in over the
first stretch of the tour and is 1 in the arena, so the title shot stays clean.

## Ledger crown (the glowing bar arc)

72 bars on a 240 degree arc at r = 60 m (from the south front, round the back, to the north front; bars within 4.5 m of a
colonnade column are dropped), in 12 wedges, one wedge per episode day. Each wedge is six bars: two green (payments the
gate **allowed**), two blue (**blocked**), two red (dollars **stolen**).
`tallyDays(state)` counts them from the reducer (`gate.verdict.verdict` by day, `attack.amount_extracted` by `day_launched`),
up to the last 12 days. Heights ease toward their targets (`heights` in `ledgerStats.ts`: allowed `4 + 2.2*sqrt(n)`, blocked
`4 + 5*sqrt(n)`, stolen `4 + 3.2*sqrt(dollars/50)`, capped at 60-70 m). Wedges with no data yet idle as a low, dim equalizer
(2-8 m), so the crown is alive before an episode and fills in as days complete. The bars are additive, with a vertical
gradient, a bright cap and a scanline running up them. It sits well outside the rotunda's apron so it never crowds the agents.

## Skyline, searchlights, motes

- **Skyline**: 280 instanced boxes on a ring 190-290 m out (9 % are 50-95 m towers), dark silhouettes shaded by the scene
  fog, with a shader-drawn grid of windows (about half lit, a few twinkling, a few cool blue instead of warm). The windows are
  added after the haze so they still read at distance, and they bloom.
- **Searchlights**: four faint cones on posts 230-270 m out, aimed away from the arena and swinging +-0.9 rad across the sky.
- **Motes**: drei `Sparkles`, a 240 x 55 x 240 m volume of warm dust plus a small cloud in each faction's colour over its
  spawn lawn.

Things that were tried and removed on review: a holographic floor with range rings and a rotating radar sweep, route "trail"
lanes along each faction's path, three tall faction-coloured crystal monoliths, tall coloured light shafts on the horizon,
ledger pages orbiting the rotunda, and the ring portals on each spawn lawn.

## Quality gating

| level | backdrop |
|---|---|
| 3 | everything |
| 2 | ledger crown and skyline (no searchlights, no motes) |
| 1, 0 | none |

## Editing

- Crown radius, arc, bar count, heights: the "ledger ring" section of `Backdrop.tsx` (`RING_R`, `ARC_*`, `BARS`) and `heights`
  in `ledgerStats.ts`.
- Skyline distance, density and heights: `SKY_N` and `skylineInstances()` (the `190 + rnd() * 100` radius).
