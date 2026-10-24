"use client";
// What surrounds the rotunda, kept well back from the arena: the ledger crown of glowing bars that the gate's daily verdicts
// and the stolen dollars grow, floating motes, and a glowing skyline with searchlights.
// Everything is additive light or a distant silhouette, so it adds mood without hiding the arena.
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { useFrame } from "@react-three/fiber";
import { Sparkles } from "@react-three/drei";
import { heights, MAX_DAYS, type DayTally } from "@/lib/arena/ledgerStats";
import { nearColumn } from "@/lib/arena/nav";
import { TEAM_META } from "@/lib/arena/roster";
import { WATER_Y } from "@/lib/arena/siteData";
import { presence } from "./presence";
import type { GroundSampler } from "./ground";

// ───────────────────────────────────────────── ledger ring ────────────────────────────────────────────────────────

const RING_R = 60; // well back from the rotunda: the crown stands out beyond the apron, round the back and both flanks
const ARC_FROM = (-30 * Math.PI) / 180;
const ARC_SPAN = (240 * Math.PI) / 180; // -30 deg (south, front) round the rear to 210 deg (north, front)
const BARS = 72;
const WEDGES = MAX_DAYS;
const PER_WEDGE = BARS / WEDGES; // 6: two green (allowed), two blue (blocked), two red (stolen)

interface Bar { x: number; z: number; wedge: number; kind: 0 | 1 | 2; seed: number }

const BAR_COLORS = [new THREE.Color(TEAM_META.green.hex), new THREE.Color(TEAM_META.blue.hex), new THREE.Color(TEAM_META.red.hex)];

function makeBars(): Bar[] {
  const out: Bar[] = [];
  for (let i = 0; i < BARS; i++) {
    const a = ARC_FROM + ARC_SPAN * ((i + 0.5) / BARS);
    const x = Math.cos(a) * RING_R, z = Math.sin(a) * RING_R;
    if (nearColumn(x, z, 4.5)) continue; // keep clear of the colonnades
    const k = i % PER_WEDGE;
    out.push({ x, z, wedge: Math.floor(i / PER_WEDGE), kind: k < 2 ? 0 : k < 4 ? 1 : 2, seed: Math.sin(i * 12.9898) * 43758.5453 % 1 });
  }
  return out;
}

function LedgerRing({ ground, tallies }: { ground: GroundSampler | null; tallies: DayTally[] }) {
  const bars = useMemo(makeBars, []);
  const mesh = useRef<THREE.InstancedMesh>(null!);
  const cur = useMemo(() => new Float32Array(bars.length).fill(2), [bars.length]);
  const baseY = useRef<Float32Array | null>(null);
  const talliesRef = useRef(tallies);
  talliesRef.current = tallies;

  const geometry = useMemo(() => new THREE.BoxGeometry(1, 1, 1).translate(0, 0.5, 0), []);
  const material = useMemo(
    () =>
      new THREE.ShaderMaterial({
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
        side: THREE.DoubleSide,
        uniforms: { uTime: { value: 0 }, uOn: { value: 0 } },
        vertexShader: /* glsl */ `
          varying float vY; varying float vWY; varying vec3 vColor;
          void main() {
            vY = position.y;
            #ifdef USE_INSTANCING_COLOR
            vColor = instanceColor;
            #else
            vColor = vec3(1.0);
            #endif
            vec4 wp = modelMatrix * instanceMatrix * vec4(position, 1.0);
            vWY = wp.y;
            gl_Position = projectionMatrix * viewMatrix * wp;
          }`,
        fragmentShader: /* glsl */ `
          varying float vY; varying float vWY; varying vec3 vColor;
          uniform float uTime, uOn;
          void main() {
            float g = 1.0 - vY;
            float cap = smoothstep(0.93, 1.0, vY);
            float scan = 0.82 + 0.18 * sin(vWY * 2.4 - uTime * 3.2);
            float a = (0.1 + 0.5 * g * g + cap * 0.9) * scan * uOn;
            gl_FragColor = vec4(vColor * (1.0 + cap * 1.6), a);
          }`,
      }),
    [],
  );

  // colours: wedges with data are bright, the rest idle dimly
  useEffect(() => {
    const m = mesh.current;
    bars.forEach((b, i) => {
      const c = BAR_COLORS[b.kind].clone().multiplyScalar(b.wedge < tallies.length ? 1 : 0.42);
      m.setColorAt(i, c);
    });
    if (m.instanceColor) m.instanceColor.needsUpdate = true;
  }, [bars, tallies.length]);

  const dummy = useMemo(() => new THREE.Object3D(), []);
  useFrame((s, dt) => {
    const m = mesh.current;
    material.uniforms.uTime.value = s.clock.elapsedTime;
    material.uniforms.uOn.value = presence();
    m.visible = material.uniforms.uOn.value > 0.01;
    if (!m.visible) return;
    if (ground?.ready && !baseY.current) baseY.current = Float32Array.from(bars.map((b) => Math.max(ground.heightAt(b.x, b.z), WATER_Y) - 0.4));
    const t = s.clock.elapsedTime;
    const T = talliesRef.current;
    bars.forEach((b, i) => {
      const day = T[b.wedge];
      let target: number;
      if (day) {
        const base = b.kind === 0 ? heights.allow(day.allow) : b.kind === 1 ? heights.block(day.block) : heights.stolen(day.stolen);
        target = base * (0.8 + 0.2 * Math.sin(t * 1.3 + b.seed * 9) * 0.5 + 0.1 * b.seed);
      } else {
        target = 2 + 4.5 * (0.5 + 0.5 * Math.sin(t * 0.9 + i * 0.5)) + 2 * Math.abs(b.seed);
      }
      cur[i] += (target - cur[i]) * Math.min(1, dt * 2.2);
      dummy.position.set(b.x, baseY.current ? baseY.current[i] : 0, b.z);
      dummy.scale.set(2.4, Math.max(0.5, cur[i]), 2.4);
      dummy.updateMatrix();
      m.setMatrixAt(i, dummy.matrix);
    });
    m.instanceMatrix.needsUpdate = true;
  });

  return <instancedMesh ref={mesh} args={[geometry, material, bars.length]} frustumCulled={false} renderOrder={3} />;
}

