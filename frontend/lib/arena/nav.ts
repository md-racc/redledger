// Walkability grid + A* for the Palace site. Pure TypeScript (no three.js) so it runs under vitest.
//
// The grid is rasterised from the real site: the lagoon, the Exploratorium hall and the pylons are impassable.
// The colonnades and the rotunda are walkable; their 138 columns (positions read from the glb export manifest)
// are too fine for the grid (3 m apart, 2 m gaps), so they are handled by circle push-out (`pushOutOfColumns`).
import { AGENT_CLEARANCE, NAV } from "./config";
import { COLUMNS, HALL, LAGOON, PYLONS, type Pt } from "./siteData";

export interface NavGrid {
  cell: number;
  x0: number;
  z0: number;
  w: number;
  h: number;
  /** 1 = blocked */
  blocked: Uint8Array;
}

export type Vec2 = [number, number];

function pointInPoly(x: number, z: number, poly: readonly Pt[]): boolean {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, zi] = poly[i];
    const [xj, zj] = poly[j];
    if (zi > z !== zj > z && x < ((xj - xi) * (z - zi)) / (zj - zi) + xi) inside = !inside;
  }
  return inside;
}

let cached: NavGrid | null = null;

export function buildNavGrid(clearance = AGENT_CLEARANCE): NavGrid {
  if (cached && clearance === AGENT_CLEARANCE) return cached;
  const { cell, minX, maxX, minZ, maxZ } = NAV;
  const w = Math.ceil((maxX - minX) / cell);
  const h = Math.ceil((maxZ - minZ) / cell);
  const raw = new Uint8Array(w * h);
  const at = (ix: number, iz: number) => iz * w + ix;

  for (let iz = 0; iz < h; iz++) {
    for (let ix = 0; ix < w; ix++) {
      const x = minX + (ix + 0.5) * cell;
      const z = minZ + (iz + 0.5) * cell;
      if (pointInPoly(x, z, LAGOON) || pointInPoly(x, z, HALL)) raw[at(ix, iz)] = 1;
    }
  }
  for (const poly of PYLONS) {
    let x0 = Infinity, x1 = -Infinity, z0 = Infinity, z1 = -Infinity;
    for (const [x, z] of poly) { x0 = Math.min(x0, x); x1 = Math.max(x1, x); z0 = Math.min(z0, z); z1 = Math.max(z1, z); }
    for (let iz = Math.floor((z0 - minZ) / cell); iz <= Math.ceil((z1 - minZ) / cell); iz++)
      for (let ix = Math.floor((x0 - minX) / cell); ix <= Math.ceil((x1 - minX) / cell); ix++)
        if (ix >= 0 && iz >= 0 && ix < w && iz < h) raw[at(ix, iz)] = 1;
  }
  // Dilate by the clearance so a path never grazes an obstacle.
  const rad = Math.max(0, Math.round(clearance / cell));
  const blocked = new Uint8Array(w * h);
  for (let iz = 0; iz < h; iz++)
    for (let ix = 0; ix < w; ix++) {
      if (ix === 0 || iz === 0 || ix === w - 1 || iz === h - 1) { blocked[at(ix, iz)] = 1; continue; }
      if (!raw[at(ix, iz)]) continue;
      for (let dz = -rad; dz <= rad; dz++)
        for (let dx = -rad; dx <= rad; dx++) {
          const jx = ix + dx, jz = iz + dz;
          if (jx >= 0 && jz >= 0 && jx < w && jz < h) blocked[at(jx, jz)] = 1;
        }
    }
  const grid: NavGrid = { cell, x0: minX, z0: minZ, w, h, blocked };
  if (clearance === AGENT_CLEARANCE) cached = grid;
  return grid;
}

export const toCell = (g: NavGrid, x: number, z: number): Vec2 => [Math.floor((x - g.x0) / g.cell), Math.floor((z - g.z0) / g.cell)];
export const toWorld = (g: NavGrid, ix: number, iz: number): Vec2 => [g.x0 + (ix + 0.5) * g.cell, g.z0 + (iz + 0.5) * g.cell];

export function isWalkable(g: NavGrid, x: number, z: number): boolean {
  const [ix, iz] = toCell(g, x, z);
  return ix >= 0 && iz >= 0 && ix < g.w && iz < g.h && g.blocked[iz * g.w + ix] === 0;
}

