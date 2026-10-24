"use client";
// The R3F canvas: atmosphere, Palace, arena, camera, picking, post.
import { useCallback, useEffect, useState } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { PerformanceMonitor } from "@react-three/drei";
import * as THREE from "three";
import { initialLevel, pinnedByUrl, QUALITY } from "@/lib/arena/quality";
import { useArena } from "@/lib/arena/store";
import type { ArenaSim } from "@/lib/arena/sim";
import type { RLEvent } from "@/lib/types";
import { ArenaWorld } from "./ArenaWorld";
import { Lights, SkyDome, Water } from "./Atmosphere";
import { CameraRig } from "./CameraRig";
import { Effects } from "./Effects";
import type { GroundSampler } from "./ground";
import { Palace } from "./Palace";
import { Picking } from "./Picking";

interface Props {
  subscribe: (fn: (e: RLEvent) => void) => () => void;
  feedActive: boolean;
  onSim: (sim: ArenaSim) => void;
  onProgress: (p: { progress: number; active: boolean }) => void;
}

/** Loading progress straight from three's manager (drei's useProgress sets state during render of the suspended glb). */
function ProgressBridge({ onProgress }: { onProgress: Props["onProgress"] }) {
  useEffect(() => {
    const m = THREE.DefaultLoadingManager;
    const prev = m.onProgress;
    m.onProgress = (url, loaded, total) => {
      prev?.(url, loaded, total);
      queueMicrotask(() => onProgress({ progress: total ? (loaded / total) * 100 : 0, active: loaded < total }));
    };
    return () => { m.onProgress = prev; };
  }, [onProgress]);
  return null;
}

/** Applies the quality level to the live renderer: shadow map size and cadence, and built-in tone mapping when the post chain is off. */
function QualityApplier({ level }: { level: 0 | 1 | 2 | 3 }) {
  const gl = useThree((s) => s.gl);
  const q = QUALITY[level];
  const frame = { n: 0 };
  useEffect(() => {
    gl.shadowMap.enabled = q.shadows;
    gl.shadowMap.autoUpdate = false;
    gl.shadowMap.needsUpdate = true;
    gl.toneMapping = q.post === "off" ? THREE.ACESFilmicToneMapping : THREE.NoToneMapping;
    gl.toneMappingExposure = 1;
  }, [gl, q]);
  useFrame(() => {
    // the sun is fixed: refresh the shadow map every few frames instead of every frame
    if (q.shadows && ++frame.n % q.shadowEvery === 0) gl.shadowMap.needsUpdate = true;
  });
  return null;
}

export default function Scene({ subscribe, feedActive, onSim, onProgress }: Props) {
  const [ground, setGround] = useState<GroundSampler | null>(null);
  const onGround = useCallback((g: GroundSampler | null) => setGround(g), []);
  const hover = useArena((s) => s.hoveredId);
  const [level, setLevel] = useState<0 | 1 | 2 | 3>(initialLevel);
  const q = QUALITY[level];
  const pinned = pinnedByUrl();

  return (
    <Canvas
      flat
      shadows={{ type: THREE.PCFShadowMap }}
      dpr={q.dpr}
      camera={{ fov: 54, near: 0.5, far: 4000, position: [-150, 26, -70] }}
      gl={{ antialias: false, powerPreference: "high-performance", stencil: false, localClippingEnabled: true }}
      style={{ touchAction: "pan-y" }}
      data-hover={hover ? "1" : "0"}
    >
      <color attach="background" args={["#d99a73"]} />
      <ProgressBridge onProgress={onProgress} />
      <QualityApplier level={level} />
      {!pinned && (
        <PerformanceMonitor
          ms={300}
          iterations={5}
          bounds={() => [20, 100]}
          flipflops={2}
          onDecline={() => setLevel((l) => (l > 0 ? ((l - 1) as 0 | 1 | 2 | 3) : l))}
        />
      )}
      <Lights shadowSize={q.shadowMap} />
      <SkyDome />
      <Water />
      <Palace onGround={onGround} />
      <ArenaWorld subscribe={subscribe} ground={ground} feedActive={feedActive} onSim={onSim} />
      <CameraRig />
      <Picking />
      <Effects mode={q.post} />
    </Canvas>
  );
}
