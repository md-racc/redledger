"use client";
// Everything that lives on the rotunda floor: the sim loop, the 30 agent figures, the ledger centrepiece and the
// effects (fraud beams, flowing coins, shockwaves, floating pops, hover tag, faction labels).
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { useFrame, useThree } from "@react-three/fiber";
import { CENTER, SLOT_RING } from "@/lib/arena/config";
import { DemoDriver, Director } from "@/lib/arena/director";
import { buildNavGrid, mulberry32 } from "@/lib/arena/nav";
import { cinema, HOLD_SECONDS } from "@/lib/arena/cinema";
import { addPop, agePops, anchors, pops } from "@/lib/arena/popBus";
import { ROSTER, TEAM_META, TEAMS } from "@/lib/arena/roster";
import { ArenaSim, GOOD_OUTCOMES, type FxTone } from "@/lib/arena/sim";
import { useArena } from "@/lib/arena/store";
import type { RLEvent } from "@/lib/types";
import { ledgerTexture, shared } from "./assets";
import { CLEAR_Y, CUT_Y, cutaway, setCutHeight, setFade } from "./cutaway";
import { animateFigure, buildFigure, disposeFigure, figures } from "./figures";
import type { GroundSampler } from "./ground";

const TONE: Record<FxTone, number> = { red: 0xff3b52, blue: 0x5aa0ff, green: 0x35e8a8, amber: 0xffc14d };

export interface WorldApi {
  sim: ArenaSim;
}

interface Props {
  subscribe: (fn: (e: RLEvent) => void) => () => void;
  ground: GroundSampler | null;
  /** true while a live/mock episode feed is driving the arena (the demo loop stands down) */
  feedActive: boolean;
  onSim: (sim: ArenaSim) => void;
}

