// Agent figures. One base silhouette per team, then a look of its own for every role:
//   red   (8 fraud schemes)  hooded fraudster in a faceted cloak; each scheme adds its tell (ghost wisps, swapping bank cards,
//                            a twin, a splitting blade, a faceless badge, an inflating balloon, a tipping scale, rising chevrons)
//   blue  (10 gate rules)    armoured guard with shield, spear, cape and a crest that grows with the rule's severity; each
//                            rule hovers its own emblem above its head (hourglass, limit bar, magnifier, padlock, chain, ...)
//   green (12 client trades) round client with a trade of its own (folders, parcels, hard hat, chef hat, laptop, ...)
// Plain three.js (no JSX) so the world loop can animate every figure in one pass.
import * as THREE from "three";
import { AGENT_SCALE } from "@/lib/arena/config";
import { BLUE_RULES, TEAM_META } from "@/lib/arena/roster";
import type { SimAgent } from "@/lib/arena/sim";
import type { AgentSpec, Team } from "@/lib/arena/types";
import { beaconTexture, glyphTexture, shared } from "./assets";

export interface AnimState {
  walk: number;
  sway: number;
  pitching: boolean;
  caught: boolean;
  dash: boolean;
}
type AnimFn = (t: number, dt: number, s: AnimState) => void;

export interface FigureHandle {
  id: string;
  team: Team;
  root: THREE.Group;
  body: THREE.Group;
  ring: THREE.Mesh;
  pillar: THREE.Mesh;
  hit: THREE.Mesh;
  /** emissive materials the flash/hover/status effects drive */
  glow: { mat: THREE.MeshStandardMaterial; base: number }[];
  shards?: THREE.Group;
  card?: THREE.Mesh;
  ice: THREE.Mesh;
  limbs: { armL: THREE.Group; armR: THREE.Group; legL: THREE.Group; legR: THREE.Group };
  anim: AnimFn[];
  phase: number;
  seed: number;
  pillarH: number;
  ringS: number;
}

/** id → live figure. Filled by ArenaWorld on mount, read by the world loop and the picker. */
export const figures = new Map<string, FigureHandle>();

// ───────────────────────────────────────────── helpers ──────────────────────────────────────────────────────────────

const cache = new Map<string, THREE.BufferGeometry>();
function cached<T extends THREE.BufferGeometry>(key: string, make: () => T): T {
  let g = cache.get(key);
  if (!g) { g = make(); cache.set(key, g); }
  return g as T;
}
const gBox = (w: number, h: number, d: number) => cached(`b${w},${h},${d}`, () => new THREE.BoxGeometry(w, h, d));
const gCyl = (rt: number, rb: number, h: number, s = 10) => cached(`c${rt},${rb},${h},${s}`, () => new THREE.CylinderGeometry(rt, rb, h, s));
const gSph = (r: number, w = 12, h = 9) => cached(`s${r},${w},${h}`, () => new THREE.SphereGeometry(r, w, h));
const gCone = (r: number, h: number, s = 8, open = false) => cached(`n${r},${h},${s},${open}`, () => new THREE.ConeGeometry(r, h, s, 1, open));
const gTor = (r: number, t: number, rs = 8, ts = 24, arc = Math.PI * 2) => cached(`t${r},${t},${rs},${ts},${arc}`, () => new THREE.TorusGeometry(r, t, rs, ts, arc));
const gPlane = (w: number, h: number) => cached(`p${w},${h}`, () => new THREE.PlaneGeometry(w, h));
const gCap = (r: number, l: number) => cached(`k${r},${l}`, () => new THREE.CapsuleGeometry(r, l, 4, 8));
const gHalf = (r: number) => cached(`h${r}`, () => new THREE.SphereGeometry(r, 14, 8, 0, Math.PI * 2, 0, Math.PI * 0.55));
const gTri = cached("tri", () => {
  const s = new THREE.Shape();
  s.moveTo(0, 0); s.lineTo(0.5, 0.16); s.lineTo(0, 0.32); s.closePath();
  return new THREE.ShapeGeometry(s);
});

const additive = (color: THREE.ColorRepresentation, opacity: number, map?: THREE.Texture) => {
  const m = new THREE.MeshBasicMaterial({ color, transparent: true, opacity, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide, toneMapped: false });
  if (map) m.map = map;
  return m;
};

const smoothstep = (a: number, b: number, x: number) => { const t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t); };

interface Ctx {
  key: string;
  index: number;
  team: Team;
  torso: THREE.Group;
  head: THREE.Group;
  armL: THREE.Group;
  armR: THREE.Group;
  col: THREE.Color;
  accent: THREE.Color;
  cloakMat?: THREE.MeshStandardMaterial;
  lit: (color: THREE.ColorRepresentation, emissive: THREE.ColorRepresentation, intensity: number, p?: THREE.MeshStandardMaterialParameters) => THREE.MeshStandardMaterial;
  holo: (color: THREE.ColorRepresentation, opacity: number) => THREE.MeshBasicMaterial;
  mesh: (g: THREE.BufferGeometry, m: THREE.Material, x?: number, y?: number, z?: number, parent?: THREE.Object3D) => THREE.Mesh;
  group: (x: number, y: number, z: number, parent?: THREE.Object3D) => THREE.Group;
  glyph: (g: string, fg?: string, bg?: string) => THREE.MeshBasicMaterial;
  anim: (fn: AnimFn) => void;
}

// ───────────────────────────────────────────── red: fraudsters ──────────────────────────────────────────────────────

