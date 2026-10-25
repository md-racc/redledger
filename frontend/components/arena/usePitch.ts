"use client";
// The React side of pitch mode (lib/arena/pitch.ts): the intro flight, the tour fast-forwarded, then the live run. Owner: Dev Ad (crunch).
//
//   P / ?pitch=1 / the title's "Live pitch" button   start (or restart) it
//   Esc                                              leave it (the run itself keeps going on the battlefield)
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { PITCH_AUTOBLOCK_MS, PITCH_SEED, PITCH_TOUR_MS, pitchQuery } from "@/lib/arena/pitch";
import { useArena } from "@/lib/arena/store";
import { SHOW_INTRO_SECONDS, claimIntroLen, releaseIntroLen, timeline } from "@/lib/arena/timeline";
import type { Feed, PitchResult } from "@/lib/arena/useFeed";

/** `intro`: the flight and the tour; `on`: in the arena with the run */
export type PitchPhase = "off" | "intro" | "on";

export interface PitchController {
  phase: PitchPhase;
  /** what the feed got, once it asked; `connecting` while it asks */
  result: PitchResult | "connecting" | null;
  seed: number;
  start: () => void;
  stop: () => void;
  /** bumped on every start, so the title lockup replays its entrance and the narration starts clean */
  runKey: number;
}

const ease = (k: number) => (k < 0.5 ? 2 * k * k : 1 - (-2 * k + 2) ** 2 / 2);

export function usePitch(feed: Feed, opts: { onStart?: () => void } = {}): PitchController {
  const [phase, setPhase] = useState<PitchPhase>("off");
  const [result, setResult] = useState<PitchController["result"]>(null);
  const [runKey, setRunKey] = useState(0);
  const stage = useArena((s) => s.stage);
  const feedRef = useRef(feed);
  feedRef.current = feed;
  const onStart = useRef(opts.onStart);
  onStart.current = opts.onStart;
  const phaseRef = useRef(phase);
  phaseRef.current = phase;
  /** the run has been asked for, in this start */
  const kicked = useRef(false);
  /** bumped on every start and stop: the answer to a superseded request is dropped */
  const req = useRef(0);
  const seed = useMemo(() => (typeof window === "undefined" ? PITCH_SEED : pitchQuery(window.location.search).seed), []);

  const start = useCallback(() => {
    onStart.current?.();
    const st = useArena.getState();
    st.select(null);
    st.setPanel(null);
    kicked.current = false;
    req.current++;
    setResult(null);
    claimIntroLen("pitch", SHOW_INTRO_SECONDS);
    // replay the flight from the top, unless it has only just begun (?pitch=1 on load)
    if (st.stage !== "loading" && !(st.stage === "intro" && timeline.introTime < 1.5)) {
      st.actions.disperse();
      window.scrollTo(0, 0);
      timeline.introTime = 0;
      timeline.intro = 0;
      st.setSkipIntro(false);
      st.setStage("intro");
    }
    setRunKey((k) => k + 1);
    setPhase("intro");
  }, []);

  const stop = useCallback(() => {
    setPhase("off");
    setResult(null);
    kicked.current = false;
    req.current++;
    feedRef.current.stopPitch();
    releaseIntroLen("pitch"); // a no-op once the arena is reached, or when the show has taken the flight over
  }, []);

  // the flight is over: ask for the run, fast-forward the tour, and once in the arena send everyone in
  useEffect(() => {
    if (phase !== "intro" || (stage !== "scroll" && stage !== "arena")) return;
    if (!kicked.current) {
      kicked.current = true;
      setResult("connecting");
      const mine = req.current;
      const settle = (r: PitchResult | "refused") => { if (mine === req.current) setResult(r); };
      void feedRef.current.pitch({ seed, autoBlockMs: PITCH_AUTOBLOCK_MS }).then(settle, () => settle("refused"));
    }
    if (stage === "arena") {
      releaseIntroLen("pitch");
      setPhase("on");
      useArena.getState().actions.converge();
      return;
    }
    const max = () => Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
    const from = Math.min(1, window.scrollY / max());
    const t0 = performance.now();
    let raf = 0;
    const loop = (now: number) => {
      const k = Math.min(1, (now - t0) / PITCH_TOUR_MS);
      window.scrollTo(0, (from + (1 - from) * ease(k)) * max());
      if (k < 1) raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [phase, stage, seed]);

  // keys: P starts (or restarts), Esc leaves when nothing else is open
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
      if ((e.key === "p" || e.key === "P") && !e.metaKey && !e.ctrlKey && !e.altKey) start();
      else if (e.key === "Escape" && phaseRef.current !== "off") {
        const s = useArena.getState();
        if (!s.panel && !s.selectedId) stop();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [start, stop]);

  return { phase, result, seed, start, stop, runKey };
}
