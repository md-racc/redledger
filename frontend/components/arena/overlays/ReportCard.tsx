"use client";
// The end-of-day report (docs/ARCHITECTURE.md, System overview): blue posts one each day (report.posted); with a live backend this shows blue's own text, and with a
// recording it shows a summary built from that day's events and says so. Owner: Dev R.
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import { daySummary, reportDays, reportText } from "@/lib/arena/report";
import type { UIState } from "@/lib/types";
import { Markdown } from "./Markdown";
import { Raw } from "./Raw";

type Body = { status: "loading" } | { status: "blue"; text: string; row: unknown } | { status: "events"; why: string };

export function ReportCard({ state, live, open, onClose }: { state: UIState; live: boolean; open: boolean; onClose: () => void }) {
  const days = useMemo(() => reportDays(state), [state]);
  const [picked, setPicked] = useState<number | null>(null);
  const day = picked !== null && days.some((d) => d.day === picked) ? picked : (days[days.length - 1]?.day ?? null);
  const entry = days.find((d) => d.day === day) ?? null;
  const cache = useRef(new Map<string, Body>());
  const [body, setBody] = useState<Body>({ status: "events", why: "" });

  // keyed on the id, not the entry: the state changes with every event and must not restart the read
  const id = entry?.report_id ?? null;
  useEffect(() => {
    if (!open || !id) return;
    const hit = cache.current.get(id);
    if (hit) { setBody(hit); return; }
    if (!live) { setBody({ status: "events", why: "This is a recording: blue's written text is only kept by a live battlefield." }); return; }
    let dead = false;
    setBody({ status: "loading" });
    api.fe.report(id).then(
      (row) => {
        const text = reportText(row);
        const b: Body = text ? { status: "blue", text, row } : { status: "events", why: "The battlefield has no text for this report." };
        cache.current.set(id, b);
        if (!dead) setBody(b);
      },
      () => { if (!dead) setBody({ status: "events", why: "Blue's report could not be read just now." }); },
    );
    return () => { dead = true; };
  }, [open, id, live]);

  const text = body.status === "blue" ? body.text : day !== null ? daySummary(state, day) : "";
  return (
    <section className={`rep ${open ? "is-open" : ""}`} role="dialog" aria-label="End-of-day report" aria-hidden={!open}>
      <header>
        <span className="cmp-kicker">End-of-day report{day !== null ? ` · day ${day}` : ""}</span>
        {open && id && body.status !== "loading" && <span className="evo-src">{body.status === "blue" ? "blue's report" : "built from the day's events"}</span>}
        <button className="icon-btn" onClick={onClose} aria-label="Close">✕</button>
      </header>
      {open && days.length === 0 && <p className="evo-wait">No report yet. Blue posts one at the end of every simulated day: run an episode and it will appear here.</p>}
      {open && days.length > 0 && (
        <>
          <nav className="rep-days" aria-label="Days with a report">
            {days.map((d) => <button key={d.report_id} className={d.day === day ? "on" : ""} onClick={() => setPicked(d.day)}>Day {d.day}</button>)}
          </nav>
          <div className="rep-body">{body.status === "loading" ? <p className="evo-wait">Reading blue&apos;s report…</p> : <Markdown text={text} />}</div>
          <footer>
            {body.status === "events" && body.why ? `${body.why} ` : ""}
            {body.status === "blue" ? "Written by blue at the end of the day." : "A plain tally of what the arena saw that day, not blue's own words."}
            <Raw data={body.status === "blue" ? body.row : { report_id: entry?.report_id, day, summary_from: "events" }} />
          </footer>
        </>
      )}
    </section>
  );
}
