// Shared textures and geometries for the arena (created lazily, client-side only).
import * as THREE from "three";

let _beacon: THREE.CanvasTexture | null = null;
/** Vertical alpha gradient for the light pillars: opaque at the base, gone at the top. */
export function beaconTexture(): THREE.CanvasTexture {
  if (_beacon) return _beacon;
  const c = document.createElement("canvas");
  c.width = 4; c.height = 128;
  const g = c.getContext("2d")!;
  const grad = g.createLinearGradient(0, 128, 0, 0);
  grad.addColorStop(0, "rgba(255,255,255,0.95)");
  grad.addColorStop(0.35, "rgba(255,255,255,0.35)");
  grad.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = grad; g.fillRect(0, 0, 4, 128);
  _beacon = new THREE.CanvasTexture(c);
  return _beacon;
}

let _ledger: THREE.CanvasTexture | null = null;
/** A ruled ledger page: cream paper, red margin and rules, a few entries. */
export function ledgerTexture(): THREE.CanvasTexture {
  if (_ledger) return _ledger;
  const W = 512, H = 384;
  const c = document.createElement("canvas");
  c.width = W; c.height = H;
  const g = c.getContext("2d")!;
  g.fillStyle = "#f3e9d2"; g.fillRect(0, 0, W, H);
  g.strokeStyle = "rgba(190,40,55,0.85)"; g.lineWidth = 2;
  for (let y = 56; y < H; y += 26) { g.beginPath(); g.moveTo(14, y); g.lineTo(W - 14, y); g.stroke(); }
  g.lineWidth = 3;
  for (const x of [70, 330, 420]) { g.beginPath(); g.moveTo(x, 14); g.lineTo(x, H - 14); g.stroke(); }
  g.fillStyle = "rgba(60,20,25,0.9)"; g.font = "bold 24px Georgia, serif";
  g.fillText("LEDGER", 90, 38);
  g.font = "18px Georgia, serif";
  const rows = ["0412", "0413", "0414", "0415", "0416", "0417", "0418", "0419", "0420", "0421", "0422", "0423"];
  rows.forEach((r, i) => { const y = 78 + i * 26; g.fillText(r, 18, y); g.fillText((1200 + ((i * 937) % 8800)).toFixed(2), 342, y); });
  _ledger = new THREE.CanvasTexture(c);
  _ledger.colorSpace = THREE.SRGBColorSpace;
  _ledger.anisotropy = 4;
  return _ledger;
}

const cardCache = new Map<string, THREE.CanvasTexture>();
/** Floating glyph card ($ over clients). */
export function glyphTexture(glyph: string, fg: string, bg: string): THREE.CanvasTexture {
  const key = glyph + fg + bg;
  const hit = cardCache.get(key);
  if (hit) return hit;
  const c = document.createElement("canvas");
  c.width = 128; c.height = 160;
  const g = c.getContext("2d")!;
  g.fillStyle = bg; g.beginPath(); g.roundRect(4, 4, 120, 152, 14); g.fill();
  g.strokeStyle = fg; g.lineWidth = 6; g.beginPath(); g.roundRect(4, 4, 120, 152, 14); g.stroke();
  g.fillStyle = fg; g.font = "bold 96px Georgia, serif"; g.textAlign = "center"; g.textBaseline = "middle";
  g.fillText(glyph, 64, 84);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  cardCache.set(key, t);
  return t;
}

const G: Record<string, THREE.BufferGeometry> = {};
const geo = <T extends THREE.BufferGeometry>(key: string, make: () => T): T => (G[key] ??= make()) as T;

export const shared = {
  redCloak: () => geo("redCloak", () => new THREE.LatheGeometry([[0, 0], [0.64, 0], [0.58, 0.22], [0.44, 0.8], [0.3, 1.25], [0.2, 1.5], [0, 1.56]].map(([x, y]) => new THREE.Vector2(x, y)), 7)),
  blueBody: () => geo("blueBody", () => new THREE.LatheGeometry([[0, 0], [0.52, 0], [0.52, 0.2], [0.47, 0.9], [0.54, 1.2], [0.42, 1.42], [0, 1.46]].map(([x, y]) => new THREE.Vector2(x, y)), 8)),
  head: () => geo("head", () => new THREE.IcosahedronGeometry(0.21, 1)),
  hood: () => geo("hood", () => new THREE.ConeGeometry(0.27, 0.55, 6)),
  helmet: () => geo("helmet", () => new THREE.SphereGeometry(0.25, 12, 8, 0, Math.PI * 2, 0, Math.PI * 0.62)),
  pauldron: () => geo("pauldron", () => new THREE.SphereGeometry(0.2, 10, 8)),
  shield: () => geo("shield", () => new THREE.CylinderGeometry(0.42, 0.42, 0.07, 6)),
  spear: () => geo("spear", () => new THREE.CylinderGeometry(0.022, 0.022, 2.1, 6)),
  spearTip: () => geo("spearTip", () => new THREE.ConeGeometry(0.07, 0.28, 6)),
  capsule: () => geo("capsule", () => new THREE.CapsuleGeometry(0.31, 0.72, 4, 12)),
  sphereHead: () => geo("sphereHead", () => new THREE.SphereGeometry(0.23, 14, 10)),
  case: () => geo("case", () => new THREE.BoxGeometry(0.36, 0.27, 0.1)),
  card: () => geo("card", () => new THREE.PlaneGeometry(0.62, 0.78)),
  shard: () => geo("shard", () => new THREE.OctahedronGeometry(0.075)),
  visor: () => geo("visor", () => new THREE.BoxGeometry(0.3, 0.06, 0.05)),
  ring: () => geo("ring", () => new THREE.RingGeometry(0.78, 0.94, 48)),
  ringSoft: () => geo("ringSoft", () => new THREE.RingGeometry(0.55, 0.95, 48)),
  pillar: () => geo("pillar", () => new THREE.CylinderGeometry(0.05, 0.05, 1, 6, 1, true)),
  hit: () => geo("hit", () => new THREE.CylinderGeometry(1.35, 1.35, 4.4, 8)),
  ice: () => geo("ice", () => new THREE.IcosahedronGeometry(0.95, 0)),
  coin: () => geo("coin", () => new THREE.OctahedronGeometry(0.16)),
  beam: () => geo("beam", () => new THREE.CylinderGeometry(0.05, 0.05, 1, 6, 1, true)),
  unitRing: () => geo("unitRing", () => new THREE.RingGeometry(0.92, 1, 64)),
};
