"use client";
// The React side of the 90-second show: gives the director (lib/arena/show.ts) a real world to act on. Owner: Dev R.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ShowDirector, type ShowHost, type ShowStatus } from "@/lib/arena/show";
import { emitShowClock, showClock } from "@/lib/arena/showClock";
import { useArena } from "@/lib/arena/store";
import { SHOW_INTRO_SECONDS, INTRO_SECONDS, timeline } from "@/lib/arena/timeline";
import type { Feed } from "@/lib/arena/useFeed";

/** how long each act of recorded story plays, and how long an escalation waits for a human before it blocks */
const ACT_MS = { off: 15_000, on: 16_500 } as const;
const HOLD_MS = 4_800;

/** The show runs on the battlefield when one is up and its agents are keyless (free and fast); `?show=live` or `?show=recorded` forces it. */
function wantLive(feed: Feed): boolean {
  const forced = typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("show") : null;
  if (forced === "recorded") return false;
  if (forced === "live") return feed.backend.state === "live";
  return feed.backend.state === "live" && feed.backend.keyless;
}

export interface ShowController {
  status: ShowStatus;
  index: number;
  start: () => void;
  stop: () => void;
  toggle: () => void;
  next: () => void;
  prev: () => void;
  seek: (i: number) => void;
  /** bumped on every (re)start of the intro, so the title lockup can replay its entrance */
  runKey: number;
}

export function useShow(feed: Feed): ShowController {
  const [status, setStatus] = useState<ShowStatus>("off");
  const [index, setIndex] = useState(-1);
  const [runKey, setRunKey] = useState(0);
  const feedRef = useRef(feed);
  feedRef.current = feed;

  const host = useMemo<ShowHost>(() => {
    const st = () => useArena.getState();
    const scrollMax = () => Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
    const toLawns = () => {
      st().select(null);
      st().setPanel(null);
      st().actions.disperse();
      feedRef.current.reset();
    };
    return {
      restartIntro() {
        toLawns();
        timeline.introTime = 0;
        timeline.intro = 0;
        timeline.introLen = SHOW_INTRO_SECONDS;
        window.scrollTo(0, 0);
        st().setSkipIntro(false);
        st().setStage("intro");
        setRunKey((k) => k + 1);
      },
      restartTour() {
        const s = st();
        if (s.stage === "loading") return;
        toLawns();
        window.scrollTo(0, 0);
        if (s.stage === "intro") s.setSkipIntro(true); // the camera rig ends the flight on its next frame
      },
      tourReady: () => st().stage === "scroll" || st().stage === "arena",
      setScroll(f) {
        if (st().stage === "intro") st().setSkipIntro(true);
        window.scrollTo(0, f * scrollMax());
      },
      converge: () => st().actions.converge(),
      startAct(act) {
        if (act === "on") st().bumpRewind();
        st().select(null);
        void feedRef.current.startAct(act, ACT_MS[act], HOLD_MS, { live: wantLive(feedRef.current), autoBlockMs: HOLD_MS });
      },
      setPanel: (p) => st().setPanel(p),
      evolveProgress(p) { showClock.evolve = p; },
      setCaption: (text, sub) => st().setShow({ caption: text, sub: sub ?? null }),
      onBeat(b, i) {
        st().setShow({ beat: b.id });
        setIndex(i);
      },
      onDone() {
        setStatus("done");
        st().setShow({ status: "done", caption: null, sub: null });
        feedRef.current.setPaused(false);
      },
    };
  }, []);

  const director = useMemo(() => new ShowDirector(host), [host]);

  const sync = useCallback(() => {
    setStatus(director.status);
    useArena.getState().setShow({ status: director.status });
  }, [director]);

  // the clock: one rAF loop, only while the show is playing
  useEffect(() => {
    if (status !== "playing") return;
    let raf = 0;
    let last = performance.now();
    const loop = (now: number) => {
      raf = requestAnimationFrame(loop);
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      director.update(dt);
      showClock.t = director.t;
      emitShowClock();
      if (director.status !== "playing") sync();
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [status, director, sync]);

  // outside the show the intro keeps its normal length (ArenaExperience locks the page scroll while the show runs)
  useEffect(() => { if (status === "off" || status === "done") timeline.introLen = INTRO_SECONDS; }, [status]);

  const start = useCallback(() => {
    if (useArena.getState().stage === "loading") return;
    feedRef.current.clearRuns();
    feedRef.current.setPaused(false);
    director.start();
    sync();
  }, [director, sync]);

  const stop = useCallback(() => {
    director.stop();
    feedRef.current.setPaused(false);
    sync();
    useArena.getState().setShow({ beat: null, caption: null, sub: null });
    setIndex(-1);
  }, [director, sync]);

  const toggle = useCallback(() => {
    if (director.status === "playing") { director.pause(); feedRef.current.setPaused(true); }
    else if (director.status === "paused") { director.resume(); feedRef.current.setPaused(false); }
    sync();
  }, [director, sync]);

  const next = useCallback(() => { if (director.status !== "off") { director.next(); feedRef.current.setPaused(false); sync(); } }, [director, sync]);
  const prev = useCallback(() => { if (director.status !== "off") { director.prev(); feedRef.current.setPaused(false); sync(); } }, [director, sync]);

  const seek = useCallback((i: number) => { if (director.status !== "off") { director.seek(i); feedRef.current.setPaused(false); sync(); } }, [director, sync]);

  // keys: space pauses, arrows jump between beats, escape leaves the show (and S starts it)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
      const active = director.status === "playing" || director.status === "paused";
      if (active && e.code === "Space") { e.preventDefault(); toggle(); }
      else if (active && e.key === "ArrowRight") { e.preventDefault(); next(); }
      else if (active && e.key === "ArrowLeft") { e.preventDefault(); prev(); }
      else if (active && e.key === "Escape") { stop(); }
      else if (!active && (e.key === "s" || e.key === "S") && !e.metaKey && !e.ctrlKey) start();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [director, toggle, next, prev, stop, start]);

  return { status, index, start, stop, toggle, next, prev, seek, runKey };
}