/** Nearest walkable world point to (x, z), searching outward in rings. */
export function nearestWalkable(g: NavGrid, x: number, z: number, maxRadius = 40): Vec2 | null {
  if (isWalkable(g, x, z)) return [x, z];
  const [cx, cz] = toCell(g, x, z);
  const maxR = Math.ceil(maxRadius / g.cell);
  for (let r = 1; r <= maxR; r++) {
    let best: Vec2 | null = null;
    let bestD = Infinity;
    for (let dz = -r; dz <= r; dz++)
      for (let dx = -r; dx <= r; dx++) {
        if (Math.max(Math.abs(dx), Math.abs(dz)) !== r) continue;
        const ix = cx + dx, iz = cz + dz;
        if (ix < 0 || iz < 0 || ix >= g.w || iz >= g.h || g.blocked[iz * g.w + ix]) continue;
        const [wx, wz] = toWorld(g, ix, iz);
        const d = (wx - x) ** 2 + (wz - z) ** 2;
        if (d < bestD) { bestD = d; best = [wx, wz]; }
      }
    if (best) return best;
  }
  return null;
}

/** True when the straight segment a→b crosses only walkable cells (sampled at half-cell steps). */
export function lineClear(g: NavGrid, a: Vec2, b: Vec2): boolean {
  const dx = b[0] - a[0], dz = b[1] - a[1];
  const n = Math.max(1, Math.ceil(Math.hypot(dx, dz) / (g.cell * 0.5)));
  for (let i = 0; i <= n; i++) {
    const t = i / n;
    if (!isWalkable(g, a[0] + dx * t, a[1] + dz * t)) return false;
  }
  return true;
}

// ---- column collision -----------------------------------------------------------------------------------------

export const COLUMN_RADIUS: Record<string, number> = { r: 1.15, i: 1.05, c: 0.65 };
const HASH = 8;
let colHash: Map<string, number[]> | null = null;

function columnHash(): Map<string, number[]> {
  if (colHash) return colHash;
  colHash = new Map();
  COLUMNS.forEach(([, x, z], i) => {
    const k = `${Math.floor(x / HASH)},${Math.floor(z / HASH)}`;
    const a = colHash!.get(k);
    if (a) a.push(i); else colHash!.set(k, [i]);
  });
  return colHash;
}

/** Visit every column within `r` metres of (x, z). */
export function forColumnsNear(x: number, z: number, r: number, fn: (cx: number, cz: number, cr: number) => void) {
  const h = columnHash();
  const gx0 = Math.floor((x - r - 2) / HASH), gx1 = Math.floor((x + r + 2) / HASH);
  const gz0 = Math.floor((z - r - 2) / HASH), gz1 = Math.floor((z + r + 2) / HASH);
  for (let gx = gx0; gx <= gx1; gx++)
    for (let gz = gz0; gz <= gz1; gz++) {
      const a = h.get(`${gx},${gz}`);
      if (!a) continue;
      for (const i of a) {
        const [kind, cx, cz] = COLUMNS[i];
        fn(cx, cz, COLUMN_RADIUS[kind]);
      }
    }
}

/** Slide a point of radius `agentR` out of any column it overlaps. `side` (+1/-1) picks which way to curl round a head-on hit. */
export function pushOutOfColumns(x: number, z: number, agentR: number, side = 1): Vec2 {
  let px = x, pz = z;
  forColumnsNear(px, pz, agentR, (cx, cz, cr) => {
    const dx = px - cx, dz = pz - cz;
    const d = Math.hypot(dx, dz);
    const min = cr + agentR;
    if (d >= min) return;
    if (d < 1e-4) { px += min * side; return; }
    const push = min - d;
    // a little tangential curl so a head-on agent slides round instead of stalling
    px += (dx / d) * push - (dz / d) * push * 0.35 * side;
    pz += (dz / d) * push + (dx / d) * push * 0.35 * side;
  });
  return [px, pz];
}

export function nearColumn(x: number, z: number, clearance: number): boolean {
  let hit = false;
  forColumnsNear(x, z, clearance, (cx, cz, cr) => { if (Math.hypot(x - cx, z - cz) < cr + clearance) hit = true; });
  return hit;
}

// ---- A* -------------------------------------------------------------------------------------------------------

class MinHeap {
  private keys: number[] = [];
  private vals: number[] = [];
  get size() { return this.keys.length; }
  push(key: number, val: number) {
    const k = this.keys, v = this.vals;
    let i = k.length;
    k.push(key); v.push(val);
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (k[p] <= k[i]) break;
      [k[p], k[i]] = [k[i], k[p]];
      [v[p], v[i]] = [v[i], v[p]];
      i = p;
    }
  }
  pop(): number {
    const k = this.keys, v = this.vals;
    const top = v[0];
    const lk = k.pop()!, lv = v.pop()!;
    if (k.length) {
      k[0] = lk; v[0] = lv;
      let i = 0;
      for (;;) {
        const l = 2 * i + 1, r = l + 1;
        let m = i;
        if (l < k.length && k[l] < k[m]) m = l;
        if (r < k.length && k[r] < k[m]) m = r;
        if (m === i) break;
        [k[m], k[i]] = [k[i], k[m]];
        [v[m], v[i]] = [v[i], v[m]];
        i = m;
      }
    }
    return top;
  }
}

