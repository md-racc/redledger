// Stylised agent figures: one silhouette per team, built from a handful of shared primitives.
//   red   - hooded fraudster in a faceted cloak, red visor, orbiting shards
//   blue  - armoured guard with pauldrons, helmet, hex shield and spear
//   green - round client with a briefcase and a floating $ invoice
// Plain three.js (no JSX) so the world loop can animate every figure in one pass.
import * as THREE from "three";
import { AGENT_SCALE } from "@/lib/arena/config";
import { TEAM_META } from "@/lib/arena/roster";
import type { SimAgent } from "@/lib/arena/sim";
import type { AgentSpec, Team } from "@/lib/arena/types";
import { beaconTexture, glyphTexture, shared } from "./assets";

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
  phase: number;
  seed: number;
  pillarH: number;
  ringS: number;
}

/** id → live figure. Filled by AgentFigures on mount, read by the world loop and the picker. */
export const figures = new Map<string, FigureHandle>();

const additive = (color: THREE.ColorRepresentation, opacity: number, map?: THREE.Texture) => {
  const m = new THREE.MeshBasicMaterial({ color, transparent: true, opacity, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide, toneMapped: false });
  if (map) m.map = map;
  return m;
};

export function buildFigure(spec: AgentSpec): FigureHandle {
  const team = spec.team;
  const meta = TEAM_META[team];
  const col = new THREE.Color(meta.hex);
  const glow: FigureHandle["glow"] = [];

  const lit = (color: THREE.ColorRepresentation, emissive: THREE.ColorRepresentation, intensity: number, o: THREE.MeshStandardMaterialParameters = {}) => {
    const mat = new THREE.MeshStandardMaterial({ color, emissive, emissiveIntensity: intensity, roughness: 0.5, metalness: 0.25, flatShading: true, ...o });
    glow.push({ mat, base: intensity });
    return mat;
  };
  const mesh = (g: THREE.BufferGeometry, m: THREE.Material, x = 0, y = 0, z = 0) => {
    const o = new THREE.Mesh(g, m);
    o.position.set(x, y, z);
    o.castShadow = true;
    return o;
  };

  const root = new THREE.Group();
  root.name = spec.id;
  root.scale.setScalar(AGENT_SCALE);
  const body = new THREE.Group();
  root.add(body);
  let shards: THREE.Group | undefined;
  let card: THREE.Mesh | undefined;

  if (team === "red") {
    body.add(mesh(shared.redCloak(), lit(0x14070c, col, 0.22, { roughness: 0.6 })));
    body.add(mesh(shared.head(), lit(0x0c0508, col, 0.1), 0, 1.74, 0));
    const hood = mesh(shared.hood(), lit(0x14070c, col, 0.2), 0, 1.9, -0.03);
    hood.rotation.x = -0.18;
    body.add(hood);
    const visor = mesh(shared.visor(), lit(0x200000, 0xff2b45, 2.6, { flatShading: false }), 0, 1.75, 0.17);
    visor.castShadow = false;
    body.add(visor);
    const hem = new THREE.Mesh(new THREE.TorusGeometry(0.6, 0.025, 6, 20), additive(col, 0.9));
    hem.rotation.x = Math.PI / 2; hem.position.y = 0.05;
    body.add(hem);
    shards = new THREE.Group();
    for (let i = 0; i < 3; i++) {
      const s = mesh(shared.shard(), lit(0x200000, 0xff3b52, 2.2, { flatShading: false }));
      const a = (i / 3) * Math.PI * 2;
      s.position.set(Math.cos(a) * 0.8, 1.0 + i * 0.28, Math.sin(a) * 0.8);
      s.castShadow = false;
      shards.add(s);
    }
    body.add(shards);
  } else if (team === "blue") {
    body.add(mesh(shared.blueBody(), lit(0x0b1a33, col, 0.14, { metalness: 0.65, roughness: 0.32 })));
    for (const sx of [-1, 1]) body.add(mesh(shared.pauldron(), lit(0x132a52, col, 0.12, { metalness: 0.6 }), sx * 0.52, 1.3, 0));
    body.add(mesh(shared.helmet(), lit(0x14284a, col, 0.12, { metalness: 0.7, roughness: 0.3 }), 0, 1.58, 0));
    const visor = mesh(shared.visor(), lit(0x00101f, 0x5aa0ff, 2.6, { flatShading: false }), 0, 1.66, 0.2);
    visor.castShadow = false;
    body.add(visor);
    const shield = mesh(shared.shield(), lit(0x10305f, 0x3d86ff, 0.9, { metalness: 0.4 }), -0.66, 0.92, 0.16);
    shield.rotation.set(Math.PI / 2, 0, Math.PI / 6);
    shield.rotation.y = 0.5;
    body.add(shield);
    const spear = mesh(shared.spear(), lit(0x1a2a44, col, 0.2), 0.68, 1.0, 0.05);
    body.add(spear);
    body.add(mesh(shared.spearTip(), lit(0x00101f, 0x7fb0ff, 2.2, { flatShading: false }), 0.68, 2.18, 0.05));
    const hem = new THREE.Mesh(new THREE.TorusGeometry(0.56, 0.025, 6, 20), additive(col, 0.9));
    hem.rotation.x = Math.PI / 2; hem.position.y = 0.05;
    body.add(hem);
  } else {
    body.add(mesh(shared.capsule(), lit(0x0e2a22, col, 0.2, { flatShading: false, roughness: 0.45 }), 0, 0.72, 0));
    body.add(mesh(shared.sphereHead(), lit(0x9ff0cf, col, 0.25, { flatShading: false, metalness: 0.05 }), 0, 1.58, 0));
    body.add(mesh(shared.case(), lit(0x0b3b30, col, 0.5, { flatShading: false }), 0.42, 0.62, 0.05));
    card = new THREE.Mesh(shared.card(), new THREE.MeshBasicMaterial({ map: glyphTexture("$", meta.glow, "#06231b"), side: THREE.DoubleSide, toneMapped: false, transparent: true }));
    card.position.y = 2.45;
    body.add(card);
  }

  // marker ring on the ground + light pillar
  const ring = new THREE.Mesh(shared.ring(), additive(col, 0.7));
  ring.rotation.x = -Math.PI / 2;
  ring.position.y = 0.06;
  root.add(ring);
  const pillar = new THREE.Mesh(shared.pillar(), additive(col, 0.5, beaconTexture()));
  pillar.scale.set(1.6, 1, 1.6);
  root.add(pillar);

  const ice = new THREE.Mesh(shared.ice(), new THREE.MeshBasicMaterial({ color: 0xbfe9ff, transparent: true, opacity: 0.38, depthWrite: false }));
  ice.scale.set(0.8, 1.55, 0.8);
  ice.position.y = 0.95;
  ice.visible = false;
  root.add(ice);

  // invisible pick volume (the raycaster still tests it)
  const hit = new THREE.Mesh(new THREE.CylinderGeometry(0.9, 0.9, 2.5, 8), new THREE.MeshBasicMaterial());
  hit.visible = false;
  hit.position.y = 1.15;
  hit.userData.agentId = spec.id;
  root.add(hit);

  return { id: spec.id, team, root, body, ring, pillar, hit, glow, shards, card, ice, phase: Math.random() * 6, seed: Math.random() * 100, pillarH: 24, ringS: 1 };
}

