"use client";
// Poll for the run on stage (activeRun.ts `currentRun`) every few seconds: every window joins it on load, attaches as soon as one starts,
// and follows a lineage from one generation's episode to the next. Reads only, so viewers use it too. Owner: Dev R.
//
//   const { run, link, refresh } = useActiveRun({ enabled: !MOCK, onPoll })
//   run      the current run, or null (nothing running, or not known yet)
//   link     "checking" before the first answer, "live" while something runs, "idle" when nothing does, "offline" when unreachable
//   onPoll   called after every answer with the run (or null), for callers that decide for themselves whether to attach (the arena)
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { readRun, type CurrentRun } from "./activeRun";

export const ACTIVE_RUN_POLL_MS = 4000;

export type RunLink = "checking" | "live" | "idle" | "offline";

export interface ActiveRunView {
  run: CurrentRun | null;
  link: RunLink;
  /** look again now (e.g. right after starting a run) */
  refresh: () => void;
}

export function useActiveRun(opts: { enabled?: boolean; intervalMs?: number; onPoll?: (run: CurrentRun | null) => void } = {}): ActiveRunView {
  const { enabled = true, intervalMs = ACTIVE_RUN_POLL_MS } = opts;
  const [run, setRun] = useState<CurrentRun | null>(null);
  const [link, setLink] = useState<RunLink>("checking");
  const onPoll = useRef(opts.onPoll);
  onPoll.current = opts.onPoll;
  const look = useRef<() => void>(() => {});

  useEffect(() => {
    if (!enabled) return;
    let dead = false;
    let busy = false;
    const tick = async () => {
      if (busy || dead) return;
      busy = true;
      try {
        const got = await readRun(api);
        if (dead || !got) return; // a hiccup (429, 403): keep what we have and ask again
        setLink(got.link);
        if (got.link === "offline") return;
        const r = got.run;
        setRun((prev) => (prev?.episodeId === r?.episodeId && prev?.lineageId === r?.lineageId ? prev : r));
        onPoll.current?.(r);
      } finally {
        busy = false;
      }
    };
    look.current = () => { void tick(); };
    void tick();
    const t = setInterval(tick, intervalMs);
    return () => { dead = true; clearInterval(t); look.current = () => {}; };
  }, [enabled, intervalMs]);

  const refresh = useCallback(() => look.current(), []);
  return { run, link, refresh };
}