export function ArenaWorld({ subscribe, ground, feedActive, onSim }: Props) {
  const grid = useMemo(() => buildNavGrid(), []);
  const sim = useMemo(() => new ArenaSim(ROSTER, grid, 11), [grid]);
  const director = useMemo(() => new Director(sim), [sim]);
  const demo = useMemo(() => new DemoDriver(sim, mulberry32(99)), [sim]);
  const figs = useMemo(() => ROSTER.map(buildFigure), []);
  const feedRef = useRef(feedActive);
  feedRef.current = feedActive;
  const groundRef = useRef(ground);
  groundRef.current = ground;
  const camera = useThree((s) => s.camera);
  const size = useThree((s) => s.size);

  useEffect(() => {
    figs.forEach((f) => figures.set(f.id, f));
    return () => figs.forEach((f) => { figures.delete(f.id); disposeFigure(f); });
  }, [figs]);

  useEffect(() => { onSim(sim); }, [sim, onSim]);
  useEffect(() => subscribe((e) => director.handle(e)), [subscribe, director]);

  useEffect(() => {
    useArena.getState().registerActions({ converge: () => sim.converge(), disperse: () => sim.disperse() });
  }, [sim]);

  // fx pools
  const rings = useMemo(() => {
    return Array.from({ length: 8 }, () => {
      const m = new THREE.Mesh(shared.unitRing(), new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false, toneMapped: false, side: THREE.DoubleSide }));
      m.rotation.x = -Math.PI / 2;
      m.visible = false;
      return { mesh: m, age: 9 };
    });
  }, []);
  const beams = useMemo(() => Array.from({ length: 6 }, () => {
    const m = new THREE.Mesh(shared.beam(), new THREE.MeshBasicMaterial({ color: 0xff3b52, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false, toneMapped: false }));
    m.visible = false;
    return m;
  }), []);
  const coins = useMemo(() => {
    const im = new THREE.InstancedMesh(shared.coin(), new THREE.MeshBasicMaterial({ color: 0xffd36e, toneMapped: false }), 24);
    im.frustumCulled = false;
    im.count = 0;
    return im;
  }, []);

  const tmp = useMemo(() => ({ m: new THREE.Matrix4(), v: new THREE.Vector3(), a: new THREE.Vector3(), b: new THREE.Vector3(), q: new THREE.Quaternion(), s: new THREE.Vector3(), up: new THREE.Vector3(0, 1, 0), lastPhase: "" }), []);
  const elapsed = useRef(0);
  const groupCenters = useMemo(() => {
    return TEAMS.map((team) => {
      const homes = ROSTER.filter((r) => r.team === team).map((r) => sim.agents.get(r.id)!.home);
      const x = homes.reduce((n, h) => n + h[0], 0) / homes.length;
      const z = homes.reduce((n, h) => n + h[1], 0) / homes.length;
      return { team, x, z };
    });
  }, [sim]);

  useFrame((_, dtRaw) => {
    const dt = Math.min(dtRaw, 0.1);
    elapsed.current += dt;
    const t = elapsed.current;
    sim.update(dt);
    if (!feedRef.current) demo.update(dt);

    const st = useArena.getState();
    const g = groundRef.current;
    // slice the dome away once the visitor is in the arena, put it back when they leave
    const wantCut = st.stage === "arena" ? CUT_Y : CLEAR_Y;
    const wantFade = st.stage === "arena" ? 0 : 1;
    if (Math.abs(cutaway.fade - wantFade) > 0.002) setFade(cutaway.fade + (wantFade - cutaway.fade) * (1 - Math.exp(-dt * 1.8)));
    if (Math.abs(cutaway.height - wantCut) > 0.05) setCutHeight(cutaway.height + (wantCut - cutaway.height) * (1 - Math.exp(-dt * (wantCut < cutaway.height ? 1.5 : 2.4))));
    const engaged = sim.phase === "engaged";
    for (const a of sim.agents.values()) {
      const h = figures.get(a.spec.id);
      if (!h) continue;
      const y = g ? g.heightAt(a.x, a.z) : 0;
      animateFigure(h, a, { y, dt, t, hovered: st.hoveredId === a.spec.id, selected: st.selectedId === a.spec.id, engaged });
    }
    // auto-cam: tell the camera what to frame (the live fraud scene and everyone in it)
    const live = sim.scenes.find((s) => s.stage === "approach" || s.stage === "pitch" || s.stage === "resolve");
    const sr = live && sim.agents.get(live.redId), sg = live && sim.agents.get(live.greenId);
    if (live && sr && sg) {
      const gd = live.stage === "resolve" && live.guardId ? sim.agents.get(live.guardId) : null;
      const pts = gd ? [sr, sg, gd] : [sr, sg];
      let span = 0;
      for (let i = 0; i < pts.length; i++) for (let j = i + 1; j < pts.length; j++) span = Math.max(span, Math.hypot(pts[i].x - pts[j].x, pts[i].z - pts[j].z));
      cinema.x = pts.reduce((n, p) => n + p.x, 0) / pts.length;
      cinema.z = pts.reduce((n, p) => n + p.z, 0) / pts.length;
      cinema.y = (g ? g.heightAt(cinema.x, cinema.z) : 0) + 2.5;
      cinema.dist = Math.min(46, Math.max(32, span * 2 + 22));
      cinema.active = true;
      cinema.hold = HOLD_SECONDS;
    } else if (cinema.active) {
      cinema.hold -= dt;
      if (cinema.hold <= 0) cinema.active = false;
    }
    if (tmp.lastPhase !== sim.phase) { tmp.lastPhase = sim.phase; st.setSimPhase(sim.phase); }

    // one-shot effects from the sim
    for (const fx of sim.drainFx()) {
      const y = (g ? g.heightAt(fx.x, fx.z) : 0);
      if (fx.kind === "ring") {
        const r = rings.find((r) => r.age > 1) ?? rings[0];
        r.age = 0;
        (r.mesh.material as THREE.MeshBasicMaterial).color.setHex(TONE[fx.tone]);
        r.mesh.position.set(fx.x, y + 0.2, fx.z);
        r.mesh.visible = true;
      } else {
        addPop({ x: fx.x, y: y + 6.6, z: fx.z, text: fx.text, tone: fx.tone });
      }
    }
    for (const r of rings) {
      if (!r.mesh.visible) continue;
      r.age += dt * 1.15;
      if (r.age > 1) { r.mesh.visible = false; continue; }
      r.mesh.scale.setScalar(1.5 + r.age * 11);
      (r.mesh.material as THREE.MeshBasicMaterial).opacity = (1 - r.age) * 0.85;
    }

    // project pops to the screen
    agePops(dt);
    for (const p of pops) {
      tmp.v.set(p.x, p.y, p.z).project(camera);
      p.onScreen = tmp.v.z < 1 && Math.abs(tmp.v.x) < 1.1 && Math.abs(tmp.v.y) < 1.1;
      p.sx = (tmp.v.x * 0.5 + 0.5) * size.width;
      p.sy = (-tmp.v.y * 0.5 + 0.5) * size.height;
    }

    // faction banners + hover tag
    for (const c of groupCenters) {
      const gy = (g ? g.heightAt(c.x, c.z) : 0) + 15;
      tmp.v.set(c.x, gy, c.z);
      const dist = tmp.v.distanceTo(camera.position);
      tmp.v.project(camera);
      const a = anchors[c.team];
      a.on = tmp.v.z < 1 && Math.abs(tmp.v.x) < 1.2 && Math.abs(tmp.v.y) < 1.2;
      a.sx = (tmp.v.x * 0.5 + 0.5) * size.width;
      a.sy = (-tmp.v.y * 0.5 + 0.5) * size.height;
      a.scale = Math.min(1.25, Math.max(0.5, 150 / dist));
    }
    const tagId = st.hoveredId ?? st.selectedId;
    const tagFig = tagId ? figures.get(tagId) : null;
    if (tagFig) {
      tmp.v.copy(tagFig.root.position).setY(tagFig.root.position.y + 7.2).project(camera);
      anchors.tag.on = tmp.v.z < 1;
      anchors.tag.sx = (tmp.v.x * 0.5 + 0.5) * size.width;
      anchors.tag.sy = (-tmp.v.y * 0.5 + 0.5) * size.height;
    } else anchors.tag.on = false;

    // fraud beams + coins
    let bi = 0, ci = 0;
    for (const sc of sim.scenes) {
      const rf = figures.get(sc.redId), gf = figures.get(sc.greenId);
      if (!rf || !gf) continue;
      if (sc.beam > 0.02 && sc.stage !== "queued" && bi < beams.length) {
        tmp.a.copy(rf.root.position); tmp.a.y += 3.1;
        tmp.b.copy(gf.root.position); tmp.b.y += 2.7;
        const len = tmp.a.distanceTo(tmp.b);
        const beam = beams[bi++];
        beam.visible = true;
        beam.position.copy(tmp.a).add(tmp.b).multiplyScalar(0.5);
        tmp.v.copy(tmp.b).sub(tmp.a).normalize();
        beam.quaternion.setFromUnitVectors(tmp.up, tmp.v);
        beam.scale.set(1 + Math.sin(t * 14) * 0.25, len, 1 + Math.sin(t * 14) * 0.25);
        (beam.material as THREE.MeshBasicMaterial).opacity = sc.beam * (0.45 + 0.25 * Math.sin(t * 9));
      }
      if (sc.stage === "resolve" && sc.outcome && GOOD_OUTCOMES.includes(sc.outcome) && sc.flow > 0 && sc.flow < 1) {
        for (let k = 0; k < 6 && ci < 24; k++, ci++) {
          const u = (sc.flow * 1.4 + k / 6) % 1;
          tmp.a.copy(gf.root.position); tmp.a.y += 2.5;
          tmp.b.copy(rf.root.position); tmp.b.y += 2.9;
          tmp.v.lerpVectors(tmp.a, tmp.b, u);
          tmp.v.y += Math.sin(u * Math.PI) * 1.6;
          tmp.q.setFromAxisAngle(tmp.up, t * 6 + k);
          tmp.s.setScalar(0.7 + 0.3 * Math.sin(t * 10 + k));
          tmp.m.compose(tmp.v, tmp.q, tmp.s);
          coins.setMatrixAt(ci, tmp.m);
        }
      }
    }
    for (let i = bi; i < beams.length; i++) beams[i].visible = false;
    coins.count = ci;
    coins.instanceMatrix.needsUpdate = true;
  }, -3);


  return (
    <group name="arena">
      {figs.map((f) => <primitive key={f.id} object={f.root} />)}
      {beams.map((b, i) => <primitive key={`b${i}`} object={b} />)}
      {rings.map((r, i) => <primitive key={`r${i}`} object={r.mesh} />)}
      <primitive object={coins} />
      <Ledger ground={ground} />
      <ScanPlane />
    </group>
  );
}