const RED_ACCENT: Record<string, number> = {
  ghost_vendor: 0xff6b7e, bank_swap: 0xffb347, duplicate_invoice: 0xff4fd8, threshold_split: 0xff7a2e,
  ghost_employee: 0xeeeeff, expense_inflation: 0xff5fa2, po_mismatch: 0xff2e49, amount_drift: 0xffd24a,
};

function redBase(c: Ctx) {
  const { torso, lit, mesh, accent } = c;
  c.cloakMat = lit(0x14070c, accent, 0.22, { roughness: 0.6 });
  torso.add(mesh(shared.redCloak(), c.cloakMat));
  c.head.position.set(0, 1.74, 0);
  mesh(shared.head(), lit(0x0c0508, accent, 0.1), 0, 0, 0, c.head);
  const hood = mesh(shared.hood(), lit(0x14070c, accent, 0.2), 0, 0.16, -0.03, c.head);
  hood.rotation.x = -0.18;
  mesh(shared.visor(), lit(0x200000, accent, 2.6, { flatShading: false }), 0, 0.01, 0.17, c.head).castShadow = false;
  const hem = new THREE.Mesh(gTor(0.6, 0.025, 6, 20), additive(accent, 0.9));
  hem.rotation.x = Math.PI / 2; hem.position.y = 0.05;
  torso.add(hem);
  // sleeves with glowing hands
  for (const arm of [c.armL, c.armR]) {
    mesh(gCap(0.09, 0.42), lit(0x14070c, accent, 0.2), 0, -0.3, 0, arm);
    mesh(gSph(0.085, 8, 6), lit(0x200000, accent, 1.2, { flatShading: false }), 0, -0.62, 0.02, arm);
  }
}

const RED_ROLES: Record<string, (c: Ctx) => void> = {
  // a see-through cloak, trailing wisps and a forged invoice floating at its side
  ghost_vendor(c) {
    const m = c.cloakMat!;
    m.transparent = true; m.opacity = 0.55; m.depthWrite = false;
    for (let i = 0; i < 3; i++) {
      const w = c.mesh(gCone(0.12, 0.55, 6), c.holo(c.accent, 0.5), Math.cos(i * 2.1) * 0.5, 0.15, Math.sin(i * 2.1) * 0.5, c.torso);
      w.rotation.x = Math.PI;
      c.anim((t) => { w.position.y = 0.15 + Math.sin(t * 2 + i * 2) * 0.1; w.scale.setScalar(0.85 + 0.25 * Math.sin(t * 3 + i)); });
    }
    const paper = c.mesh(gPlane(0.4, 0.52), c.glyph("$?", "#ffd7dc", "#2a0a10"), 0.62, 1.3, 0.2, c.torso);
    c.anim((t) => { paper.position.y = 1.3 + Math.sin(t * 1.7) * 0.08; paper.rotation.y = Math.sin(t * 0.9) * 0.5; });
  },
  // two bank cards forever trading places around the chest
  bank_swap(c) {
    const cards = [0, 1].map(() => c.mesh(gBox(0.38, 0.24, 0.02), c.lit(0x2a1500, c.accent, 1.4), 0.6, 1.15, 0, c.torso));
    c.anim((t) => cards.forEach((m, i) => {
      const a = t * 1.9 + i * Math.PI;
      m.position.set(Math.cos(a) * 0.66, 1.15 + Math.sin(a * 2) * 0.1, Math.sin(a) * 0.66);
      m.rotation.y = -a;
    }));
  },
  // a faint twin standing at its shoulder
  duplicate_invoice(c) {
    const twin = c.group(0.62, 0, -0.42, c.torso);
    const body = c.mesh(shared.redCloak(), c.holo(c.accent, 0.26), 0, 0, 0, twin);
    body.scale.setScalar(0.9);
    c.mesh(gSph(0.2, 10, 8), c.holo(c.accent, 0.3), 0, 1.6, 0, twin);
    const papers = [0, 1].map((i) => c.mesh(gPlane(0.34, 0.44), c.glyph("$", "#ffd0f1", "#2a0a24"), -0.5 + i * 0.07, 1.25 + i * 0.05, 0.3, c.torso));
    c.anim((t) => { twin.position.y = Math.sin(t * 1.6) * 0.05; papers.forEach((p, i) => { p.rotation.y = 0.4 + Math.sin(t + i) * 0.1; }); });
  },
  // a glowing blade and three slips of paper fanned in the other hand
  threshold_split(c) {
    const blade = c.mesh(gBox(0.07, 1.0, 0.025), c.lit(0x201005, c.accent, 2.2, { flatShading: false }), 0, -0.82, 0.12, c.armR);
    blade.rotation.x = 0.35;
    for (let i = 0; i < 3; i++) {
      const p = c.mesh(gPlane(0.3, 0.42), c.holo(0xffe2cf, 0.9), 0, -0.82, 0.12, c.armL);
      p.rotation.z = (i - 1) * 0.45; p.position.x = (i - 1) * 0.07;
    }
  },
  // no face, just a blank mask and a badge nobody issued
  ghost_employee(c) {
    const mask = c.mesh(gSph(0.2, 12, 9), c.lit(0xdedeff, 0xffffff, 0.5, { flatShading: false }), 0, 0, 0.1, c.head);
    mask.scale.z = 0.55;
    const badge = c.mesh(gPlane(0.34, 0.46), c.glyph("?", "#eef", "#14122a"), 0, 1.12, 0.52, c.torso);
    c.mesh(gCyl(0.012, 0.012, 0.5, 4), c.holo(0xeeeeff, 0.6), 0, 1.4, 0.5, c.torso);
    c.anim((t, _dt, s) => { badge.rotation.z = Math.sin(t * 2.2) * 0.12 + s.sway * 0.1 * s.walk; });
  },
  // a balloon of receipts that keeps swelling
  expense_inflation(c) {
    const group = c.group(0.55, 2.5, 0.1, c.torso);
    const b = c.mesh(gSph(0.36, 14, 10), c.lit(0x2a0818, c.accent, 1.1, { flatShading: false }), 0, 0, 0, group);
    c.mesh(gPlane(0.3, 0.38), c.glyph("$", "#ffe3ef", "#3a0c22"), 0, 0, 0.37, group);
    c.mesh(gCyl(0.012, 0.012, 1.2, 4), c.holo(0xffd0e3, 0.55), 0.0, -0.78, 0, group);
    c.anim((t) => { const k = 1 + 0.14 * Math.sin(t * 2.2); b.scale.setScalar(k); group.position.y = 2.5 + Math.sin(t * 1.3) * 0.08; });
  },
  // a scale that never balances
  po_mismatch(c) {
    const g = c.group(0, 2.5, 0, c.torso);
    c.mesh(gBox(1.1, 0.06, 0.06), c.lit(0x1a0508, c.accent, 1.6, { flatShading: false }), 0, 0, 0, g);
    c.mesh(gCyl(0.025, 0.025, 0.4, 5), c.holo(c.accent, 0.5), 0, -0.2, 0, g);
    for (const s of [-1, 1]) {
      c.mesh(gCyl(0.22, 0.22, 0.04, 14), c.lit(0x1a0508, c.accent, 1.3, { flatShading: false }), s * 0.55, -0.36, 0, g);
      c.mesh(gCyl(0.012, 0.012, 0.36, 4), c.holo(c.accent, 0.5), s * 0.55, -0.18, 0, g);
    }
    c.anim((t) => { g.rotation.z = 0.42 * Math.sin(t * 1.1); });
  },
  // chevrons forever creeping upward
  amount_drift(c) {
    const ch = [0, 1, 2].map(() => c.mesh(gCone(0.14, 0.3, 4), c.lit(0x241200, c.accent, 2, { flatShading: false }), 0, 2.2, 0, c.torso));
    c.anim((t) => ch.forEach((m, i) => { const f = (t * 0.7 + i / 3) % 1; m.position.y = 2.1 + f * 1.0; m.scale.setScalar(1 - f * 0.65); m.rotation.y = t * 2; }));
  },
};

