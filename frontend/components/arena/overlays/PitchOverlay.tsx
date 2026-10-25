"use client";
// Pitch mode's screen furniture: where the events come from (LIVE / RECORDED and the agents' modes), captions narrated from the real
// events (lib/arena/narration.ts), whose turn it is, and the closing card at episode.ended. Owner: Dev Ad (crunch).
// The arena animation, the HUD and the escalation card stay as they are; this only adds words.
import { useEffect, useRef, useState } from "react";
import { CaptionQueue, captionFor, statusFor, type Caption } from "@/lib/arena/narration";
import { pitchStatus } from "@/lib/arena/pitch";
import { money } from "@/lib/arena/headlines";
import { provenance } from "@/lib/arena/provenance";
import { useArena } from "@/lib/arena/store";
import type { Feed } from "@/lib/arena/useFeed";
import type { Score } from "@/lib/types";
import type { PitchController } from "../usePitch";

const MOCK_ONLY = process.env.NEXT_PUBLIC_MOCK === "true";
const usd = (n: unknown) => money(n) || "$0";

interface Ended { episodeId: string; score: Partial<Score> | null }

export function PitchOverlay({ feed, pitch }: { feed: Feed; pitch: PitchController }) {
  const stage = useArena((s) => s.stage);
  const on = pitch.phase !== "off";
  const [caption, setCaption] = useState<Caption | null>(null);
  const [turn, setTurn] = useState<string | null>(null);
  const [ended, setEnded] = useState<Ended | null>(null);
  const queue = useRef(new CaptionQueue());
  // the episode's length, from its own episode.started (the reducer's copy lags a render behind the event that follows it)
  const days = useRef(0);
  // an open escalation is the story while it is open: its card speaks, the captions wait (the run is held at the gate anyway)
  const escOpen = Object.values(feed.state.escalations).some((x) => x.status === "open");
  const visible = useRef(false);
  visible.current = on && stage === "arena" && !escOpen;

  // a fresh start is a clean slate
  useEffect(() => {
    queue.current.clear();
    setCaption(null);
    setTurn(null);
    setEnded(null);
  }, [pitch.runKey, on]);

  // every event as the arena plays it (after the pacer)
  const subscribe = feed.subscribe;
  useEffect(() => {
    if (!on) return;
    return subscribe((e) => {
      if (e.type === "episode.started") {
        days.current = Number((e.payload as { days?: number }).days) || 0;
        setEnded(null);
        queue.current.clear();
        setCaption(null);
      }
      if (e.type === "episode.ended") setEnded({ episodeId: e.episode_id, score: (e.payload as { final_score?: Partial<Score> }).final_score ?? null });
      const s = statusFor(e);
      if (s !== undefined) setTurn(s);
      const c = captionFor(e, days.current);
      if (c && queue.current.push(c)) setCaption(queue.current.current);
    });
  }, [on, subscribe]);

  // the caption clock runs only while the arena is on screen, so nothing is read out over the intro
  useEffect(() => {
    if (!on) return;
    let last = performance.now();
    const t = setInterval(() => {
      const now = performance.now();
      const dt = now - last;
      last = now;
      if (visible.current && queue.current.advance(dt)) setCaption(queue.current.current);
    }, 150);
    return () => clearInterval(t);
  }, [on]);

  if (!on) return null;

  const prov = provenance({ backend: feed.backend, source: feed.source, inShow: false, episodeId: feed.state.episodeId, recording: feed.recording });
  const status = pitchStatus(pitch.result, { source: feed.source, mockOnly: MOCK_ONLY, seed: pitch.seed, note: feed.note });
  const s = ended?.score;

  return (
    <div className={`pitch ${stage === "arena" ? "is-on" : ""}`} aria-live="polite">
      <div className="pitch-strip" title={prov.meaning}>
        <span className={`pitch-badge badge-${prov.badge.toLowerCase()}`}>{prov.badge}</span>
        <span className="pitch-agents">{prov.agents.map((a) => (
          <span key={a.name} className={`tag-${a.name}`}><b>{a.name}</b> {a.mode}{a.model ? ` · ${a.model}` : ""}</span>
        ))}</span>
        {prov.episode && <span className="pitch-ep">{prov.episode}{prov.recordedOn ? ` · recorded ${prov.recordedOn}` : ""}</span>}
      </div>
      {(status || turn) && (
        <p className="pitch-status" title={status ?? undefined}>
          {turn ? <em>{turn}<i className="pitch-dots" aria-hidden>…</i></em> : status}
        </p>
      )}

      {caption && !ended && !escOpen && (
        <div key={`${caption.key}:${caption.count ?? 1}`} className={`pitch-caption tone-${caption.tone}`}>
          <span className="pitch-tag">{caption.tag}{caption.count && caption.count > 1 ? ` ×${caption.count}` : ""}</span>
          <p className={caption.quote ? "is-quote" : ""}>{caption.quote ? `“${caption.text}”` : caption.text}</p>
          {caption.sub && <small>{caption.sub}</small>}
        </div>
      )}

      {ended && (
        <section className="pitch-end" role="dialog" aria-label="Episode over">
          <button className="pitch-x" onClick={() => setEnded(null)} aria-label="Close">×</button>
          <span className="pitch-tag">Episode over · {ended.episodeId}{prov.recordedOn ? ` · recorded ${prov.recordedOn}` : ""}</span>
          <h2>{usd(s?.dollars_extracted)} stolen, {usd(s?.dollars_blocked)} blocked</h2>
          <div className="pitch-end-tiles">
            <div className="tile tone-red"><span>Stolen</span><b>{usd(s?.dollars_extracted)}</b></div>
            <div className="tile tone-blue"><span>Blocked</span><b>{usd(s?.dollars_blocked)}</b></div>
            <div className="tile tone-amber"><span>False-positive cost</span><b>{usd(s?.false_positive_cost)}</b></div>
            <div className="tile tone-green"><span>Caught</span><b>{s?.attacks_caught ?? 0}/{s?.attacks_launched ?? 0}</b></div>
          </div>
          <a className="pitch-report" href={`/report/${encodeURIComponent(ended.episodeId)}`}>Controls report →</a>
          <small>The battlefield&rsquo;s own final score. <kbd>P</kbd> runs it again · <kbd>Esc</kbd> leaves pitch mode.</small>
        </section>
      )}
    </div>
  );
}
