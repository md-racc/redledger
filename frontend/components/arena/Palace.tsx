"use client";
// The Palace of Fine Arts. Loads the baked glb export (meshopt + KTX2 + GPU instancing) of
// github.com/dkhh10/palace-of-fine-arts-3d: `palace-arch.glb` (rotunda + colonnades) and `palace-ground.glb`
// (terrain, lagoon bed, paving). If either fails to load, a procedural stand-in built from the same site data
// takes its place, so the experience never ends on a blank scene.
import { Component, Suspense, useCallback, useEffect, useMemo, useRef, type ReactNode } from "react";
import * as THREE from "three";
import { useLoader, useThree } from "@react-three/fiber";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { KTX2Loader } from "three/examples/jsm/loaders/KTX2Loader.js";
import { MeshoptDecoder } from "three/examples/jsm/libs/meshopt_decoder.module.js";
import { MODEL_URLS } from "@/lib/arena/config";
import { COLUMNS, LAGOON, WATER_Y } from "@/lib/arena/siteData";
import { useArena } from "@/lib/arena/store";
import { cutaway, HIDE_IN_ARENA } from "./cutaway";
import { closeColumnGaps } from "./palaceGaps";
import { GroundSampler } from "./ground";

let ktx2: KTX2Loader | null = null;

function useModel(url: string) {
  const gl = useThree((s) => s.gl);
  return useLoader(GLTFLoader, url, (loader) => {
    if (!ktx2) {
      ktx2 = new KTX2Loader().setTranscoderPath("/basis/").detectSupport(gl);
    }
    loader.setKTX2Loader(ktx2);
    loader.setMeshoptDecoder(MeshoptDecoder);
  });
}

function prep(root: THREE.Object3D, shadows: boolean, cut = false) {
  root.traverse((o) => {
    const m = o as THREE.Mesh;
    if (!m.isMesh) return;
    m.castShadow = shadows;
    m.receiveShadow = true;
    const mats = Array.isArray(m.material) ? m.material : [m.material];
    for (const mat of mats as THREE.MeshStandardMaterial[]) {
      if (!mat) continue;
      mat.envMapIntensity = 0.9;
      if (mat.map) mat.map.anisotropy = 8;
      mat.roughness = Math.max(mat.roughness ?? 0.9, 0.7);
      mat.metalness = 0;
      if (cut) {
        if (HIDE_IN_ARENA.test(mat.name) && !cutaway.fading.includes(mat)) cutaway.fading.push(mat);
        mat.clippingPlanes = [cutaway.plane];
        mat.side = THREE.DoubleSide; // sliced walls read as solid from inside
      }
    }
  });
}

function RealPalace({ onReady }: { onReady: (roots: THREE.Object3D[]) => void }) {
  const arch = useModel(MODEL_URLS.arch);
  const ground = useModel(MODEL_URLS.ground);
  useEffect(() => {
    closeColumnGaps(arch.scene);
    prep(arch.scene, true, true);
    prep(ground.scene, false);
    onReady([ground.scene, arch.scene]);
  }, [arch, ground, onReady]);
  return (
    <group name="palace">
      <primitive object={ground.scene} />
      <primitive object={arch.scene} />
    </group>
  );
}