const SQRT2 = Math.SQRT2;

/**
 * A* over the 8-connected grid (no corner cutting), then string-pulled with line-of-sight so agents walk
 * straight legs instead of staircases. Returns waypoints in world space (excluding the start), or null.
 */
export function findPath(g: NavGrid, from: Vec2, to: Vec2): Vec2[] | null {
  const s = nearestWalkable(g, from[0], from[1], 12);
  const t = nearestWalkable(g, to[0], to[1], 12);
  if (!s || !t) return null;
  const [sx, sz] = toCell(g, s[0], s[1]);
  const [tx, tz] = toCell(g, t[0], t[1]);
  const W = g.w;
  const start = sz * W + sx, goal = tz * W + tx;
  const gScore = new Float32Array(g.w * g.h).fill(Infinity);
  const parent = new Int32Array(g.w * g.h).fill(-1);
  const closed = new Uint8Array(g.w * g.h);
  const open = new MinHeap();
  const heur = (ix: number, iz: number) => {
    const dx = Math.abs(ix - tx), dz = Math.abs(iz - tz);
    return dx + dz + (SQRT2 - 2) * Math.min(dx, dz);
  };
  gScore[start] = 0;
  open.push(heur(sx, sz), start);
  let found = start === goal;
  while (open.size && !found) {
    const cur = open.pop();
    if (closed[cur]) continue;
    closed[cur] = 1;
    if (cur === goal) { found = true; break; }
    const cx = cur % W, cz = (cur - cx) / W;
    for (let dz = -1; dz <= 1; dz++)
      for (let dx = -1; dx <= 1; dx++) {
        if (!dx && !dz) continue;
        const nx = cx + dx, nz = cz + dz;
        if (nx < 0 || nz < 0 || nx >= g.w || nz >= g.h) continue;
        const ni = nz * W + nx;
        if (g.blocked[ni] || closed[ni]) continue;
        if (dx && dz && (g.blocked[cz * W + nx] || g.blocked[nz * W + cx])) continue; // no corner cutting
        const ng = gScore[cur] + (dx && dz ? SQRT2 : 1);
        if (ng < gScore[ni]) {
          gScore[ni] = ng;
          parent[ni] = cur;
          open.push(ng + heur(nx, nz), ni);
        }
      }
  }
  if (!found) return null;

  const cells: Vec2[] = [];
  for (let c = goal; c !== -1; c = parent[c]) {
    const ix = c % W;
    cells.push(toWorld(g, ix, (c - ix) / W));
    if (c === start) break;
  }
  cells.reverse();
  cells[0] = s;
  cells[cells.length - 1] = t;

  // string pulling
  const out: Vec2[] = [];
  let anchor = 0;
  while (anchor < cells.length - 1) {
    let far = anchor + 1;
    for (let k = cells.length - 1; k > anchor + 1; k--) {
      if (lineClear(g, cells[anchor], cells[k])) { far = k; break; }
    }
    out.push(cells[far]);
    anchor = far;
  }
  return out;
}

export const pathLength = (from: Vec2, path: Vec2[]): number => {
  let len = 0, px = from[0], pz = from[1];
  for (const [x, z] of path) { len += Math.hypot(x - px, z - pz); px = x; pz = z; }
  return len;
};

// ---- deterministic randomness ----------------------------------------------------------------------------------

export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Scatter `count` points around (cx, cz) on walkable ground, at least `minDist` apart (Poisson-ish dart throwing). */
export function scatterWalkable(g: NavGrid, cx: number, cz: number, radius: number, count: number, minDist: number, rng: () => number): Vec2[] {
  const pts: Vec2[] = [];
  let guard = 0;
  let md = minDist;
  while (pts.length < count && guard++ < 4000) {
    if (guard % 400 === 0) md *= 0.85; // relax if the area is cramped
    const a = rng() * Math.PI * 2;
    const r = Math.sqrt(rng()) * radius;
    const x = cx + Math.cos(a) * r, z = cz + Math.sin(a) * r;
    if (!isWalkable(g, x, z) || nearColumn(x, z, 1.2)) continue;
    if (pts.some(([px, pz]) => Math.hypot(px - x, pz - z) < md)) continue;
    pts.push([x, z]);
  }
  return pts;
}