export function disposeFigure(h: FigureHandle) {
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
  h.phase += dt * (1.6 + a.vel * 1.25);
  const sway = Math.sin(h.phase);
  const caught = a.status === "caught";
  const pitching = a.mode === "pitch";

  h.body.position.y = Math.abs(sway) * 0.13 * walk - (caught ? 0.1 : 0);
  h.body.position.x = pitching ? Math.sin(t * 11 + h.seed) * 0.03 : 0;
  h.body.rotation.x = caught ? -0.5 : 0.17 * walk + (pitching ? 0.12 : 0) + (a.mode === "dash" ? 0.18 : 0);
  h.body.rotation.z = sway * 0.07 * walk + (caught ? 0.22 : 0);
  const breathe = 1 + Math.sin(t * 1.7 + h.seed) * 0.012 * (1 - walk);
  h.body.scale.set(1, caught ? 0.84 : breathe, 1);

  if (h.shards) {
    h.shards.rotation.y += dt * (pitching ? 6 : 2.2);
    h.shards.children.forEach((s, i) => { s.position.y = 1.0 + i * 0.28 + Math.sin(t * 2.4 + i * 2) * 0.12; });
  }
  if (h.card) {
    h.card.rotation.y += dt * 1.4;
    h.card.position.y = 2.45 + Math.sin(t * 2 + h.seed) * 0.08;
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