// ---- the ledger at the centre ---------------------------------------------------------------------------------------

function Ledger({ ground }: { ground: GroundSampler | null }) {
  const pages = useRef<THREE.Group>(null!);
  const root = useRef<THREE.Group>(null!);
  const glow = useRef<THREE.PointLight>(null!);
  const floorRings = useRef<THREE.Group>(null!);
  const tex = useMemo(() => ledgerTexture(), []);
  const pageMat = useMemo(() => new THREE.MeshStandardMaterial({ map: tex, emissiveMap: tex, emissive: new THREE.Color(0xffd9d0), emissiveIntensity: 0.55, roughness: 0.8, side: THREE.DoubleSide }), [tex]);
  const level = useRef(0);

  useFrame((s, dt) => {
    const phase = useArena.getState().simPhase;
    const target = phase === "idle" ? 0.35 : 1;
    level.current += (target - level.current) * Math.min(1, dt * 1.5);
    const y = ground ? ground.heightAt(CENTER.x, CENTER.z) : 0;
    root.current.position.set(CENTER.x, y, CENTER.z);
    const t = s.clock.elapsedTime;
    pages.current.rotation.y = t * 0.45;
    pages.current.position.y = 3.1 + Math.sin(t * 1.2) * 0.18;
    pageMat.emissiveIntensity = 0.3 + 0.5 * level.current;
    glow.current.intensity = 14 + 60 * level.current;
    floorRings.current.children.forEach((c, i) => {
      const m = (c as THREE.Mesh).material as THREE.MeshBasicMaterial;
      m.opacity = (0.1 + 0.16 * level.current) * (0.8 + 0.2 * Math.sin(t * 1.6 + i));
    });
  });

  return (
    <group ref={root}>
      <group ref={pages}>
        {Array.from({ length: 6 }, (_, i) => (
          <mesh key={i} material={pageMat} rotation={[0, (i / 6) * Math.PI * 0.55, 0]} position={[0, i * 0.07, 0]} castShadow>
            <boxGeometry args={[2.6, 0.05, 1.95]} />
          </mesh>
        ))}
      </group>
      <pointLight ref={glow} color="#ff4d5e" position={[0, 3.4, 0]} distance={40} decay={1.6} />
      <mesh position={[0, 0.07, 0]} rotation-x={-Math.PI / 2}>
        <ringGeometry args={[2.5, 2.8, 64]} />
        <meshBasicMaterial color="#ff4d5e" transparent opacity={0.55} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
      </mesh>
      <mesh position={[0, 0.06, 0]} rotation-x={-Math.PI / 2}>
        <circleGeometry args={[2.5, 64]} />
        <meshBasicMaterial color="#1b0509" transparent opacity={0.55} depthWrite={false} />
      </mesh>
      <group ref={floorRings}>
        {(["green", "blue", "red"] as const).map((team) => (
          <mesh key={team} position={[0, 0.09, 0]} rotation-x={-Math.PI / 2}>
            <ringGeometry args={[SLOT_RING[team] - 0.7, SLOT_RING[team] + 0.7, 96]} />
            <meshBasicMaterial color={TEAM_META[team].hex} transparent opacity={0.15} blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
          </mesh>
        ))}
      </group>
    </group>
  );
}