// ───────────────────────────────────────────── blue: guards ─────────────────────────────────────────────────────────

const BLUE_ACCENT: Record<string, number> = {
  vendor_age_lt_7d: 0x5ad1ff, near_threshold: 0x7fb0ff, duplicate_invoice: 0x8f9bff, recent_bank_change: 0x4de3d1, bank_change_with_open_invoices: 0xa17bff,
  no_po_from_po_vendor: 0x6fe0ff, over_po_amount: 0x5a9bff, recurring_drift: 0x7fe3ff, employee_bank_matches_vendor: 0x9fc2ff, already_flagged_high: 0xff7a8a,
};

function blueBase(c: Ctx) {
  const { torso, lit, mesh, col, accent } = c;
  const sev = BLUE_RULES.find((r) => r.key === c.key)?.severity ?? 1;
  mesh(shared.blueBody(), lit(0x1b3f78, col, 0.2, { metalness: 0.65, roughness: 0.32 }), 0, 0, 0, torso);
  for (const sx of [-1, 1]) {
    mesh(shared.pauldron(), lit(0x2d5fae, col, 0.2, { metalness: 0.6 }), sx * 0.52, 1.3, 0, torso);
    if (sev === 3) { const spike = mesh(gCone(0.07, 0.3, 6), lit(0x2d5fae, accent, 0.9), sx * 0.6, 1.5, 0, torso); spike.rotation.z = -sx * 0.4; }
  }
  c.head.position.set(0, 1.58, 0);
  mesh(shared.helmet(), lit(0x2f5596, col, 0.2, { metalness: 0.7, roughness: 0.3 }), 0, 0, 0, c.head);
  mesh(shared.visor(), lit(0x00101f, accent, 2.6, { flatShading: false }), 0, 0.08, 0.2, c.head).castShadow = false;
  // the helmet crest grows with severity: none / a low fin / a tall fin
  if (sev >= 2) mesh(gBox(0.05, sev === 3 ? 0.34 : 0.2, 0.46), lit(0x2f5596, accent, sev === 3 ? 1.1 : 0.6), 0, 0.28, -0.02, c.head);
  // chest plate, belt and a short cape
  mesh(gBox(0.32, 0.3, 0.05), lit(0x0f3366, accent, 1.3, { flatShading: false }), 0, 1.0, 0.5, torso);
  const belt = new THREE.Mesh(gTor(0.5, 0.03, 6, 24), additive(accent, 0.8));
  belt.rotation.x = Math.PI / 2; belt.position.y = 0.62;
  torso.add(belt);
  const cape = mesh(gPlane(0.8, 1.2), lit(0x1b3f78, col, 0.18, { flatShading: false, side: THREE.DoubleSide }), 0, 0.95, -0.5, torso);
  c.anim((t, _dt, s) => { cape.rotation.x = 0.12 + s.walk * 0.45 + Math.sin(t * 3) * 0.04 * (0.3 + s.walk); });
  // shield on the left arm, spear in the right hand
  const shield = mesh(shared.shield(), lit(0x234f94, col, 0.9, { metalness: 0.4 }), -0.1, -0.5, 0.3, c.armL);
  shield.rotation.set(Math.PI / 2, 0.5, Math.PI / 6);
  mesh(shared.spear(), lit(0x1a2a44, col, 0.2), 0.0, -0.4, 0.08, c.armR);
  mesh(shared.spearTip(), lit(0x00101f, accent, 2.2, { flatShading: false }), 0.0, 0.7, 0.08, c.armR);
  for (const arm of [c.armL, c.armR]) mesh(gCap(0.1, 0.4), lit(0x1b3f78, col, 0.2, { metalness: 0.6 }), 0, -0.28, 0, arm);
}

