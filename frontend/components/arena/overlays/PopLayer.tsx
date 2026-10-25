"use client";
// DOM half of the floating pops: the 3D loop writes screen positions into popBus, this layer paints them.
import { useEffect, useRef } from "react";
import { POP_LIFE, pops } from "@/lib/arena/popBus";
import { type Stage, useArena } from "@/lib/arena/store";
import { timeline } from "@/lib/arena/timeline";

const SLOTS = 8;

/** Pops stay hidden while the "redledger" title is up (loading, the intro flight, and the first slice of scroll it exits
 *  over): a run started from the title would otherwise stack its labels over the lettering. */
export const popsVisible = (stage: Stage, scroll: number) => stage === "arena" || (stage === "scroll" && scroll >= 0.1);

export function PopLayer() {
  const els = useRef<(HTMLDivElement | null)[]>([]);
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      raf = requestAnimationFrame(tick);
      const shown = popsVisible(useArena.getState().stage, timeline.scroll);
      for (let i = 0; i < SLOTS; i++) {
        const el = els.current[i];
        if (!el) continue;
        const p = pops[i];
        if (!p || !p.onScreen || !shown) { el.style.opacity = "0"; continue; }
        const k = p.age / POP_LIFE;
        const a = k < 0.12 ? k / 0.12 : k > 0.7 ? (1 - k) / 0.3 : 1;
        if (el.dataset.id !== String(p.id)) { el.dataset.id = String(p.id); el.textContent = p.text; el.dataset.tone = p.tone; }
        el.style.opacity = a.toFixed(2);
        el.style.transform = `translate3d(${p.sx}px, ${p.sy - k * 46}px, 0) translate(-50%, -100%) scale(${0.9 + 0.1 * Math.min(1, k * 6)})`;
      }
    };
    tick();
    return () => cancelAnimationFrame(raf);
  }, []);
  return (
    <div className="pops" aria-hidden>
      {Array.from({ length: SLOTS }, (_, i) => <div key={i} className="pop" ref={(el) => { els.current[i] = el; }} />)}
    </div>
  );
}