/** A faint glowing disc at the slicing height: the "scan" that opens the building. */
function ScanPlane() {
  const ring = useRef<THREE.Mesh>(null!);
  const disc = useRef<THREE.Mesh>(null!);
  useFrame((s) => {
    const open = cutaway.height < CLEAR_Y - 2;
    ring.current.visible = disc.current.visible = open;
    if (!open) return;
    // a ring that sweeps down with the cut plane, then vanishes once it lands
    const k = Math.sin(Math.PI * Math.min(1, Math.max(0, (CLEAR_Y - cutaway.height) / (CLEAR_Y - CUT_Y))));
    ring.current.position.y = disc.current.position.y = cutaway.height + 0.05;
    (ring.current.material as THREE.MeshBasicMaterial).opacity = k * (0.3 + 0.1 * Math.sin(s.clock.elapsedTime * 3));
    (disc.current.material as THREE.MeshBasicMaterial).opacity = k * 0.05;
  });
  return (
    <group>
      <mesh ref={ring} rotation-x={-Math.PI / 2}>
        <ringGeometry args={[27.5, 28.2, 96]} />
        <meshBasicMaterial color="#ff6a7a" transparent depthWrite={false} blending={THREE.AdditiveBlending} toneMapped={false} />
      </mesh>
      <mesh ref={disc} rotation-x={-Math.PI / 2}>
        <circleGeometry args={[27.8, 96]} />
        <meshBasicMaterial color="#ff6a7a" transparent depthWrite={false} blending={THREE.AdditiveBlending} toneMapped={false} />
      </mesh>
    </group>
  );
}
