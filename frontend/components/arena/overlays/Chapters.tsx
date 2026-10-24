"use client";
// Scroll chapters: a caption per stop on the rail, plus a progress rail on the right edge.
import { useEffect, useRef } from "react";
import { useArena } from "@/lib/arena/store";
import { CHAPTERS, subscribeTimeline } from "@/lib/arena/timeline";

const WINDOW = 0.095;

export function Chapters() {
  const stage = useArena((s) => s.stage);
  const refs = useRef<(HTMLElement | null)[]>([]);
  const ticks = useRef<(HTMLElement | null)[]>([]);
  const root = useRef<HTMLDivElement>(null);

  useEffect(
    () =>
      subscribeTimeline((t) => {
        CHAPTERS.forEach((c, i) => {
          const el = refs.current[i];
          if (!el) return;
          let o = Math.max(0, 1 - Math.abs(t.scroll - c.at) / WINDOW);
          if (i === 0) o *= Math.min(1, t.scroll / 0.035) ; // the title owns the very top
          if (i === CHAPTERS.length - 1) o *= 1 - t.arena; // the HUD takes over once the orbit is live
          const e = o * o * (3 - 2 * o);
          el.style.opacity = e.toFixed(3);
          el.style.transform = `translate3d(0, ${((1 - e) * 22).toFixed(1)}px, 0)`;
          el.style.visibility = e < 0.01 ? "hidden" : "visible";
          const tick = ticks.current[i];
          if (tick) tick.dataset.on = Math.abs(t.scroll - c.at) < WINDOW * 0.75 ? "1" : "0";
        });
        root.current?.style.setProperty("--p", t.scroll.toFixed(3));
      }),
    [],
  );

  const on = stage === "scroll" || stage === "arena";
  return (
    <div ref={root} className={`chapters ${on ? "is-on" : ""}`} aria-hidden={!on}>
      {CHAPTERS.map((c, i) => (
        <article key={c.no} className="chapter" ref={(el) => { refs.current[i] = el; }}>
          <span className="chapter-no">{c.no}</span>
          <h2 className="chapter-title">{c.title}</h2>
          <p className="chapter-body">{c.body}</p>
        </article>
      ))}
      <nav className="rail" aria-label="Tour progress">
        <span className="rail-fill" />
        {CHAPTERS.map((c, i) => (
          <button
            key={c.no}
            ref={(el) => { ticks.current[i] = el; }}
            className="rail-tick"
            style={{ top: `${c.at * 100}%` }}
            aria-label={`Go to ${c.title}`}
            onClick={() => window.scrollTo({ top: c.at * (document.documentElement.scrollHeight - window.innerHeight), behavior: "smooth" })}
          >
            <span>{c.no}</span>
          </button>
        ))}
      </nav>
      <div className="scroll-hint" aria-hidden><i /><span>Scroll</span></div>
    </div>
  );
}