// ───────────────────────────────────────────── skyline and searchlights ─────────────────────────────────────

const SKY_N = 280;

function skylineInstances() {
  const rnd = (() => { let a = 90210; return () => { a = (a + 0x6d2b79f5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; })();
  const m = new THREE.Matrix4(), q = new THREE.Quaternion(), p = new THREE.Vector3(), sc = new THREE.Vector3();
  const colors: number[] = [];
  const mats: THREE.Matrix4[] = [];
  for (let i = 0; i < SKY_N; i++) {
    const a = rnd() * Math.PI * 2;
    const r = 190 + rnd() * 100;
    const tall = rnd() < 0.09;
    const h = tall ? 50 + rnd() * 45 : 10 + rnd() * 34;
    const w = 8 + rnd() * 18, d = 8 + rnd() * 16;
    p.set(Math.cos(a) * r, -3, Math.sin(a) * r);
    q.setFromAxisAngle(new THREE.Vector3(0, 1, 0), -a + (rnd() - 0.5) * 0.6);
    sc.set(w, h + 3, d);
    m.compose(p, q, sc);
    mats.push(m.clone());
    const v = 0.07 + rnd() * 0.06;
    colors.push(v * 0.9, v, v * 1.35);
  }
  return { mats, colors };
}

function Skyline() {
  const mesh = useRef<THREE.InstancedMesh>(null!);
  const { mats, colors } = useMemo(skylineInstances, []);
  const geometry = useMemo(() => new THREE.BoxGeometry(1, 1, 1).translate(0, 0.5, 0), []);
  const material = useMemo(
    () =>
      new THREE.ShaderMaterial({
        fog: true,
        uniforms: THREE.UniformsUtils.merge([THREE.UniformsLib.fog, { uTime: { value: 0 }, uOn: { value: 0 } }]),
        vertexShader: /* glsl */ `
          varying vec3 vWorld; varying vec3 vN; varying vec3 vColor;
          #include <fog_pars_vertex>
          void main() {
            #ifdef USE_INSTANCING_COLOR
            vColor = instanceColor;
            #else
            vColor = vec3(0.1);
            #endif
            vec4 wp = modelMatrix * instanceMatrix * vec4(position, 1.0);
            vWorld = wp.xyz;
            vN = normalize(mat3(modelMatrix * instanceMatrix) * normal);
            vec4 mvPosition = viewMatrix * wp;
            gl_Position = projectionMatrix * mvPosition;
            #include <fog_vertex>
          }`,
        fragmentShader: /* glsl */ `
          varying vec3 vWorld; varying vec3 vN; varying vec3 vColor;
          uniform float uTime, uOn;
          #include <fog_pars_fragment>
          float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
          void main() {
            gl_FragColor = vec4(vColor * (0.7 + 0.5 * max(vN.x * 0.4 + vN.z * 0.5, 0.0)), 1.0);
            #include <fog_fragment>
            // lit windows on the side faces, added after the haze so they still read at a distance
            vec2 cellSize = vec2(3.4, 4.4);
            vec2 uv = vec2(vWorld.x * vN.z - vWorld.z * vN.x, vWorld.y) / cellSize;
            vec2 id = floor(uv), f = fract(uv);
            float win = step(0.2, f.x) * step(f.x, 0.8) * step(0.22, f.y) * step(f.y, 0.72);
            float h = hash(id + floor(vWorld.xz * 0.01));
            float lit = step(0.5, h) * (0.75 + 0.25 * sin(uTime * (0.4 + h) + h * 40.0));
            vec3 warm = mix(vec3(1.0, 0.72, 0.4), vec3(0.55, 0.8, 1.0), step(0.86, hash(id.yx)));
            float side = 1.0 - step(0.5, abs(vN.y));
            gl_FragColor.rgb += warm * win * lit * side * 1.7 * uOn;
          }`,
      }),
    [],
  );
  useEffect(() => {
    const m = mesh.current;
    mats.forEach((mm, i) => { m.setMatrixAt(i, mm); m.setColorAt(i, new THREE.Color(colors[i * 3], colors[i * 3 + 1], colors[i * 3 + 2])); });
    m.instanceMatrix.needsUpdate = true;
    if (m.instanceColor) m.instanceColor.needsUpdate = true;
  }, [mats, colors]);
  useFrame((s) => {
    material.uniforms.uTime.value = s.clock.elapsedTime;
    material.uniforms.uOn.value = 0.25 + 0.75 * presence();
  });
  return <instancedMesh ref={mesh} args={[geometry, material, SKY_N]} frustumCulled={false} />;
}

/** Four faint searchlights on posts out beyond the park, aimed away from the arena and sweeping the sky. */
function Searchlights() {
  const sweepers = useRef<THREE.Group[]>([]);
  const coneMat = useMemo(
    () =>
      new THREE.ShaderMaterial({
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
        side: THREE.DoubleSide,
        uniforms: { uOn: { value: 0 }, uColor: { value: new THREE.Color(0.55, 0.75, 1) } },
        vertexShader: /* glsl */ `varying float vT; void main(){ vT = position.y / 320.0; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
        fragmentShader: /* glsl */ `varying float vT; uniform float uOn; uniform vec3 uColor; void main(){ float a = pow(1.0 - clamp(vT, 0.0, 1.0), 1.8) * 0.11 * uOn; gl_FragColor = vec4(uColor, a); }`,
      }),
    [],
  );
  const coneGeo = useMemo(() => new THREE.ConeGeometry(17, 320, 24, 1, true).rotateX(Math.PI).translate(0, 160, 0), []);
  const posts = useMemo(() => [[-230, 90], [235, 120], [30, 270], [-120, -230]] as const, []);

  useFrame((s) => {
    coneMat.uniforms.uOn.value = presence();
    const t = s.clock.elapsedTime;
    sweepers.current.forEach((g, i) => {
      if (!g) return;
      // aimed away from the arena and swinging ±0.9 rad across the sky behind it
      const [px, pz] = posts[i];
      g.rotation.order = "YXZ";
      g.rotation.y = Math.atan2(px, pz) + 0.9 * Math.sin(t * (0.22 + i * 0.05) + i * 1.9);
      g.rotation.x = 0.85 + 0.2 * Math.sin(t * 0.37 + i * 2);
    });
  });

  return (
    <group>
      {posts.map(([x, z], i) => (
          <group key={i} position={[x, 0, z]}>
            <group ref={(g) => { if (g) sweepers.current[i] = g; }}>
              <mesh geometry={coneGeo} material={coneMat} frustumCulled={false} />
            </group>
          </group>
      ))}
    </group>
  );
}

// ───────────────────────────────────────────── the whole backdrop ──────────────────────────────────────────────────

export function Backdrop({ ground, tallies, detail }: { ground: GroundSampler | null; tallies: DayTally[]; detail: 0 | 1 | 2 | 3 }) {
  return (
    <group name="backdrop">
      {detail >= 2 && <LedgerRing ground={ground} tallies={tallies} />}
      {detail >= 2 && <Skyline />}
      {detail >= 3 && <Searchlights />}
      {detail >= 3 && (
        <>
          <Sparkles count={220} scale={[240, 55, 240]} position={[0, 28, 25]} size={7} speed={0.25} opacity={0.75} color="#ffbb77" noise={0.6} />
          <Sparkles count={34} scale={[22, 20, 22]} position={[-86, 11, -12]} size={6} speed={0.5} opacity={0.9} color={TEAM_META.red.glow} />
          <Sparkles count={34} scale={[22, 20, 22]} position={[78, 11, -30]} size={6} speed={0.5} opacity={0.9} color={TEAM_META.blue.glow} />
          <Sparkles count={34} scale={[18, 20, 18]} position={[-20, 11, 42]} size={6} speed={0.5} opacity={0.9} color={TEAM_META.green.glow} />
        </>
      )}
    </group>
  );
}

