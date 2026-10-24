# The Palace model, the site data and pathfinding

## The files

| file | contents | size |
|---|---|---|
| `public/models/palace-arch.glb` | rotunda, colonnades, site architecture; 21 nodes, ~330k unique triangles, GPU-instanced columns and ornament | 4.6 MB |
| `public/models/palace-ground.glb` | terrain, lagoon bed, riprap, colonnade paving; one 113k-triangle mesh | 2.0 MB |
| `public/basis/basis_transcoder.{js,wasm}` | KTX2 / Basis transcoder (copied from `three/examples/jsm/libs/basis`) | 0.6 MB |

They are the baked `gate1` exports of <https://github.com/dkhh10/palace-of-fine-arts-3d>, fetched unmodified from its
live walkthrough, with gltfpack's meshopt compression, `KHR_mesh_quantization`, KTX2 (BasisU) albedo textures and
`EXT_mesh_gpu_instancing`. `Palace.tsx` loads them with `GLTFLoader` + `MeshoptDecoder` + `KTX2Loader`
(`/basis/` transcoder path) through R3F's `useLoader`. They carry albedo only: the project's lightmaps and PBR maps are
hundreds of MB and are not used, so the arena lights the geometry itself (`Atmosphere.tsx`).

Licence and credit: `public/models/ATTRIBUTION.md` (textures CC BY-SA 4.0, site outlines © OpenStreetMap contributors).

## Coordinates

glTF is Y-up: Blender +Z → +Y, Blender +Y → -Z. So in the viewer:

- 1 unit = 1 m, **origin = the centre of the rotunda floor**, `y = 0` is the rotunda floor
- the lagoon lies toward **-Z** (the classic hero camera is at about (-14, 1, -100) looking +Z)
- the north colonnade is toward **-X**, the south colonnade toward **+X**, the hall behind the rotunda toward **+Z**
- water surface at `y = -1.3`

OpenStreetMap (east, north) maps to three `(x, z) = (-north, -east)`; Blender `(x, y, z)` maps to `(x, z, -y)`. Both were
checked against the exported glb's bounding box and the manifest's hero camera.

## Site data (`lib/arena/siteData.ts`, generated)

`tools/gen-site-data.py <site_local.json> <manifest.json> > lib/arena/siteData.ts` reads two files from the Palace
project (the OSM footprints in `reference/plans/site_local.json` and the gate5 export manifest) and writes:

| export | meaning |
|---|---|
| `WATER_Y` | -1.3 |
| `LAGOON` | the lagoon outline (160 points) |
| `HALL` | the crescent-shaped exhibition hall behind the rotunda |
| `PYLONS` | six small pylon squares near the rotunda |
| `ROTUNDA_FOOTPRINT`, `COLONNADE_NORTH_ROOF`, `COLONNADE_SOUTH_ROOF` | outlines used by the fallback palace |
| `COLUMNS` | 138 columns from the manifest's per-object locations: 16 outer rotunda (r = 23.85 m), 8 inner (r = 16 m), 114 colonnade (two rows 4.5 m apart, 3 m between columns) |

The generator is not part of the build. Re-run it only if the model changes.

## Pathfinding (`lib/arena/nav.ts`)

- A 1 m grid over x ∈ [-150, 150], z ∈ [-135, 110]. Lagoon, hall and pylons are blocked, then dilated by 1 m so a path
  never grazes them. Built once per page load and cached (a fraction of a second).
- **A\*** over the 8-connected grid, no corner cutting, octile heuristic, binary-heap open list; the result is
  string-pulled with a line-of-sight test so agents walk straight legs. Start and goal snap to the nearest walkable cell.
- **Columns are not in the grid.** They are 3 m apart with ~2 m gaps, which a 1 m grid cannot resolve, and the colonnades
  are walkways. They are circles in a spatial hash (`pushOutOfColumns`); the sim slides agents out of any column each
  frame, with a small tangential curl so a head-on agent goes round rather than stalling.
- `scatterWalkable` places the 8 / 10 / 12 agents of a team around its spawn anchor on walkable ground at least 3.4 m apart
  and 1.2 m clear of any column.

Typical paths: 50-110 m from the spawns round the lagoon and through the colonnades to the rotunda; `sim.test.ts`
asserts a clear path from each spawn and that none is longer than 260 m.

## Height under the feet (`components/arena/ground.ts`)

Once the glb is in, a `GroundSampler` raycasts it straight down once over a 2 m grid (700 rays per frame so it never
stalls the main thread), using BVHs from `three-mesh-bvh`, ignoring instanced meshes (columns, urns, statues) and
back-facing hits. Agents sample it bilinearly; before it is ready, or with the fallback palace, the floor is flat at 0.

## The cutaway (`components/arena/cutaway.ts`)

The rotunda is roofed, so from above nobody on the floor is visible. In the arena stage:

- a clipping plane slices every Palace material above `CUT_Y = 11` m (the outer columns end near 23.5 m; the piers are left as stumps); the plane
  eases down from 140 m so the building appears to open from the top
- materials whose names match `HIDE_IN_ARENA` (`dome_membrane`, `plaster_ceiling*`, `concrete_inner`,
  `column_tan_inner`, `drum_band`) fade out and are then hidden, which also removes their shadows
- sliced walls are rendered double-sided so they read as solid from inside

A faint ring sweeps down with the cut plane as the building opens and vanishes once it lands. Going back up the tour reverses it. The materials are matched by the names in the glb, so a renamed material needs
`HIDE_IN_ARENA` updating.

## Sky, water, light (`components/arena/Atmosphere.tsx`)

The sun direction is the Blender sun baked into the Palace export (`sun.direction_gltf` = (-0.473, -0.128, 0.872), a low
golden-hour sun over the lagoon). The sky is a gradient shader dome with the sun glow; the lagoon is a 4 km plane at
`WATER_Y` with a fresnel / sun-glint shader and travelling ripples that flatten with distance; fog colour matches the
horizon. Shadows are one directional light covering ±140 m.

## If the model is missing

`Palace.tsx` wraps the glb loads in an error boundary; on failure it builds a stand-in from `siteData.ts` (lawn with the
lagoon cut out, rotunda ring, drum and dome, instanced columns and beams) and the experience carries on. The HUD notes
"stand-in palace".
