"use client";
// Cinematic camera: an auto-playing drone pass over the Palace (the intro), then a scroll-driven rail around the
// three perimeter groups, landing on the arena where the visitor takes over with an orbit.
//
//   intro   (time)    CatmullRom flight, ~12 s, scroll locked
//   scroll  (scrollY) CatmullRom rail, damped; mouse parallax on top
//   arena             OrbitControls; clicking an agent dollies in on it
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { useFrame, useThree } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import { useArena } from "@/lib/arena/store";
import { emitTimeline, INTRO_SECONDS, timeline } from "@/lib/arena/timeline";
import { figures } from "./figures";

type Key = [number, number, number, number, number, number]; // pos xyz, look xyz

/** The intro: skim the north colonnade, cross the lagoon, rise into the establishing shot. */
const INTRO: Key[] = [
  [-150, 26, -70, -70, 10, 8],
  [-105, 20, -88, -40, 12, 6],
  [-52, 20, -104, -4, 14, 4],
  [-6, 26, -118, 0, 18, 0],
  [30, 58, -142, 0, 10, 0],
];

/** The rail: establishing → south (guards) → behind the rotunda (clients) → north (fraudsters) → arena. */
const RAIL: Key[] = [
  [30, 58, -142, 0, 10, 0], // establishing
  [112, 26, -80, 78, 3, -30], // guards on the south shore
  [120, 44, 30, 40, 4, 38],
  [22, 28, 86, -20, 3, 42], // clients behind the rotunda
  [-70, 46, 88, -50, 3, 30],
  [-124, 26, -56, -86, 3, -12], // fraudsters at the north tip
  [-70, 80, -88, 0, 4, 2],
  [0, 72, -40, 0, 4, 2], // arena (steep enough to see over the rotunda's near piers)
];

const curveOf = (keys: Key[], off: number) =>
  new THREE.CatmullRomCurve3(keys.map((k) => new THREE.Vector3(k[off], k[off + 1], k[off + 2])), false, "centripetal", 0.5);

const smoother = (x: number) => x * x * x * (x * (x * 6 - 15) + 10);
const damp = (a: number, b: number, lambda: number, dt: number) => a + (b - a) * (1 - Math.exp(-lambda * dt));
const clamp01 = (x: number) => Math.min(1, Math.max(0, x));

export const ARENA_LOOK = new THREE.Vector3(0, 4, 2);

export function CameraRig() {
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera;
  const stage = useArena((s) => s.stage);
  const curves = useMemo(() => ({ ip: curveOf(INTRO, 0), il: curveOf(INTRO, 3), rp: curveOf(RAIL, 0), rl: curveOf(RAIL, 3) }), []);
  const v = useMemo(() => ({ pos: new THREE.Vector3(), look: new THREE.Vector3(), tp: new THREE.Vector3(), tl: new THREE.Vector3(), off: new THREE.Vector3(), right: new THREE.Vector3(), up: new THREE.Vector3(), want: new THREE.Vector3(), dir: new THREE.Vector3() }), []);
  const s = useRef({ scroll: 0, mx: 0, my: 0, ready: false, baseDist: 122, returning: false, lastFov: 0, shX: 0, shY: 0 });

  // place the camera on the first intro frame before anything is drawn
  useEffect(() => {
    curves.ip.getPoint(0, v.pos); curves.il.getPoint(0, v.look);
    camera.position.copy(v.pos); camera.lookAt(v.look);
    s.current.ready = true;
  }, [camera, curves, v]);

  // reduced motion: skip the flight
  useEffect(() => {
    if (typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) useArena.getState().setSkipIntro(true);
  }, []);

  useFrame((state, dtRaw) => {
    const dt = Math.min(dtRaw, 0.05);
    const st = useArena.getState();
    const S = s.current;
    if (!S.ready) return;

    let fov = 40;
    // portrait screens: widen the lens and dolly back so the three groups still fit side to side
    const aspect = state.size.width / Math.max(1, state.size.height);
    const narrow = clamp01((1.5 - aspect) / 1.0);
    const back = 1 + narrow * 0.9;
    if (st.stage === "loading" || st.stage === "intro") {
      if (st.stage === "intro") timeline.introTime += st.skipIntro ? 99 : dt;
      const p = clamp01(timeline.introTime / INTRO_SECONDS);
      timeline.intro = p;
      const u = smoother(p);
      curves.ip.getPoint(u, v.pos); curves.il.getPoint(u, v.look);
      fov = 54 - 14 * u;
      dolly(v, back);
      applyPose(camera, v, state.pointer, S, dt, 0.5);
      if (st.stage === "intro" && p >= 1) {
        S.scroll = 0;
        window.scrollTo(0, 0);
        st.setStage("scroll");
        v.tp.copy(v.pos); v.tl.copy(v.look);
      }
    } else {
      const max = Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
      const raw = clamp01(window.scrollY / max);
      S.scroll = damp(S.scroll, raw, 4.2, dt);
      timeline.scroll = S.scroll;
      curves.rp.getPoint(clamp01(S.scroll), v.want);
      curves.rl.getPoint(clamp01(S.scroll), v.dir);

      if (st.stage === "scroll") {
        // exponential approach to the rail point: smooth even when the wheel jumps
        v.tp.lerp(v.want, 1 - Math.exp(-dt * 7));
        v.tl.lerp(v.dir, 1 - Math.exp(-dt * 7));
        v.pos.copy(v.tp); v.look.copy(v.tl);
        dolly(v, back);
        applyPose(camera, v, state.pointer, S, dt, 1);
        if (S.scroll > 0.994 && raw > 0.99) {
          S.baseDist = camera.position.distanceTo(ARENA_LOOK);
          st.setStage("arena");
        }
      } else if (st.stage === "arena") {
        if (raw < 0.96) {
          v.tp.copy(camera.position);
          const c = state.controls as unknown as OrbitControlsImpl | null;
          if (c) v.tl.copy(c.target); else v.tl.copy(ARENA_LOOK);
          v.tp.sub(v.tl).multiplyScalar(1 / back).add(v.tl); // the rail stores the pose before the portrait dolly
          st.setStage("scroll");
        } else {
          orbitFocus(state.controls as unknown as OrbitControlsImpl | null, camera, st.selectedId, S, v, dt);
        }
      }
      fov = 40;
    }
    fov += narrow * 22;

    // keep the selected agent clear of the dossier: shift the projection centre left (desktop) or up (phone sheet)
    const open = st.stage === "arena" && !!st.selectedId;
    const phone = state.size.width <= 760;
    S.shX = damp(S.shX, open && !phone ? 0.2 : 0, 4, dt);
    S.shY = damp(S.shY, open && phone ? 0.22 : 0, 4, dt);
    if (Math.abs(S.shX) > 0.0005 || Math.abs(S.shY) > 0.0005) camera.setViewOffset(state.size.width, state.size.height, S.shX * state.size.width, S.shY * state.size.height, state.size.width, state.size.height);
    else if (camera.view?.enabled) camera.clearViewOffset();

    timeline.arena = damp(timeline.arena, st.stage === "arena" ? 1 : 0, 3, dt);
    if (Math.abs(S.lastFov - fov) > 0.01) { camera.fov = fov; camera.updateProjectionMatrix(); S.lastFov = fov; }
    emitTimeline();
  }, -2);

  return stage === "arena" ? <ArenaOrbit /> : null;
}