/** Every guard hovers an emblem above its head: the rule it embodies, turning slowly. */
function emblem(c: Ctx, build: (g: THREE.Group) => void, spin = 0.9) {
  const g = c.group(0, 2.8, 0, c.torso);
  build(g);
  const halo = c.mesh(gTor(0.5, 0.012, 6, 36), c.holo(c.accent, 0.5), 0, -0.05, 0, g);
  halo.rotation.x = Math.PI / 2;
  c.anim((t) => { g.rotation.y = t * spin; g.position.y = 2.8 + Math.sin(t * 1.4 + c.index) * 0.06; });
  return g;
}

const BLUE_ROLES: Record<string, (c: Ctx) => void> = {
  // an hourglass that flips: a vendor under a week old
  vendor_age_lt_7d(c) {
    const g = emblem(c, (g) => {
      const m = c.lit(0x061420, c.accent, 1.5, { flatShading: false });
      const top = c.mesh(gCone(0.2, 0.3, 10), m, 0, 0.15, 0, g); top.rotation.x = Math.PI;
      c.mesh(gCone(0.2, 0.3, 10), m, 0, -0.15, 0, g);
      for (const y of [-0.31, 0.31]) c.mesh(gCyl(0.24, 0.24, 0.03, 10), m, 0, y, 0, g);
    }, 0.5);
    c.anim((t) => { const p = (t % 4) / 4; g.rotation.z = Math.PI * (Math.floor(t / 4) + smoothstep(0.82, 1, p)); });
  },
  // the limit line: a bar across two posts
  near_threshold(c) {
    emblem(c, (g) => {
      const m = c.lit(0x061420, c.accent, 1.6, { flatShading: false });
      for (const s of [-1, 1]) c.mesh(gBox(0.06, 0.5, 0.06), m, s * 0.42, 0, 0, g);
      c.mesh(gBox(0.9, 0.08, 0.08), m, 0, 0.06, 0, g);
      c.mesh(gCone(0.1, 0.22, 4), c.holo(c.accent, 0.9), 0, -0.3, 0, g);
    });
  },
  // a magnifier checking for twins
  duplicate_invoice(c) {
    emblem(c, (g) => {
      const m = c.lit(0x061420, c.accent, 1.5, { flatShading: false });
      c.mesh(gTor(0.26, 0.04, 8, 28), m, 0, 0.05, 0, g);
      c.mesh(gCyl(0.03, 0.03, 0.36, 6), m, 0.24, -0.26, 0, g).rotation.z = -0.8;
      c.mesh(gCyl(0.25, 0.25, 0.01, 24), c.holo(c.accent, 0.22), 0, 0.05, 0, g).rotation.x = Math.PI / 2;
    });
  },
  // a padlock on recent bank changes
  recent_bank_change(c) {
    emblem(c, (g) => {
      const m = c.lit(0x061420, c.accent, 1.5, { flatShading: false });
      c.mesh(gBox(0.36, 0.3, 0.14), m, 0, -0.05, 0, g);
      c.mesh(gTor(0.13, 0.035, 8, 18, Math.PI), m, 0, 0.1, 0, g);
      c.mesh(gBox(0.05, 0.1, 0.16), c.holo(0xffffff, 0.9), 0, -0.05, 0, g);
    });
  },
  // two links of chain: the trap for a bank swap
  bank_change_with_open_invoices(c) {
    emblem(c, (g) => {
      const m = c.lit(0x061420, c.accent, 1.5, { flatShading: false });
      c.mesh(gTor(0.2, 0.05, 8, 20), m, -0.14, 0, 0, g);
      const b = c.mesh(gTor(0.2, 0.05, 8, 20), m, 0.14, 0, 0, g);
      b.rotation.y = Math.PI / 2;
    }, 1.2);
  },
  // a clipboard: an invoice with no purchase order
  no_po_from_po_vendor(c) {
    emblem(c, (g) => {
      c.mesh(gBox(0.42, 0.56, 0.03), c.lit(0x0a1c30, c.accent, 0.9, { flatShading: false }), 0, 0, 0, g);
      c.mesh(gBox(0.16, 0.07, 0.05), c.lit(0x061420, c.accent, 1.8, { flatShading: false }), 0, 0.28, 0, g);
      for (let i = 0; i < 3; i++) c.mesh(gBox(0.28, 0.03, 0.04), c.holo(0xdff6ff, 0.85), 0, 0.12 - i * 0.14, 0.02, g);
    }, 0.7);
  },
  // a ceiling over the head: nothing may exceed its PO
  over_po_amount(c) {
    emblem(c, (g) => {
      const m = c.lit(0x061420, c.accent, 1.5, { flatShading: false });
      c.mesh(gBox(1.0, 0.06, 0.6), m, 0, 0.12, 0, g);
      const arrow = c.mesh(gCone(0.12, 0.26, 4), c.holo(c.accent, 0.9), 0, -0.12, 0, g);
      arrow.rotation.x = Math.PI;
      c.anim((t) => { arrow.position.y = -0.1 - 0.06 * Math.abs(Math.sin(t * 2.4)); });
    }, 0.6);
  },
  // a radar dish sweeping for drift
  recurring_drift(c) {
    emblem(c, (g) => {
      const m = c.lit(0x061420, c.accent, 1.4, { flatShading: false });
      c.mesh(gCyl(0.03, 0.03, 0.5, 6), m, 0, -0.1, 0, g);
      const dish = c.mesh(gCone(0.36, 0.18, 18, true), m, 0, 0.18, 0, g);
      dish.rotation.x = -0.9;
      c.mesh(gSph(0.05, 8, 6), c.holo(0xffffff, 0.95), 0, 0.28, 0.1, g);
    }, 1.8);
  },
  // an ID badge on a lanyard
  employee_bank_matches_vendor(c) {
    emblem(c, (g) => {
      c.mesh(gPlane(0.5, 0.34), c.glyph("ID", "#d9e8ff", "#0a1c30"), 0, 0, 0, g);
      c.mesh(gBox(0.1, 0.06, 0.03), c.lit(0x061420, c.accent, 1.8, { flatShading: false }), 0, 0.2, 0, g);
    }, 0.8);
  },
  // a flag planted on whatever was flagged high
  already_flagged_high(c) {
    emblem(c, (g) => {
      c.mesh(gCyl(0.025, 0.025, 0.9, 6), c.lit(0x061420, 0xffffff, 0.6, { flatShading: false }), 0, -0.05, 0, g);
      const flag = c.mesh(gTri, c.lit(0x300008, 0xff3b52, 1.8, { flatShading: false, side: THREE.DoubleSide }), 0, 0.14, 0, g);
      c.anim((t) => { flag.rotation.y = Math.sin(t * 3) * 0.35; });
    }, 0.7);
  },
};

