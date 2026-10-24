// Tunable constants for the arena. World space = the Palace glb's: 1 unit = 1 m, origin = rotunda floor centre,
// +Y up, the lagoon lies toward -Z, the north colonnade toward -X, the south colonnade toward +X.
import type { Team } from "./types";

export const MODEL_URLS = {
  arch: "/models/palace-arch.glb",
  ground: "/models/palace-ground.glb",
} as const;

/** Where the agents converge. The rotunda floor centre. */
export const CENTER = { x: 0, z: 0 } as const;

/** Visual scale of every agent figure (a 1.8 m person reads as an ant from the aerial shots). */
export const AGENT_SCALE = 2.1;

/** Radius of the keep-out margin around obstacles, metres. Wider than the figure so shoulders clear columns. */
export const AGENT_CLEARANCE = 1.0;

/** Perimeter spawn anchors (x, z, scatter radius), all on open ground (no roof overhead) so the aerial shots can see
 *  them: the lawn at the north colonnade tip (red), the south shore lawn (blue) and the lawn behind the rotunda (green).
 *  Paths from here are 50-110 m round the lagoon and through the colonnades. */
export const SPAWN: Record<Team, { x: number; z: number; r: number }> = {
  red: { x: -86, z: -12, r: 8 },
  blue: { x: 78, z: -30, r: 8 },
  green: { x: -20, z: 42, r: 6 },
};

/** Slot rings in the arena centre. Clients (green) sit innermost, guards (blue) ring them, and the fraudsters (red)
 *  hold the outer ring, so an attack has to cut through the guards to reach its target. All inside the r = 23.85 outer colonnade (the r = 16 inner piers fade away in the arena, so they are not obstacles). */
export const SLOT_RING: Record<Team, number> = { green: 7.0, blue: 12.5, red: 18.0 };

/** Metres per second. Per-agent speed is drawn from [min, max]. */
export const SPEED: Record<Team, [number, number]> = { red: [13.5, 15.5], blue: [14.0, 16.0], green: [11.0, 13.0] };
export const DASH_SPEED = 24;

export const NAV = {
  cell: 1.0,
  minX: -150,
  maxX: 150,
  minZ: -135,
  maxZ: 110,
} as const;

/** The glb's golden-hour sun: direction the light travels, from the export manifest (`sun.direction_gltf`). */
export const SUN_TRAVEL = { x: -0.473, y: -0.128, z: 0.872 } as const;