/** Pull the camera back along its view line: portrait screens see less sideways. */
function dolly(v: { pos: THREE.Vector3; look: THREE.Vector3 }, k: number) {
  if (k !== 1) v.pos.sub(v.look).multiplyScalar(k).add(v.look);
}

/** Mouse parallax on top of the rail pose; the offset is recomputed from the pose each frame so it never accumulates. */
function applyPose(camera: THREE.PerspectiveCamera, v: { pos: THREE.Vector3; look: THREE.Vector3; off: THREE.Vector3; right: THREE.Vector3; up: THREE.Vector3 }, pointer: THREE.Vector2, S: { mx: number; my: number }, dt: number, amount: number) {
  S.mx = damp(S.mx, pointer.x, 2.5, dt);
  S.my = damp(S.my, pointer.y, 2.5, dt);
  camera.position.copy(v.pos);
  camera.lookAt(v.look);
  camera.updateMatrix();
  v.right.setFromMatrixColumn(camera.matrix, 0);
  v.up.setFromMatrixColumn(camera.matrix, 1);
  v.off.copy(v.right).multiplyScalar(S.mx * 3.2 * amount).addScaledVector(v.up, S.my * 1.8 * amount);
  camera.position.add(v.off);
  camera.lookAt(v.look);
}

/** Set by the orbit controls: the visitor is dragging, or did a moment ago. */
const orbitState = { lastTouch: -1e9 };

/** Arena orbit: dolly in on the selected agent, ease back out when it is deselected; drifts slowly when left alone. */
function orbitFocus(c: OrbitControlsImpl | null, camera: THREE.PerspectiveCamera, selected: string | null, S: { baseDist: number; returning: boolean }, v: { want: THREE.Vector3; dir: THREE.Vector3 }, dt: number) {
  if (!c) return;
  const h = selected ? figures.get(selected) : null;
  const wantTarget = h ? v.want.copy(h.root.position).setY(h.root.position.y + 2.2) : ARENA_LOOK;
  const k = 1 - Math.exp(-dt * 3);
  c.target.lerp(wantTarget, k);
  if (!h && performance.now() - orbitState.lastTouch > 4500) {
    // slow cinematic drift around the target, independent of frame rate
    v.dir.copy(camera.position).sub(c.target);
    const a = dt * 0.025, cos = Math.cos(a), sin = Math.sin(a);
    const x = v.dir.x * cos - v.dir.z * sin, z = v.dir.x * sin + v.dir.z * cos;
    camera.position.set(c.target.x + x, camera.position.y, c.target.z + z);
  }
  if (h) S.returning = true;
  if (h || S.returning) {
    const wantDist = h ? 26 : S.baseDist;
    v.dir.copy(camera.position).sub(c.target);
    const len = v.dir.length();
    const next = len + (wantDist - len) * (1 - Math.exp(-dt * 2.2));
    if (!h && Math.abs(next - wantDist) < 0.5) S.returning = false;
    camera.position.copy(c.target).addScaledVector(v.dir.normalize(), next);
  }
}

function ArenaOrbit() {
  return (
    <OrbitControls
      makeDefault
      target={ARENA_LOOK.toArray()}
      enablePan={false}
      enableZoom={false}
      enableDamping
      dampingFactor={0.08}
      rotateSpeed={0.45}
      minPolarAngle={0.3}
      maxPolarAngle={1.25}
      onStart={() => { orbitState.lastTouch = performance.now() + 1e9; }}
      onEnd={() => { orbitState.lastTouch = performance.now(); }}
    />
  );
}
