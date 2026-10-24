// Cutaway of the rotunda: once the visitor lands in the arena the dome, drum and attic are sliced away at one height,
// so the floor (and everyone on it) is visible from the orbit camera. A clipping plane on the Palace materials only.
import * as THREE from "three";

/** y above which the Palace is clipped. The rotunda's outer columns end around 23.5 m; slicing them at 11 m leaves the piers
 *  as stumps that still read as architecture, but they no longer stand in front of the agents on the floor. */
export const CUT_Y = 11;
export const CLEAR_Y = 140;

/** Palace materials that fade out in the arena: the dome shell, the coffered ceiling and the inner pier ring, so nothing
 *  stands between the orbit camera and the rotunda floor. Matched by the glb's material names. */
export const HIDE_IN_ARENA = /(dome_membrane|plaster_ceiling|concrete_inner|column_tan_inner|drum_band)/;

export const cutaway = {
  plane: new THREE.Plane(new THREE.Vector3(0, -1, 0), CLEAR_Y),
  height: CLEAR_Y,
  /** 1 = building intact, 0 = interior stripped */
  fade: 1,
  fading: [] as THREE.Material[],
};

export function setFade(f: number) {
  cutaway.fade = f;
  const solid = f > 0.995;
  for (const m of cutaway.fading) {
    const mat = m as THREE.MeshStandardMaterial;
    if (mat.transparent === solid) { mat.transparent = !solid; mat.depthWrite = solid || f > 0.5; mat.needsUpdate = true; }
    mat.opacity = f;
    mat.visible = f > 0.01;
  }
}

export function setCutHeight(y: number) {
  cutaway.height = y;
  cutaway.plane.constant = y;
}
