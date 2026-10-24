"use client";
// The agent dossier: opens when an agent is clicked in the 3D scene (or picked from the roster).
// Every row has a data source; rows without a value render as placeholders naming that source.
import { useEffect, useMemo, useRef, useState } from "react";
import { buildDetails, formatValue, type Catalogs } from "@/lib/arena/details";
import { bridge } from "@/lib/arena/bridge";
import { rosterOf, ROSTER_BY_ID, TEAM_META } from "@/lib/arena/roster";
import { useArena } from "@/lib/arena/store";
import type { AgentDetailOverrides, DetailField } from "@/lib/arena/types";
import type { UIState } from "@/lib/types";

interface Props {
  state: UIState;
  catalogs: Catalogs;
  overrides?: AgentDetailOverrides;
}

export function AgentModal({ state, catalogs, overrides }: Props) {
  const selectedId = useArena((s) => s.selectedId);
  const select = useArena((s) => s.select);
  const [shown, setShown] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const panel = useRef<HTMLElement>(null);
  const line = useRef<SVGPathElement>(null);
  const dot = useRef<SVGCircleElement>(null);

  // mount → animate in; unmount after the exit transition
  useEffect(() => {
    if (selectedId) {
      setShown(selectedId);
      const r = requestAnimationFrame(() => setOpen(true));
      return () => cancelAnimationFrame(r);
    }
    setOpen(false);
    const t = setTimeout(() => setShown(null), 420);
    return () => clearTimeout(t);
  }, [selectedId]);

  useEffect(() => {
    if (!selectedId) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") select(null); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectedId, select]);

  // connector from the agent in the scene to the panel edge
  useEffect(() => {
    if (!shown) return;
    let raf = 0;
    const tick = () => {
      raf = requestAnimationFrame(tick);
      const p = bridge.project(shown);
      const box = panel.current?.getBoundingClientRect();
      const path = line.current, d = dot.current;
      if (!path || !d || !box || !p || p.z > 1 || !open) { if (path) path.style.opacity = "0"; if (d) d.style.opacity = "0"; return; }
      const vertical = box.width > window.innerWidth * 0.7; // bottom sheet on phones
      const ex = vertical ? box.left + box.width / 2 : box.left;
      const ey = vertical ? box.top : box.top + 76;
      const mx = p.x + (ex - p.x) * 0.55;
      path.setAttribute("d", vertical ? `M${p.x},${p.y} C${p.x},${(p.y + ey) / 2} ${ex},${(p.y + ey) / 2} ${ex},${ey}` : `M${p.x},${p.y} C${mx},${p.y} ${mx},${ey} ${ex},${ey}`);
      path.style.opacity = "0.9";
      d.setAttribute("cx", String(p.x)); d.setAttribute("cy", String(p.y)); d.style.opacity = "1";
    };
    tick();
    return () => cancelAnimationFrame(raf);
  }, [shown, open]);

  const details = useMemo(() => (shown ? buildDetails(shown, state, catalogs, overrides) : null), [shown, state, catalogs, overrides]);
  if (!shown || !details) return null;

  const meta = TEAM_META[details.team];
  const team = rosterOf(details.team);
  const idx = team.findIndex((a) => a.id === shown);
  const step = (d: number) => select(team[(idx + d + team.length) % team.length].id);
  void ROSTER_BY_ID;

  return (
    <>
      <svg className={`connector tone-${details.team} ${open ? "is-open" : ""}`} aria-hidden>
        <path ref={line} fill="none" strokeWidth="1.25" />
        <circle ref={dot} r="4" />
      </svg>
      <aside ref={panel} className={`dossier tone-${details.team} ${open ? "is-open" : ""}`} role="dialog" aria-labelledby="dossier-title" aria-modal="false" tabIndex={-1}>
        <header className="dossier-head">
          <div className="dossier-role">
            <i className="dossier-pip" />{details.role}<span>·</span>{meta.role}
            <span className="dossier-count">{String(idx + 1).padStart(2, "0")}/{String(team.length).padStart(2, "0")}</span>
          </div>
          <h2 id="dossier-title">{details.title}</h2>
          <p className="dossier-caption">{details.caption}</p>
          <div className="dossier-bar">
            {details.status && <span className={`status status-${details.status.tone}`}><i />{details.status.label}</span>}
            {details.placeholder && <span className="status status-ph">placeholder data</span>}
            <span className="grow" />
            <button className="icon-btn" onClick={() => step(-1)} aria-label="Previous agent">‹</button>
            <button className="icon-btn" onClick={() => step(1)} aria-label="Next agent">›</button>
            <button className="icon-btn" onClick={() => select(null)} aria-label="Close dossier">✕</button>
          </div>
        </header>

        <div className="dossier-body" key={shown}>
          {details.story && <blockquote className="dossier-story">{details.story}</blockquote>}
          {details.sections.map((sec) => (
            <section key={sec.title} className="dossier-sec">
              <h3>{sec.title}</h3>
              <dl>
                {sec.fields.map((f) => <Row key={f.key} f={f} />)}
              </dl>
            </section>
          ))}
        </div>
        <footer className="dossier-foot">
          <span>esc to close</span>
          <span>data: /api/fe · events</span>
        </footer>
      </aside>
    </>
  );
}

function Row({ f }: { f: DetailField }) {
  const v = formatValue(f);
  return (
    <div className="row">
      <dt>{f.label}</dt>
      <dd className={f.kind === "mono" ? "mono" : ""}>
        {v ?? <span className="ph" title={`Awaiting ${f.source}`}><i /><em>{f.source}</em></span>}
      </dd>
    </div>
  );
}
