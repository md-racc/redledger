// The colonnade's columns reach the beams above them. A scene shaped like the baked Palace's: 11.2 m shafts topped at 11.6 m under beams that
// start at 13.4 m, taller corner shafts that already reach the beam, and one cap plate per shaft.
import * as THREE from "three";
import { describe, expect, it } from "vitest";
import { closeColumnGaps } from "./palaceGaps";

const named = (name: string) => new THREE.MeshBasicMaterial({ name });

function colonnade() {
  const scene = new THREE.Group();
  const fam = "colonnade_north__MAT_concrete_colonnade";
  const beam = new THREE.Mesh(new THREE.BoxGeometry(20, 8.4, 4).translate(0, 17.6, 0), named(`${fam}__merged`)); // y 13.4 .. 21.8
  const set = (mesh: THREE.InstancedMesh, ys: number[]) => ys.forEach((y, i) => mesh.setMatrixAt(i, new THREE.Matrix4().makeTranslation(i * 3, y, 0)));
  const short = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.9, 0.9, 11.2).translate(0, 5.6, 0), named(fam), 3);
  const tall = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.9, 0.9, 13.6).translate(0, 6.8, 0), named(fam), 2);
  const caps = new THREE.InstancedMesh(new THREE.BoxGeometry(1.8, 0.17, 1.8).translate(0, -0.075, 0), named(fam), 5);
  set(short, [0.4, 0.4, 0.4]);
  set(tall, [0.4, 0.4]);
  set(caps, [11.6, 11.6, 11.6, 14, 14]); // the cap of each shaft sits at its top
  scene.add(beam, short, tall, caps);
  return { scene, short, tall, caps };
}

const topOf = (m: THREE.InstancedMesh, i: number, height: number) => {
  const mat = new THREE.Matrix4();
  m.getMatrixAt(i, mat);
  return new THREE.Vector3(0, height, 0).applyMatrix4(mat).y;
};
const yOf = (m: THREE.InstancedMesh, i: number) => {
  const mat = new THREE.Matrix4();
  m.getMatrixAt(i, mat);
  return mat.elements[13]!;
};

describe("closeColumnGaps", () => {
  it("stretches the short shafts up into the beam and lifts their caps", () => {
    const { scene, short, caps } = colonnade();
    const r = closeColumnGaps(scene);
    expect(r).toEqual({ shafts: 3, caps: 3 });
    for (let i = 0; i < 3; i++) expect(topOf(short, i, 11.2)).toBeCloseTo(13.5, 5); // 13.4 + 0.1 into the beam
    for (let i = 0; i < 3; i++) expect(yOf(caps, i)).toBeCloseTo(13.5, 5);
    // a shaft keeps its footing and its width
    expect(yOf(short, 0)).toBeCloseTo(0.4, 5);
    const m = new THREE.Matrix4();
    short.getMatrixAt(0, m);
    expect(m.elements[0]).toBeCloseTo(1, 5);
  });

  it("leaves the tall corner columns and their caps alone", () => {
    const { scene, tall, caps } = colonnade();
    closeColumnGaps(scene);
    for (let i = 0; i < 2; i++) expect(topOf(tall, i, 13.6)).toBeCloseTo(14.0, 5);
    expect(yOf(caps, 3)).toBeCloseTo(14, 5);
    expect(yOf(caps, 4)).toBeCloseTo(14, 5);
  });

  it("is safe to run twice", () => {
    const { scene, short } = colonnade();
    closeColumnGaps(scene);
    expect(closeColumnGaps(scene)).toEqual({ shafts: 0, caps: 0 });
    expect(topOf(short, 0, 11.2)).toBeCloseTo(13.5, 5);
  });

  it("does nothing to columns that have no beam above them", () => {
    const scene = new THREE.Group();
    const shaft = new THREE.InstancedMesh(new THREE.CylinderGeometry(1, 1, 14).translate(0, 7, 0), named("rotunda__MAT_column_rose"), 2);
    shaft.setMatrixAt(0, new THREE.Matrix4().makeTranslation(0, 8.5, 0));
    shaft.setMatrixAt(1, new THREE.Matrix4().makeTranslation(4, 8.5, 0));
    scene.add(shaft);
    expect(closeColumnGaps(scene)).toEqual({ shafts: 0, caps: 0 });
    expect(topOf(shaft, 0, 14)).toBeCloseTo(22.5, 5);
  });

  it("ignores a gap that is a different structure, not a short column", () => {
    const { scene, short, caps } = colonnade();
    const beam = scene.children[0] as THREE.Mesh;
    beam.geometry = new THREE.BoxGeometry(20, 4, 4).translate(0, 22, 0); // starts at 20 m: 8.4 m above the shafts
    expect(closeColumnGaps(scene)).toEqual({ shafts: 0, caps: 0 });
    expect(topOf(short, 0, 11.2)).toBeCloseTo(11.6, 5);
    expect(yOf(caps, 0)).toBeCloseTo(11.6, 5);
  });
});
