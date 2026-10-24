"use client";
// Pointer picking with an explicit THREE.Raycaster against each agent's pick volume. Hover sets the cursor and the
// highlight, a click (no drag) selects the agent and opens the modal. At aerial distances the figures are a few
// pixels wide, so a miss falls back to the nearest agent head within a small screen-space radius.
import { useEffect } from "react";
import * as THREE from "three";
import { useThree } from "@react-three/fiber";
import { bridge } from "@/lib/arena/bridge";
import { useArena } from "@/lib/arena/store";
import { figures } from "./figures";

const ASSIST_PX = 30;
const CLICK_PX = 6;

export function Picking() {
  const gl = useThree((s) => s.gl);
  const camera = useThree((s) => s.camera);
  const scene = useThree((s) => s.scene);

  useEffect(() => {
    const el = gl.domElement;
    const ray = new THREE.Raycaster();
    const ndc = new THREE.Vector2();
    const head = new THREE.Vector3();
    let down: { x: number; y: number; t: number } | null = null;
    let raf = 0;
    let last: PointerEvent | null = null;

    const pick = (cx: number, cy: number): string | null => {
      const r = el.getBoundingClientRect();
      ndc.set(((cx - r.left) / r.width) * 2 - 1, -((cy - r.top) / r.height) * 2 + 1);
      ray.setFromCamera(ndc, camera);
      const hits = ray.intersectObjects([...figures.values()].map((f) => f.hit), false);
      if (hits.length) return hits[0].object.userData.agentId as string;
      let best: string | null = null;
      let bd = ASSIST_PX;
      for (const f of figures.values()) {
        head.copy(f.root.position);
        head.y += 2.6;
        head.project(camera);
        if (head.z > 1) continue;
        const sx = (head.x * 0.5 + 0.5) * r.width + r.left;
        const sy = (-head.y * 0.5 + 0.5) * r.height + r.top;
        const d = Math.hypot(sx - cx, sy - cy);
        if (d < bd) { bd = d; best = f.id; }
      }
      return best;
    };

    const live = () => {
      const s = useArena.getState().stage;
      return s === "scroll" || s === "arena";
    };

    const onMove = (e: PointerEvent) => {
      last = e;
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        const ev = last;
        if (!ev) return;
        const st = useArena.getState();
        if (!live() || ev.buttons) { if (st.hoveredId) st.setHovered(null); return; }
        const id = pick(ev.clientX, ev.clientY);
        st.setHovered(id);
        el.style.cursor = id ? "pointer" : st.stage === "arena" ? "grab" : "default";
      });
    };
    const onDown = (e: PointerEvent) => { down = { x: e.clientX, y: e.clientY, t: performance.now() }; };
    const onUp = (e: PointerEvent) => {
      const d = down;
      down = null;
      if (!d || !live()) return;
      if (Math.hypot(e.clientX - d.x, e.clientY - d.y) > CLICK_PX || performance.now() - d.t > 700) return;
      const st = useArena.getState();
      const id = pick(e.clientX, e.clientY);
      if (id) st.select(id);
      else if (st.selectedId) st.select(null);
    };
    const onLeave = () => useArena.getState().setHovered(null);

    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerdown", onDown);
    el.addEventListener("pointerup", onUp);
    el.addEventListener("pointerleave", onLeave);

    // where is an agent on screen? (modal connector line, tests)
    const proj = new THREE.Vector3();
    bridge.project = (id: string) => {
      const f = figures.get(id);
      if (!f) return null;
      const r = el.getBoundingClientRect();
      proj.copy(f.root.position);
      proj.y += 3.2;
      proj.project(camera);
      return { x: (proj.x * 0.5 + 0.5) * r.width + r.left, y: (-proj.y * 0.5 + 0.5) * r.height + r.top, z: proj.z };
    };
    const w = window as unknown as { __arena?: unknown };
    w.__arena = { gl, scene, camera, project: (id: string) => bridge.project(id), ids: () => [...figures.keys()], pos: (id: string) => figures.get(id)?.root.position.toArray() };

    return () => {
      cancelAnimationFrame(raf);
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerdown", onDown);
      el.removeEventListener("pointerup", onUp);
      el.removeEventListener("pointerleave", onLeave);
      delete w.__arena;
      bridge.project = () => null;
    };
  }, [gl, camera, scene]);

  return null;
}