// ───────────────────────────────────────────── green: clients ───────────────────────────────────────────────────────

const GREEN_BODY = [0x0e2a22, 0x103326, 0x0d2d2a, 0x12301f, 0x0b2c2f, 0x152b1d, 0x0f2e25, 0x112b2d, 0x14331f, 0x0c2a27, 0x13301e, 0x0e2f2c];
const GREEN_HEAD = [0x9ff0cf, 0xc2f5d9, 0x86e6bf, 0xb5f0a8, 0xa8f0e0, 0xd2f7c4, 0x93eac6, 0xbdf2dc, 0xa3ecb4, 0xc9f5e9, 0x8fe8b8, 0xb0f0d0];

function greenBase(c: Ctx) {
  const { lit, mesh, col, index } = c;
  const body = lit(GREEN_BODY[index % 12], col, 0.2, { flatShading: false, roughness: 0.45 });
  mesh(shared.capsule(), body, 0, 0.72, 0, c.torso);
  c.head.position.set(0, 1.58, 0);
  mesh(shared.sphereHead(), lit(GREEN_HEAD[index % 12], col, 0.25, { flatShading: false, metalness: 0.05 }), 0, 0, 0, c.head);
  for (const arm of [c.armL, c.armR]) {
    mesh(gCap(0.09, 0.4), body, 0, -0.26, 0, arm);
    mesh(gSph(0.08, 8, 6), lit(GREEN_HEAD[index % 12], col, 0.2, { flatShading: false }), 0, -0.55, 0.02, arm);
  }
  // a collar line so the head reads as a head from above
  const collar = new THREE.Mesh(gTor(0.26, 0.02, 6, 20), additive(col, 0.5));
  collar.rotation.x = Math.PI / 2; collar.position.y = 1.32;
  c.torso.add(collar);
}

const wood = (c: Ctx) => c.lit(0x2a1a0e, 0xffb15a, 0.12, { flatShading: false });
const white = (c: Ctx) => c.lit(0xe9f5ee, 0xcffff0, 0.25, { flatShading: false });

