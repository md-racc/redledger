// Height under the agents' feet: raycast the loaded Palace geometry once into a coarse grid, then sample it.
// Falls back to a flat floor at y = 0 (the rotunda floor) until the grid is built or when no model is loaded.
import * as THREE from "three";
import { MeshBVH, acceleratedRaycast } from "three-mesh-bvh";
import { NAV } from "@/lib/arena/config";

const CELL = 2;

export class GroundSampler {
  ready = false;
  private w = Math.ceil((NAV.maxX - NAV.minX) / CELL);
  private h = Math.ceil((NAV.maxZ - NAV.minZ) / CELL);
  private heights = new Float32Array(this.w * this.h).fill(NaN);
  private cancelled = false;

  /** Build the grid from the given roots, a few hundred rays per frame so the main thread never stalls. */
  build(roots: THREE.Object3D[]): Promise<void> {
    const meshes: THREE.Mesh[] = [];
    for (const r of roots) {
      r.updateWorldMatrix(true, true);
      r.traverse((o) => {
        const m = o as THREE.Mesh;
        // instanced meshes are columns, urns and statues: not floor
        if (m.isMesh && !(m as THREE.InstancedMesh).isInstancedMesh && m.geometry?.attributes?.position) meshes.push(m);
      });
    }
    for (const m of meshes) {
      if (!m.geometry.boundsTree) m.geometry.boundsTree = new MeshBVH(m.geometry);
      m.raycast = acceleratedRaycast;
    }
    const ray = new THREE.Raycaster();
    ray.firstHitOnly = true;
    const origin = new THREE.Vector3();
    const down = new THREE.Vector3(0, -1, 0);
    let i = 0;
    const total = this.w * this.h;

    return new Promise((resolve) => {
      const step = () => {
        if (this.cancelled) return resolve();
        const end = Math.min(total, i + 700);
        for (; i < end; i++) {
          const ix = i % this.w, iz = (i - ix) / this.w;
          origin.set(NAV.minX + (ix + 0.5) * CELL, 5, NAV.minZ + (iz + 0.5) * CELL);
          ray.set(origin, down);
          const hits = ray.intersectObjects(meshes, false);
          for (const h of hits) {
            if (h.face && h.face.normal.y > 0.35) { this.heights[i] = h.point.y; break; }
          }
        }
        if (i < total) requestAnimationFrame(step);
        else { this.ready = true; resolve(); }
      };
      step();
    });
  }

  cancel() { this.cancelled = true; }

  private at(ix: number, iz: number): number {
    if (ix < 0 || iz < 0 || ix >= this.w || iz >= this.h) return NaN;
    return this.heights[iz * this.w + ix];
  }

  heightAt(x: number, z: number): number {
    if (!this.ready) return 0;
    const fx = (x - NAV.minX) / CELL - 0.5, fz = (z - NAV.minZ) / CELL - 0.5;
    const ix = Math.floor(fx), iz = Math.floor(fz);
    const tx = fx - ix, tz = fz - iz;
    const v = [this.at(ix, iz), this.at(ix + 1, iz), this.at(ix, iz + 1), this.at(ix + 1, iz + 1)];
    const wgt = [(1 - tx) * (1 - tz), tx * (1 - tz), (1 - tx) * tz, tx * tz];
    let s = 0, ws = 0;
    for (let k = 0; k < 4; k++) if (!Number.isNaN(v[k])) { s += v[k] * wgt[k]; ws += wgt[k]; }
    return ws > 0 ? s / ws : 0;
  }
}
