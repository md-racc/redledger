// The baked Palace model's columns stop short of what they should carry. The colonnades' shafts are 11.2 m tall and end at 11.6 m;
// the roof beams above them start at 13.4 m, so a 1.8 m gap of daylight shows between the capital and the beam (the rotunda's inner
// pier ring has the same 1.8 m). This stretches each short shaft up to the beam above it and lifts its cap plate to match; the
// taller corner columns (which already reach into the beam) are left alone. Pure geometry on the loaded scene, safe to run twice.
// Owner: Dev R.
import * as THREE from "three";

/** metres of shaft pushed into the beam, so there is no seam */
const OVERLAP = 0.1;
/** a gap smaller than this is a seam, not a gap; larger than MAX_GAP is a different structure, not a short column */
const MIN_GAP = 0.3;
const MAX_GAP = 4;
/** a cap plate sits within this of the top of its shaft */
const SAME_TOP = 0.03;

export interface GapReport {
  /** shaft instances stretched */
  shafts: number;
  /** cap plates lifted */
  caps: number;
}

const isInstanced = (m: THREE.Object3D): m is THREE.InstancedMesh => (m as THREE.InstancedMesh).isInstancedMesh === true;
const materialName = (m: THREE.Mesh) => (Array.isArray(m.material) ? m.material[0] : m.material)?.name ?? "";
/** `colonnade_north__MAT_concrete_colonnade__merged` (the beams) belongs to the family of `…_colonnade` (the shafts) */
const family = (name: string) => name.replace(/__merged$/, "");

function bounds(m: THREE.Mesh): THREE.Box3 {
  m.geometry.computeBoundingBox();
  return m.geometry.boundingBox as THREE.Box3;
}

export function closeColumnGaps(root: THREE.Object3D): GapReport {
  const meshes: THREE.Mesh[] = [];
  root.traverse((o) => { if ((o as THREE.Mesh).isMesh) meshes.push(o as THREE.Mesh); });

  // the beams: plain meshes that start high above the ground, by material family; the lowest underside wins
  const beams = new Map<string, number>();
  for (const m of meshes) {
    if (isInstanced(m)) continue;
    const b = bounds(m);
    if (b.min.y <= 5) continue;
    const fam = family(materialName(m));
    beams.set(fam, Math.min(beams.get(fam) ?? Infinity, b.min.y));
  }

  // the shafts: tall instanced meshes (from the ground up) of a family that has a beam; stretch the ones that stop short of it
  const lifted = new Map<string, Map<number, number>>(); // family → old top → new top
  const report: GapReport = { shafts: 0, caps: 0 };
  const m4 = new THREE.Matrix4();
  for (const m of meshes) {
    if (!isInstanced(m)) continue;
    const fam = family(materialName(m));
    const beam = beams.get(fam);
    if (beam === undefined) continue;
    const b = bounds(m);
    const height = b.max.y - b.min.y;
    if (height < 5 || Math.abs(b.min.y) > 0.05) continue;
    const tops = lifted.get(fam) ?? new Map<number, number>();
    for (let i = 0; i < m.count; i++) {
      m.getMatrixAt(i, m4);
      const e = m4.elements;
      const sy = Math.hypot(e[4], e[5], e[6]);
      const top = e[13] + b.max.y * sy;
      const gap = beam - top;
      if (gap < MIN_GAP || gap > MAX_GAP) continue;
      const to = beam + OVERLAP;
      const k = (to - e[13]) / (b.max.y * sy);
      e[4] *= k; e[5] *= k; e[6] *= k;
      m.setMatrixAt(i, m4);
      tops.set(Math.round(top * 100) / 100, to);
      report.shafts++;
    }
    if (tops.size) lifted.set(fam, tops);
    m.instanceMatrix.needsUpdate = true;
    m.computeBoundingSphere();
  }

  // the cap plates: thin instanced meshes at the old tops move up to the new ones
  for (const m of meshes) {
    if (!isInstanced(m)) continue;
    const tops = lifted.get(family(materialName(m)));
    if (!tops) continue;
    const b = bounds(m);
    if (b.max.y - b.min.y > 0.5 || b.min.y >= 0) continue;
    for (let i = 0; i < m.count; i++) {
      m.getMatrixAt(i, m4);
      const e = m4.elements;
      for (const [from, to] of tops) {
        if (Math.abs(e[13] - from) > SAME_TOP) continue;
        e[13] += to - from;
        m.setMatrixAt(i, m4);
        report.caps++;
        break;
      }
    }
    m.instanceMatrix.needsUpdate = true;
    m.computeBoundingSphere();
  }
  return report;
}