/** Twelve trades, one per client slot. */
const GREEN_TRADES: ((c: Ctx) => void)[] = [
  // 01 office supplies: a stack of folders and glasses
  (c) => {
    [0, 1, 2].forEach((i) => c.mesh(gBox(0.34, 0.045, 0.26), i % 2 ? white(c) : c.lit(0x0b3b30, c.col, 0.5, { flatShading: false }), 0, -0.55 + i * 0.05, 0.22, c.armL));
    for (const s of [-1, 1]) c.mesh(gTor(0.07, 0.012, 6, 14), c.holo(0xd8fff0, 0.9), s * 0.1, 0.02, 0.2, c.head);
  },
  // 02 logistics: a parcel on the shoulder
  (c) => {
    c.mesh(gBox(0.5, 0.4, 0.42), wood(c), 0.28, 1.78, 0, c.torso);
    c.mesh(gBox(0.52, 0.05, 0.1), white(c), 0.28, 1.78, 0, c.torso);
  },
  // 03 construction: hard hat and hi-vis vest
  (c) => {
    c.mesh(gHalf(0.27), c.lit(0x3a3000, 0xffd24a, 0.55, { flatShading: false }), 0, 0.06, 0, c.head);
    c.mesh(gCyl(0.3, 0.3, 0.03, 14), c.lit(0x3a3000, 0xffd24a, 0.4, { flatShading: false }), 0, 0.06, 0.06, c.head);
    c.mesh(gBox(0.72, 0.5, 0.5), c.lit(0x2a1400, 0xff8a2e, 0.5, { flatShading: false }), 0, 0.95, 0, c.torso).scale.set(1, 1, 1);
    c.mesh(gBox(0.74, 0.06, 0.52), white(c), 0, 1.0, 0, c.torso);
  },
  // 04 café: a chef's hat and apron
  (c) => {
    c.mesh(gCyl(0.19, 0.22, 0.26, 12), white(c), 0, 0.34, 0, c.head);
    c.mesh(gSph(0.25, 12, 8), white(c), 0, 0.56, 0, c.head);
    c.mesh(gBox(0.5, 0.55, 0.03), white(c), 0, 0.78, 0.37, c.torso);
  },
  // 05 IT: a laptop, screen glowing
  (c) => {
    c.mesh(gBox(0.46, 0.03, 0.32), c.lit(0x111418, 0x7fe3ff, 0.2, { flatShading: false }), 0, -0.52, 0.28, c.armL);
    const lid = c.mesh(gBox(0.46, 0.32, 0.02), c.lit(0x111418, 0x7fe3ff, 0.2, { flatShading: false }), 0, -0.4, 0.14, c.armL);
    lid.rotation.x = -0.35;
    c.mesh(gPlane(0.4, 0.26), c.holo(0x7fe3ff, 0.85), 0, -0.4, 0.155, c.armL).rotation.x = -0.35;
  },
  // 06 utilities: a wrench at the hip and a gear overhead
  (c) => {
    const w = c.mesh(gCyl(0.03, 0.03, 0.62, 6), c.lit(0x1a1f24, 0xbfd0d8, 0.3, { flatShading: false }), 0.4, 0.62, 0.08, c.torso);
    w.rotation.z = 0.5;
    c.mesh(gTor(0.09, 0.03, 6, 14, Math.PI * 1.5), c.lit(0x1a1f24, 0xbfd0d8, 0.3, { flatShading: false }), 0.56, 0.9, 0.08, c.torso);
    const gear = c.mesh(gCyl(0.28, 0.28, 0.06, 8), c.lit(0x102018, c.col, 1.4, { flatShading: false }), 0, 2.45, 0, c.torso);
    gear.rotation.x = Math.PI / 2;
    c.anim((t) => { gear.rotation.z = t * 1.2; });
  },
  // 07 legal: a briefcase and a tie
  (c) => {
    c.mesh(gBox(0.42, 0.3, 0.13), c.lit(0x2a1a0e, 0xd99a4a, 0.15, { flatShading: false }), 0, -0.66, 0.1, c.armR);
    c.mesh(gTor(0.07, 0.015, 6, 12, Math.PI), c.lit(0x2a1a0e, 0xd99a4a, 0.15, { flatShading: false }), 0, -0.5, 0.1, c.armR);
    c.mesh(gBox(0.09, 0.42, 0.03), c.lit(0x0b3b30, c.col, 0.9, { flatShading: false }), 0, 1.12, 0.37, c.torso);
  },
  // 08 marketing: a megaphone
  (c) => {
    const g = c.group(0, -0.5, 0.2, c.armR);
    c.mesh(gCone(0.2, 0.42, 12, true), c.lit(0x3a1a00, 0xff8a2e, 0.9, { flatShading: false, side: THREE.DoubleSide }), 0, 0.1, 0.1, g).rotation.x = Math.PI / 2;
    c.mesh(gCyl(0.07, 0.07, 0.18, 8), c.lit(0x222222, 0xffffff, 0.2, { flatShading: false }), 0, -0.06, -0.12, g).rotation.x = Math.PI / 2;
    g.rotation.x = -1.0;
  },
  // 09 cleaning: bucket and mop
  (c) => {
    c.mesh(gCyl(0.17, 0.12, 0.24, 10), c.lit(0x0c2a3a, 0x7fe3ff, 0.35, { flatShading: false }), 0, -0.72, 0.1, c.armL);
    const mop = c.mesh(gCyl(0.02, 0.02, 1.5, 5), wood(c), 0, -0.3, 0.12, c.armR);
    mop.rotation.x = 0.1;
    c.mesh(gBox(0.32, 0.1, 0.1), white(c), 0, -1.05, 0.14, c.armR);
  },
  // 10 printing: a paper roll across the shoulders
  (c) => {
    const r = c.mesh(gCyl(0.14, 0.14, 0.78, 12), white(c), 0, 1.62, -0.2, c.torso);
    r.rotation.z = Math.PI / 2;
    c.mesh(gCyl(0.145, 0.145, 0.05, 12), c.lit(0x051a20, 0x7fe3ff, 1.2, { flatShading: false }), 0.2, 1.62, -0.2, c.torso).rotation.z = Math.PI / 2;
  },
  // 11 courier: a cap and a parcel in both hands
  (c) => {
    c.mesh(gCyl(0.26, 0.27, 0.1, 14), c.lit(0x0b2a3a, 0x6fb7ff, 0.5, { flatShading: false }), 0, 0.13, 0, c.head);
    c.mesh(gBox(0.32, 0.03, 0.2), c.lit(0x0b2a3a, 0x6fb7ff, 0.5, { flatShading: false }), 0, 0.1, 0.26, c.head);
    c.mesh(gBox(0.4, 0.3, 0.3), wood(c), 0, -0.55, 0.3, c.armL);
    c.mesh(gBox(0.42, 0.05, 0.08), white(c), 0, -0.55, 0.3, c.armL);
  },
  // 12 consulting: glasses, a tie and a clipboard
  (c) => {
    for (const s of [-1, 1]) c.mesh(gTor(0.07, 0.012, 6, 14), c.holo(0xd8fff0, 0.9), s * 0.1, 0.02, 0.2, c.head);
    c.mesh(gBox(0.09, 0.42, 0.03), c.lit(0x3a0c22, 0xff5fa2, 0.8, { flatShading: false }), 0, 1.12, 0.37, c.torso);
    c.mesh(gBox(0.3, 0.4, 0.03), white(c), 0, -0.55, 0.22, c.armR);
    c.mesh(gBox(0.12, 0.05, 0.04), c.lit(0x222222, 0xffffff, 0.3, { flatShading: false }), 0, -0.35, 0.22, c.armR);
  },
];