/** Procedural Palace: rotunda, colonnade pergolas, lawn with the lagoon cut out. */
function StandInPalace({ onReady }: { onReady: (roots: THREE.Object3D[]) => void }) {
  const group = useRef<THREE.Group>(null!);
  const parts = useMemo(() => {
    const stone = new THREE.MeshStandardMaterial({ color: 0xc9a98a, roughness: 0.85, flatShading: false });
    const rose = new THREE.MeshStandardMaterial({ color: 0xc08a78, roughness: 0.8 });
    const dome = new THREE.MeshStandardMaterial({ color: 0x9fb4a4, roughness: 0.6, metalness: 0.15 });

    // lawn with the lagoon as a hole
    const shape = new THREE.Shape();
    shape.moveTo(-600, -600); shape.lineTo(600, -600); shape.lineTo(600, 600); shape.lineTo(-600, 600); shape.closePath();
    shape.holes.push(new THREE.Path(LAGOON.map(([x, z]) => new THREE.Vector2(x, -z))));
    const lawnGeo = new THREE.ShapeGeometry(shape);
    lawnGeo.rotateX(-Math.PI / 2); // (x, y) -> (x, 0, -y): lagoon z is restored
    const lawn = new THREE.Mesh(lawnGeo, new THREE.MeshStandardMaterial({ color: 0x55703f, roughness: 1 }));
    lawn.position.y = -0.25;
    lawn.receiveShadow = true;
    const bed = new THREE.Mesh(new THREE.PlaneGeometry(1200, 1200).rotateX(-Math.PI / 2), new THREE.MeshStandardMaterial({ color: 0x1b2a22, roughness: 1 }));
    bed.position.y = WATER_Y - 1.2;

    const g = new THREE.Group();
    g.add(lawn, bed);
    for (const m of [stone, dome]) m.clippingPlanes = [cutaway.plane];
    const podium = new THREE.Mesh(new THREE.CylinderGeometry(31, 33, 1.6, 48), stone);
    podium.position.y = -0.1; podium.receiveShadow = true; podium.castShadow = true;
    g.add(podium);
    const floor = new THREE.Mesh(new THREE.CircleGeometry(26, 48).rotateX(-Math.PI / 2), new THREE.MeshStandardMaterial({ color: 0xb09a82, roughness: 0.9 }));
    floor.position.y = 0.72; floor.receiveShadow = true;
    g.add(floor);

    // columns (instanced): rotunda ring, inner ring, colonnades
    const colGeo = new THREE.CylinderGeometry(0.6, 0.75, 1, 14);
    const cols = new THREE.InstancedMesh(colGeo, rose, COLUMNS.length);
    const m = new THREE.Matrix4();
    COLUMNS.forEach(([k, x, z], i) => {
      const h = k === "r" ? 16 : k === "i" ? 14 : 12;
      m.compose(new THREE.Vector3(x, 0.7 + h / 2, z), new THREE.Quaternion(), new THREE.Vector3(k === "c" ? 1 : 1.5, h, k === "c" ? 1 : 1.5));
      cols.setMatrixAt(i, m);
    });
    cols.castShadow = true; cols.receiveShadow = true;
    g.add(cols);

    // entablature ring + drum + dome
    const ent = new THREE.Mesh(new THREE.CylinderGeometry(25.2, 25.2, 3.2, 48, 1, true), stone);
    ent.position.y = 18.4; ent.castShadow = true;
    const entCap = new THREE.Mesh(new THREE.RingGeometry(0, 25.2, 48).rotateX(-Math.PI / 2), stone);
    entCap.position.y = 20;
    const drum = new THREE.Mesh(new THREE.CylinderGeometry(19.5, 21.5, 13, 32), stone);
    drum.position.y = 26.5; drum.castShadow = true;
    const cupola = new THREE.Mesh(new THREE.SphereGeometry(19.5, 40, 20, 0, Math.PI * 2, 0, Math.PI / 2), dome);
    cupola.position.y = 33; cupola.scale.y = 0.85; cupola.castShadow = true;
    g.add(ent, entCap, drum, cupola);

    // colonnade beams: link each column to its nearest neighbours
    const cc = COLUMNS.filter((c) => c[0] === "c");
    const beamGeo = new THREE.BoxGeometry(1, 0.9, 1);
    const pairs: [number, number, number, number][] = [];
    cc.forEach((a, i) => {
      for (let j = i + 1; j < cc.length; j++) {
        const d = Math.hypot(a[1] - cc[j][1], a[2] - cc[j][2]);
        if (d < 5.2) pairs.push([a[1], a[2], cc[j][1], cc[j][2]]);
      }
    });
    const beams = new THREE.InstancedMesh(beamGeo, stone, pairs.length);
    pairs.forEach(([ax, az, bx, bz], i) => {
      const len = Math.hypot(bx - ax, bz - az);
      m.compose(new THREE.Vector3((ax + bx) / 2, 12.9, (az + bz) / 2), new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), -Math.atan2(bz - az, bx - ax)), new THREE.Vector3(len, 1, 1.1));
      beams.setMatrixAt(i, m);
    });
    beams.castShadow = true;
    g.add(beams);
    return g;
  }, []);

  useEffect(() => {
    onReady([parts]);
  }, [parts, onReady]);

  return <primitive ref={group} object={parts} name="palace-standin" />;
}

class Boundary extends Component<{ children: ReactNode; fallback: ReactNode; onError: (e: unknown) => void }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(e: unknown) { this.props.onError(e); }
  render() { return this.state.failed ? this.props.fallback : this.props.children; }
}

export function Palace({ onGround }: { onGround: (g: GroundSampler | null) => void }) {
  const setModelState = useArena((s) => s.setModelState);

  const handle = useCallback(
    (roots: THREE.Object3D[], real: boolean) => {
      setModelState(real ? "real" : "fallback");
      const sampler = new GroundSampler();
      onGround(sampler);
      void sampler.build(roots);
    },
    [onGround, setModelState],
  );
  const readyReal = useCallback((roots: THREE.Object3D[]) => handle(roots, true), [handle]);
  const readyFake = useCallback((roots: THREE.Object3D[]) => handle(roots, false), [handle]);

  return (
    <Boundary fallback={<StandInPalace onReady={readyFake} />} onError={(e) => console.warn("[redledger] Palace glb failed to load, using the procedural stand-in:", e)}>
      <Suspense fallback={null}>
        <RealPalace onReady={readyReal} />
      </Suspense>
    </Boundary>
  );
}
