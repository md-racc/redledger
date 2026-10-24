"use client";
// The show's chrome: a progress bar split into its beats, transport controls, and the big caption line. Owner: Dev R.
import { useEffect, useRef } from "react";
import { SHOW_BEATS } from "@/lib/arena/show";

const ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"];
import { subscribeShowClock } from "@/lib/arena/showClock";
import { useArena } from "@/lib/arena/store";
import type { ShowController } from "../useShow";

export function ShowBar({ show }: { show: ShowController }) {
  const caption = useArena((s) => s.show.caption);
  const sub = useArena((s) => s.show.sub);
  const rewind = useArena((s) => s.rewind);
  const root = useRef<HTMLDivElement>(null);
  const active = show.status === "playing" || show.status === "paused";

  useEffect(() => subscribeShowClock((c) => root.current?.style.setProperty("--t", (c.t / c.total).toFixed(4))), []);

  return (
    <>
      <div ref={root} className={`showbar ${active ? "is-on" : ""}`} aria-hidden={!active}>
        <div className="showbar-track" role="group" aria-label="Show progress">
          {SHOW_BEATS.map((b, i) => (
            <button
              key={b.id}
              className={`seg-beat ${i === show.index ? "on" : i < show.index ? "past" : ""}`}
              style={{ flexGrow: b.end - b.at }}
              onClick={() => { show.seek(i); }}
              title={b.label}
            >
              <span><i>{ROMAN[i]}</i><em>{b.label}</em></span>
            </button>
          ))}
          <i className="showbar-fill" />
        </div>
        <div className="showbar-ctl">
          <button className="icon-btn" onClick={show.prev} aria-label="Previous beat" title="Back (←)">‹</button>
          <button className="icon-btn" onClick={show.toggle} aria-label={show.status === "paused" ? "Resume" : "Pause"} title="Pause (space)">{show.status === "paused" ? "▶" : "❚❚"}</button>
          <button className="icon-btn" onClick={show.next} aria-label="Next beat" title="Next (→)">›</button>
          <button className="icon-btn" onClick={show.stop} aria-label="Leave the show" title="Leave the show (esc)">✕</button>
        </div>
      </div>

      <div className={`show-caption ${active && caption ? "is-on" : ""}`} aria-live="polite">
        {caption && (
          <div key={caption}>
            <p>{caption}</p>
            {sub && <small>{sub}</small>}
          </div>
        )}
      </div>

      {/* between acts: the clock runs back to day 0 */}
      {rewind > 0 && (
        <div key={rewind} className="rewind" aria-hidden>
          <span>Rewind</span>
          <small>day 0 · same seed · controller on</small>
        </div>
      )}
    </>
  );
}