// ───────────────────────────────────────────── building a figure ────────────────────────────────────────────────────

export function buildFigure(spec: AgentSpec): FigureHandle {
  const team = spec.team;
  const meta = TEAM_META[team];
  const col = new THREE.Color(meta.hex);
  const key = spec.id.slice(spec.id.indexOf(":") + 1);
  const glow: FigureHandle["glow"] = [];
  const anim: AnimFn[] = [];

  const accentHex = team === "red" ? RED_ACCENT[key] : team === "blue" ? BLUE_ACCENT[key] : undefined;
  const accent = new THREE.Color(accentHex ?? meta.glow);

  const lit: Ctx["lit"] = (color, emissive, intensity, p = {}) => {
    const mat = new THREE.MeshStandardMaterial({ color, emissive, emissiveIntensity: intensity, roughness: 0.5, metalness: 0.25, flatShading: true, ...p });
    glow.push({ mat, base: intensity });
    return mat;
  };
  const holo: Ctx["holo"] = (color, opacity) => additive(color, opacity);
  const mesh: Ctx["mesh"] = (g, m, x = 0, y = 0, z = 0, parent) => {
    const o = new THREE.Mesh(g, m);
    o.position.set(x, y, z);
    (parent ?? body).add(o);
    return o;
  };
  const group: Ctx["group"] = (x, y, z, parent) => {
    const g = new THREE.Group();
    g.position.set(x, y, z);
    (parent ?? body).add(g);
    return g;
  };
  const glyph: Ctx["glyph"] = (g, fg = "#ffffff", bg = "#101010") => new THREE.MeshBasicMaterial({ map: glyphTexture(g, fg, bg), side: THREE.DoubleSide, toneMapped: false, transparent: true });

  const root = new THREE.Group();
  root.name = spec.id;
  root.scale.setScalar(AGENT_SCALE);
  const body = new THREE.Group();
  root.add(body);

  // torso sits on short legs; arms hang from the shoulders
  const torso = group(0, 0.24, 0, body);
  const head = group(0, 1.6, 0, torso);
  const armL = group(-0.42, 1.36, 0, torso);
  const armR = group(0.42, 1.36, 0, torso);
  const mkLeg = (x: number) => {
    const leg = group(x, 0.5, 0, body);
    const mat = lit(team === "red" ? 0x14070c : team === "blue" ? 0x1b3f78 : GREEN_BODY[spec.index % 12], team === "green" ? col : accent, 0.12, { flatShading: false });
    mesh(gCap(0.1, 0.28), mat, 0, -0.24, 0, leg);
    mesh(gBox(0.2, 0.1, 0.28), mat, 0, -0.5, 0.05, leg);
    return leg;
  };
  const legL = mkLeg(-0.17), legR = mkLeg(0.17);

  const c: Ctx = { key, index: spec.index, team, torso, head, armL, armR, col, accent, lit, holo, mesh, group, glyph, anim: (fn) => { anim.push(fn); } };

  let shards: THREE.Group | undefined;
  let card: THREE.Mesh | undefined;

  if (team === "red") {
    redBase(c);
    shards = new THREE.Group();
    for (let i = 0; i < 3; i++) {
      const s = mesh(shared.shard(), lit(0x200000, accent, 2.2, { flatShading: false }), 0, 0, 0, shards);
      const a = (i / 3) * Math.PI * 2;
      s.position.set(Math.cos(a) * 0.8, 1.0 + i * 0.28, Math.sin(a) * 0.8);
    }
    torso.add(shards);
    RED_ROLES[key]?.(c);
  } else if (team === "blue") {
    blueBase(c);
    BLUE_ROLES[key]?.(c);
  } else {
    greenBase(c);
    GREEN_TRADES[spec.index % GREEN_TRADES.length](c);
    card = new THREE.Mesh(shared.card(), new THREE.MeshBasicMaterial({ map: glyphTexture("$", meta.glow, "#06231b"), side: THREE.DoubleSide, toneMapped: false, transparent: true }));
    card.position.y = 2.6;
    torso.add(card);
    // clients differ a little in size too
    root.scale.multiplyScalar(0.93 + (spec.index % 4) * 0.045);
  }
  body.traverse((o) => { const m = o as THREE.Mesh; if (m.isMesh && (m.material as THREE.Material).transparent !== true) m.castShadow = true; });

  // marker ring on the ground + light pillar
  const ring = new THREE.Mesh(shared.ring(), additive(col, 0.7));
  ring.rotation.x = -Math.PI / 2;
  ring.position.y = 0.06;
  root.add(ring);
  const pillar = new THREE.Mesh(shared.pillar(), additive(col, 0.5, beaconTexture()));
  pillar.scale.set(1.6, 1, 1.6);
  root.add(pillar);

  const ice = new THREE.Mesh(shared.ice(), new THREE.MeshBasicMaterial({ color: 0xbfe9ff, transparent: true, opacity: 0.38, depthWrite: false }));
  ice.scale.set(0.8, 1.7, 0.8);
  ice.position.y = 1.05;
  ice.visible = false;
  root.add(ice);

  // invisible pick volume (the raycaster still tests it)
  const hit = new THREE.Mesh(new THREE.CylinderGeometry(0.9, 0.9, 3.0, 8), new THREE.MeshBasicMaterial());
  hit.visible = false;
  hit.position.y = 1.35;
  hit.userData.agentId = spec.id;
  root.add(hit);

  return { id: spec.id, team, root, body, ring, pillar, hit, glow, shards, card, ice, limbs: { armL, armR, legL, legR }, anim, phase: Math.random() * 6, seed: Math.random() * 100, pillarH: 24, ringS: 1 };
}

