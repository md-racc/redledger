"use client";
// Golden-hour atmosphere: gradient sky dome, fog, sun + fill lights, and the lagoon water plane.
// The sun direction is the one baked into the Palace export (manifest `sun.direction_gltf`).
import { useMemo, useRef } from "react";
import * as THREE from "three";
import { useFrame } from "@react-three/fiber";
import { Environment, Lightformer } from "@react-three/drei";
import { SUN_TRAVEL } from "@/lib/arena/config";
import { WATER_Y } from "@/lib/arena/siteData";

export const SUN_DIR = new THREE.Vector3(-SUN_TRAVEL.x, -SUN_TRAVEL.y, -SUN_TRAVEL.z).normalize(); // toward the sun

const SKY_GLSL = /* glsl */ `
  vec3 skyColor(vec3 d, vec3 sunDir) {
    float h = d.y;
    vec3 zenith  = vec3(0.045, 0.075, 0.19);
    vec3 mid     = vec3(0.30, 0.31, 0.50);
    vec3 horizon = vec3(1.00, 0.56, 0.30);
    vec3 below   = vec3(0.16, 0.12, 0.13);
    vec3 c = mix(horizon, mid, smoothstep(0.0, 0.22, h));
    c = mix(c, zenith, smoothstep(0.18, 0.75, h));
    c = mix(c, below, smoothstep(0.0, -0.25, h));
    float s = max(dot(d, sunDir), 0.0);
    c += vec3(1.0, 0.62, 0.30) * pow(s, 6.0) * 0.55;
    c += vec3(1.0, 0.82, 0.55) * pow(s, 120.0) * 1.4;
    c += vec3(1.0, 0.95, 0.85) * pow(s, 2200.0) * 6.0;
    return c;
  }
`;

export function SkyDome() {
  const mat = useMemo(
    () =>
      new THREE.ShaderMaterial({
        side: THREE.BackSide,
        depthWrite: false,
        fog: false,
        uniforms: { sunDir: { value: SUN_DIR.clone() } },
        vertexShader: /* glsl */ `varying vec3 vDir; void main(){ vDir = normalize(position); gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }`,
        fragmentShader: /* glsl */ `varying vec3 vDir; uniform vec3 sunDir; ${SKY_GLSL}
          void main(){ gl_FragColor = vec4(skyColor(normalize(vDir), sunDir), 1.0); }`,
      }),
    [],
  );
  return (
    <mesh renderOrder={-10} frustumCulled={false} material={mat}>
      <sphereGeometry args={[1800, 32, 16]} />
    </mesh>
  );
}

export function Water() {
  const mat = useMemo(() => {
    const m = new THREE.ShaderMaterial({
      fog: true,
      transparent: false,
      uniforms: THREE.UniformsUtils.merge([
        THREE.UniformsLib.fog,
        { time: { value: 0 }, sunDir: { value: SUN_DIR.clone() }, deep: { value: new THREE.Color(0.012, 0.055, 0.06) } },
      ]),
      vertexShader: /* glsl */ `
        varying vec3 vWorld;
        #include <fog_pars_vertex>
        void main(){
          vec4 wp = modelMatrix * vec4(position, 1.0);
          vWorld = wp.xyz;
          vec4 mvPosition = viewMatrix * wp;
          gl_Position = projectionMatrix * mvPosition;
          #include <fog_vertex>
        }`,
      fragmentShader: /* glsl */ `
        varying vec3 vWorld;
        uniform float time; uniform vec3 sunDir; uniform vec3 deep;
        ${SKY_GLSL}
        #include <fog_pars_fragment>
        float wave(vec2 p, vec2 dir, float freq, float speed){ return sin(dot(p, dir) * freq + time * speed); }
        void main(){
          vec2 p = vWorld.xz;
          // layered travelling ripples -> a perturbed normal, flattened with distance so far water never moirés
          float dist = length(cameraPosition - vWorld);
          float near = 1.0 - smoothstep(60.0, 320.0, dist);
          vec2 g = vec2(0.0);
          g += vec2(0.8, 0.6) * wave(p, vec2(0.8, 0.6), 0.55, 0.9) * 0.030;
          g += vec2(-0.5, 0.86) * wave(p, vec2(-0.5, 0.86), 1.1, 1.3) * 0.024;
          g += vec2(0.2, -0.98) * wave(p, vec2(0.2, -0.98), 2.3, 1.9) * 0.014;
          g += vec2(0.95, 0.3) * wave(p, vec2(0.95, 0.3), 4.7, 2.4) * 0.008;
          g += vec2(sin(p.y * 0.23 + time * 0.5), cos(p.x * 0.19 - time * 0.4)) * 0.020;
          g *= near;
          vec3 n = normalize(vec3(-g.x, 1.0, -g.y));
          vec3 v = normalize(cameraPosition - vWorld);
          float cosT = clamp(dot(n, v), 0.0, 1.0);
          float fres = 0.02 + 0.98 * pow(1.0 - cosT, 5.0);
          vec3 r = reflect(-v, n);
          r.y = abs(r.y);
          vec3 refl = skyColor(normalize(r), sunDir);
          vec3 col = mix(deep, refl, clamp(fres * 1.25, 0.0, 1.0));
          col += vec3(1.0, 0.7, 0.4) * pow(max(dot(r, sunDir), 0.0), 700.0) * 6.0;
          gl_FragColor = vec4(col, 1.0);
          #include <fog_fragment>
        }`,
    });
    return m;
  }, []);
  useFrame((s) => { mat.uniforms.time.value = s.clock.elapsedTime; });
  return (
    <mesh rotation-x={-Math.PI / 2} position={[0, WATER_Y, 0]} material={mat} frustumCulled={false}>
      <planeGeometry args={[4000, 4000]} />
    </mesh>
  );
}

export function Lights({ shadowSize = 2048 }: { shadowSize?: number }) {
  const sun = useRef<THREE.DirectionalLight>(null!);
  const p = SUN_DIR.clone().multiplyScalar(240);
  return (
    <>
      <hemisphereLight args={[0xcdd2e4, 0x7d6a4c, 1.1]} />
      <directionalLight
        key={shadowSize}
        ref={sun}
        position={[p.x, p.y + 30, p.z]}
        color={0xffb86b}
        intensity={4.2}
        castShadow
        shadow-mapSize={[shadowSize, shadowSize]}
        shadow-bias={-0.0004}
        shadow-normalBias={0.4}
        shadow-camera-left={-140}
        shadow-camera-right={140}
        shadow-camera-top={140}
        shadow-camera-bottom={-140}
        shadow-camera-near={10}
        shadow-camera-far={620}
      />
      {/* low cool fill from the opposite side so shadow sides keep form */}
      <directionalLight position={[-p.x * 0.5, 60, -p.z * 0.5]} color={0x9aa8ff} intensity={0.3} />
      <Environment resolution={128} frames={1} background={false} environmentIntensity={0.75}>
        <Lightformer form="rect" intensity={4} color="#ffb070" position={[p.x * 0.3, 18, p.z * 0.3]} scale={[60, 20, 1]} target={[0, 0, 0]} />
        <Lightformer form="rect" intensity={1.2} color="#7f98ff" position={[0, 80, 0]} rotation-x={Math.PI / 2} scale={[120, 120, 1]} />
        <Lightformer form="ring" intensity={0.8} color="#ff6f7d" position={[-60, 20, 60]} scale={30} target={[0, 0, 0]} />
      </Environment>
      <fogExp2 attach="fog" args={[0xdda27a, 0.0021]} />
    </>
  );
}
