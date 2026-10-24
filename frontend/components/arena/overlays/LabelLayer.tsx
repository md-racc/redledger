"use client";
// Persistent in-scene labels, painted in the DOM from screen anchors the 3D loop writes every frame:
// the three faction banners over the spawn groups and the hover / selection tag.
import { useEffect, useRef } from "react";
import { anchors } from "@/lib/arena/popBus";
import { ROSTER_BY_ID, TEAM_META, TEAMS, rosterOf } from "@/lib/arena/roster";
import { useArena } from "@/lib/arena/store";
import { timeline } from "@/lib/arena/timeline";

/** each faction banner shows while the rail passes its group */
const AT: Record<string, number> = { blue: 0.2, green: 0.43, red: 0.71 };

export function LabelLayer() {
  const hovered = useArena((s) => s.hoveredId);
  const selected = useArena((s) => s.selectedId);
  const fac = useRef<Record<string, HTMLDivElement | null>>({});
  const tag = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let raf = 0;
    const tick = () => {
      raf = requestAnimationFrame(tick);
      for (const team of TEAMS) {
        const el = fac.current[team], a = anchors[team];
        if (!el) continue;
        const st = useArena.getState();
        const idle = st.simPhase === "idle";
        let o = st.stage === "arena" ? 1 : Math.max(0, 1 - Math.max(0, Math.abs(timeline.rail - AT[team]) - 0.03) / 0.06);
        o = idle && (st.stage === "scroll" || st.stage === "arena") ? o * o * (3 - 2 * o) : 0;
        el.style.opacity = o.toFixed(3);
        el.style.visibility = a.on && o > 0.01 ? "visible" : "hidden";
        el.style.transform = `translate3d(${a.sx}px, ${a.sy}px, 0) translate(-50%, -50%) scale(${a.scale.toFixed(3)})`;
      }
      const t = tag.current, a = anchors.tag;
      if (t) {
        t.style.visibility = a.on ? "visible" : "hidden";
        t.style.transform = `translate3d(${a.sx}px, ${a.sy}px, 0) translate(-50%, -100%)`;
      }
    };
    tick();
    return () => cancelAnimationFrame(raf);
  }, []);

  const activeId = hovered ?? selected;
  const spec = activeId ? ROSTER_BY_ID[activeId] : null;

  return (
    <div className="labels" aria-hidden>
      {TEAMS.map((team) => (
        <div key={team} className="anchor" ref={(el) => { fac.current[team] = el; }}>
          <div className={`faction-label tag-${team}`}>
            <span className="faction-count">{String(rosterOf(team).length).padStart(2, "0")}</span>
            <span className="faction-name">{TEAM_META[team].label}</span>
            <span className="faction-line">{TEAM_META[team].tagline}</span>
          </div>
        </div>
      ))}
      <div className="anchor" ref={tag}>
        {spec && (
          <div className={`agent-tag tag-${spec.team}`} key={spec.id}>
            <span className="agent-tag-role">{TEAM_META[spec.team].singular}</span>
            <span className="agent-tag-name">{spec.name}</span>
          </div>
        )}
      </div>
    </div>
  );
}
