# Agent design: what each figure looks like and why

Every one of the 30 figures is built in code (`components/arena/figures.ts`, plain three.js, no model files) from a **team
base** plus a **role kit**, so a figure tells you who it is before you click it. Nothing here changes the ids, the sim or
the events; it is all presentation.

## How a figure is put together

```
root (scale AGENT_SCALE = 2.1)
├─ body
│   ├─ torso (group, y = 0.24)       team base + role kit parent here, so everything sways with the walk
│   │   ├─ head, armL, armR (groups) pivots, so arms and head can animate independently
│   │   └─ role props, emblem, cape …
│   └─ legL, legR (groups)           pivots at the hip
├─ ring + pillar                     team-coloured ground ring and a beacon; both grow on hover / selection, and the
│                                    beacon drops to a short stub once the arena is engaged so it stops cluttering the shot
├─ ice                               the translucent shell shown while the agent's status is "frozen" (vendor.frozen)
└─ hit                               invisible 3 m cylinder: the raycaster's pick volume
```

- **Geometry is cached.** `gBox / gCyl / gSph / gCone / gTor / gPlane / gCap / gHalf` return one shared `BufferGeometry` per
  distinct size, so 30 figures with ~40 meshes each share a few dozen geometries. `disposeFigure` only disposes materials.
- **Role kits get a `Ctx`** (`torso`, `head`, `armL`, `armR`, `accent`, `lit`, `holo`, `mesh`, `group`, `glyph`, `anim`).
  A kit builds meshes with `c.mesh(...)` and registers per-frame motion with `c.anim((t, dt, state) => …)`. All of a
  figure's animators live in `FigureHandle.anim`, and `animateFigure` runs them after the shared locomotion pass.
- **Locomotion is shared.** `animateFigure` swings the arms and legs against each other with the stride, bobs and leans the
  whole body into motion (more when a guard dashes), breathes when idle, shudders and raises a fraudster's right hand
  while it is pitching, and slumps a caught fraudster. Role kits add on top (a cape that streams when the guard runs, an
  emblem that turns, a balloon that swells).
- **Colour carries the team**; the **accent colour** carries the role. Teams keep their hue (red, blue, green) in the ring,
  pillar and glow so the groups read from the sky; each role has its own accent (`RED_ACCENT`, `BLUE_ACCENT`) for the
  visor, belt and props.

## Red: eight fraudsters, eight tells

All wear a dark hooded cloak with a glowing visor, a glowing hem and three orbiting shards. The cloak and props say
which scheme they run:

| scheme | tell |
|---|---|
| `ghost_vendor` | see-through cloak (transparent, no depth write), three bobbing wisps at the hem, a forged `$?` invoice floating at its side |
| `bank_swap` | two bank cards forever trading places in an orbit around the chest |
| `duplicate_invoice` | a faint holographic twin standing at its shoulder, two near-identical papers |
| `threshold_split` | a glowing blade in one hand and three slips of paper fanned in the other |
| `ghost_employee` | a blank white mask instead of a face, and a swinging `?` badge nobody issued |
| `expense_inflation` | a balloon of receipts over its shoulder that keeps swelling and shrinking |
| `po_mismatch` | a scale over its head that never balances (tips ±24°) |
| `amount_drift` | chevrons creeping upward, shrinking as they rise |

## Blue: ten guards, ten emblems

All are armoured (plated body, pauldrons, helmet with a glowing visor, belt, short cape that streams when they run, a
shield on the left arm and a spear in the right). Severity from `lib/arena/roster.ts` shows in the kit:

- severity 1: plain helmet
- severity 2: a low fin crest
- severity 3: a tall fin crest and spikes on the pauldrons

Each guard also hovers a slowly turning **emblem** over its head that depicts the rule it enforces:

| rule | emblem |
|---|---|
| `vendor_age_lt_7d` | an hourglass that flips every four seconds |
| `near_threshold` | a limit bar across two posts with a marker under it |
| `duplicate_invoice` | a magnifying glass |
| `recent_bank_change` | a padlock |
| `bank_change_with_open_invoices` | two interlocked chain links |
| `no_po_from_po_vendor` | a clipboard with ruled lines |
| `over_po_amount` | a ceiling plate with an arrow pushing against it |
| `recurring_drift` | a spinning radar dish |
| `employee_bank_matches_vendor` | an ID badge |
| `already_flagged_high` | a red flag planted on a pole, waving |

## Green: twelve clients, twelve trades

Clients are rounder and softer than the other two teams (capsule body, sphere head), in slightly different body and skin
tones and slightly different heights (93-107 % of the base scale) so a crowd does not look cloned. A floating `$` card
marks them as the party being paid. Each carries the tools of a trade (`GREEN_TRADES`, indexed by client slot):

| slot | trade | props |
|---|---|---|
| 01 | office supplies | stack of folders, glasses |
| 02 | logistics | a parcel on the shoulder |
| 03 | construction | hard hat, hi-vis vest |
| 04 | café | chef's hat, apron |
| 05 | IT | open laptop, glowing screen |
| 06 | utilities | wrench at the hip, spinning gear overhead |
| 07 | legal | briefcase, tie |
| 08 | marketing | megaphone |
| 09 | cleaning | bucket and mop |
| 10 | printing | paper roll across the shoulders |
| 11 | courier | cap, parcel in both hands |
| 12 | consulting | glasses, tie, clipboard |

## Editing a figure

- **A new fraud scheme or rule**: add its key to `RED_ROLES` / `BLUE_ROLES` (and an entry in `RED_ACCENT` /
  `BLUE_ACCENT`). A key with no kit still renders the team base, so a new backend id never breaks the arena.
- **Props sit in torso space.** The torso is at y = 0.24 inside a root scaled by 2.1, so a prop at `y = 1.3` is about chest
  height, `y = 2.5` is above the head. Hover labels and pop-ups are anchored at +6.6 / +7.2 world metres above the ground
  (`ArenaWorld.tsx`) so they clear tall emblems.
- **Keep it cheap.** Use the cached `g*` helpers, reuse materials through `c.lit` / `c.holo`, and put any motion in `c.anim`
  rather than a separate `useFrame`. Materials from `c.lit` are registered for the shared emissive pulse (`FigureHandle.glow`).
