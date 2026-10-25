"use client";
// The R3F canvas: atmosphere, Palace, arena, camera, picking, post.
import { useCallback, useEffect, useMemo, useState } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import * as THREE from "three";
import { QualityGovernor } from "@/lib/arena/governor";
import { initialLevel, pinnedByUrl, QUALITY } from "@/lib/arena/quality";
import { useArena } from "@/lib/arena/store";
import type { ArenaSim } from "@/lib/arena/sim";
import type { RLEvent } from "@/lib/types";
import { ArenaWorld } from "./ArenaWorld";
import { Backdrop } from "./Backdrop";
import type { DayTally } from "@/lib/arena/ledgerStats";
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
  /** per-day verdict / stolen tallies that grow the ledger ring */
  tallies: DayTally[];
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

/** Applies the quality level to the live renderer: shadow map cadence, and built-in tone mapping when the post chain is off.
 *  It never touches `gl.shadowMap.enabled` (the Canvas turns shadows on once): toggling it at runtime without recompiling every
 *  material binds the wrong texture to the shadow samplers and blacks out the scene (lib/arena/quality.ts). */
function QualityApplier({ level }: { level: 0 | 1 | 2 | 3 }) {
  const gl = useThree((s) => s.gl);
  const q = QUALITY[level];
  const frame = { n: 0 };
  useEffect(() => {
    gl.shadowMap.autoUpdate = false;
    gl.shadowMap.needsUpdate = true;
    gl.toneMapping = q.post === "off" ? THREE.ACESFilmicToneMapping : THREE.NoToneMapping;
    gl.toneMappingExposure = 1;
  }, [gl, q]);
  useFrame(() => {
    // the sun is fixed: refresh the shadow map every few frames instead of every frame
    if (++frame.n % q.shadowEvery === 0) gl.shadowMap.needsUpdate = true;
  });
  return null;
}

/** Steps the quality level from the frame rate (lib/arena/governor.ts): slow to step down, able to step back up. Idle while the
 *  scene is still loading or the page is hidden. */
function Governor({ start, onLevel }: { start: 0 | 1 | 2 | 3; onLevel: (l: 0 | 1 | 2 | 3) => void }) {
  const gov = useMemo(() => new QualityGovernor(start), [start]);
  useFrame((_, dt) => {
    if (document.hidden || useArena.getState().stage === "loading") return;
    const l = gov.frame(dt);
    if (l !== null) onLevel(l);
  });
  return null;
}

export default function Scene({ subscribe, feedActive, onSim, onProgress, tallies }: Props) {
  const [ground, setGround] = useState<GroundSampler | null>(null);
  const onGround = useCallback((g: GroundSampler | null) => setGround(g), []);
  const hover = useArena((s) => s.hoveredId);
  const [start] = useState<0 | 1 | 2 | 3>(initialLevel);
  const [level, setLevel] = useState<0 | 1 | 2 | 3>(start);
  useEffect(() => { document.documentElement.dataset.quality = String(level); }, [level]); // for debugging: which step the page is on
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
      {!pinned && <Governor start={start} onLevel={setLevel} />}
      {/* the map size stays at the starting level's: a new size remounts the sun mid-run, so a step down only slows the refresh */}
      <Lights shadowSize={QUALITY[start].shadowMap} />
      <SkyDome />
      <Water />
      <Palace onGround={onGround} />
      <ArenaWorld subscribe={subscribe} ground={ground} feedActive={feedActive} onSim={onSim} />
      <Backdrop ground={ground} tallies={tallies} detail={level} />
      <CameraRig />
      <Picking />
      <Effects mode={q.post} />
    </Canvas>
  );
}