export function disposeFigure(h: FigureHandle) {
  // geometries are shared through the cache; only materials belong to this figure
  h.root.traverse((o) => {
    const m = o as THREE.Mesh;
    if (m.isMesh) {
      const mat = m.material as THREE.Material | THREE.Material[];
      (Array.isArray(mat) ? mat : [mat]).forEach((x) => x.dispose());
    }
  });
}

export interface FigureFrame {
  y: number;
  dt: number;
  t: number;
  hovered: boolean;
  selected: boolean;
  engaged: boolean;
}

/** Push one sim agent's state into its figure. */
export function animateFigure(h: FigureHandle, a: SimAgent, f: FigureFrame) {
  const { dt, t } = f;
  h.root.position.set(a.x, f.y, a.z);
  h.root.rotation.y = a.heading;

  const walk = Math.min(1, a.vel / 6);
  h.phase += dt * (1.6 + a.vel * 0.95);
  const sway = Math.sin(h.phase);
  const caught = a.status === "caught";
  const pitching = a.mode === "pitch";
  const dash = a.mode === "dash";

  h.body.position.y = Math.abs(sway) * 0.1 * walk - (caught ? 0.1 : 0);
  h.body.position.x = pitching ? Math.sin(t * 11 + h.seed) * 0.03 : 0;
  h.body.rotation.x = caught ? -0.5 : 0.17 * walk + (pitching ? 0.12 : 0) + (dash ? 0.22 : 0);
  h.body.rotation.z = sway * 0.05 * walk + (caught ? 0.22 : 0);
  const breathe = 1 + Math.sin(t * 1.7 + h.seed) * 0.012 * (1 - walk);
  h.body.scale.set(1, caught ? 0.84 : breathe, 1);

  // limbs: arms and legs swing opposite each other with the stride; a fraudster working a target raises its hand
  const sw = sway * 0.95 * walk;
  const idle = Math.sin(t * 1.3 + h.seed) * 0.05;
  h.limbs.armL.rotation.x = caught ? 0.4 : sw + idle;
  h.limbs.armR.rotation.x = caught ? 0.4 : pitching ? -1.05 + Math.sin(t * 8 + h.seed) * 0.25 : -sw - idle + (dash ? -0.9 : 0);
  h.limbs.legL.rotation.x = -sway * 0.85 * walk;
  h.limbs.legR.rotation.x = sway * 0.85 * walk;

  const st: AnimState = { walk, sway, pitching, caught, dash };
  for (const fn of h.anim) fn(t, dt, st);

  if (h.shards) {
    h.shards.rotation.y += dt * (pitching ? 6 : 2.2);
    h.shards.children.forEach((s, i) => { s.position.y = 1.0 + i * 0.28 + Math.sin(t * 2.4 + i * 2) * 0.12; });
  }
  if (h.card) {
    h.card.rotation.y += dt * 1.4;
    h.card.position.y = 2.6 + Math.sin(t * 2 + h.seed) * 0.08;
    h.card.visible = a.status !== "caught";
    (h.card.material as THREE.MeshBasicMaterial).opacity = a.status === "drained" ? 0.45 : 1;
  }

  // emissive: base, +hover/select, +flash pulse, dimmed when drained/caught
  const boost = 1 + (f.hovered ? 0.7 : 0) + (f.selected ? 1 : 0);
  const dim = caught ? 0.12 : a.status === "drained" ? 0.45 : a.status === "frozen" ? 0.25 : 1;
  const k = a.flash * 3.5;
  for (const g of h.glow) g.mat.emissiveIntensity = g.base * boost * dim + k;
  h.ice.visible = a.status === "frozen";

  // ground ring + pillar
  const tr = f.selected ? 1.7 : f.hovered ? 1.3 : 1;
  h.ringS += (tr - h.ringS) * Math.min(1, dt * 8);
  const pulse = 1 + Math.sin(t * 3 + h.seed) * 0.05;
  h.ring.scale.setScalar(h.ringS * pulse);
  (h.ring.material as THREE.MeshBasicMaterial).opacity = Math.min(1, 0.55 + (f.hovered ? 0.3 : 0) + (f.selected ? 0.4 : 0) + a.flash * 0.5) * (caught ? 0.5 : 1);

  const wantH = f.selected ? 30 : f.engaged ? 7 : 24;
  h.pillarH += (wantH - h.pillarH) * Math.min(1, dt * 2.5);
  h.pillar.scale.set(1.6, h.pillarH / AGENT_SCALE, 1.6);
  h.pillar.position.y = h.pillarH / AGENT_SCALE / 2;
  (h.pillar.material as THREE.MeshBasicMaterial).opacity = (f.engaged && !f.selected && !f.hovered ? 0.3 : 0.55) + a.flash * 0.3;
}
