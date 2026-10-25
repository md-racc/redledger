"use client";
// Poll for the run on stage (activeRun.ts `currentRun`) every few seconds: every window joins it on load, attaches as soon as one starts,
// and follows a lineage from one generation's episode to the next. Reads only, so viewers use it too. Owner: Dev R.
//
//   const { run, link, refresh } = useActiveRun({ enabled: !MOCK, onPoll })
//   run      the current run, or null (nothing running, or not known yet)
//   link     "checking" before the first answer, "live" while something runs, "idle" when nothing does, "offline" when unreachable
//   onPoll   called after every answer with the run (or null), for callers that decide for themselves whether to attach (the arena)
//
// Every poll also publishes, to `useRunPulse`, what a screen needs when nothing is on stage: whether the backend answered, whether the
// newest run is paused, and the newest finished run with its final score (for "Between runs · last run …" and a link to its report).
// `runStatus` turns that into the HUD's honest status line: "backend offline" only when the backend really did not answer.
import { useCallback, useEffect, useRef, useState } from "react";
import { create } from "zustand";
import { api } from "../api";
import type { Score } from "../types";
import { readRun, type CurrentRun, type RunReader } from "./activeRun";

export const ACTIVE_RUN_POLL_MS = 4000;

export type RunLink = "checking" | "live" | "idle" | "offline";

export interface ActiveRunView {
  run: CurrentRun | null;
  link: RunLink;
  /** look again now (e.g. right after starting a run) */
  refresh: () => void;
}

/** The newest run that has ended, as GET /episodes lists it, with its final score once read (null until then, or if it can't be). */
export interface LastRun {
  episodeId: string;
  status: "finished" | "failed";
  score: Score | null;
}

export interface RunPulse {
  /** the last poll's answer: "idle" and "live" both mean the backend answered */
  link: RunLink;
  /** the newest run that got going is paused (the operator paused it) */
  paused: boolean;
  last: LastRun | null;
}

export const useRunPulse = create<RunPulse>(() => ({ link: "checking", paused: false, last: null }));

interface EpisodeRow { id?: unknown; status?: unknown }

const STARTED = new Set(["running", "paused", "finished", "failed"]);
/** Real runs only, in GET /episodes order (newest first): replays never count, and an episode that never started says nothing. */
const started = (list: readonly EpisodeRow[] | null | undefined): EpisodeRow[] =>
  (list ?? []).filter((e) => typeof e.id === "string" && !e.id.startsWith("replay_") && STARTED.has(String(e.status)));

/** The newest run that ended (GET /episodes is newest first). */
export function newestEnded(list: readonly EpisodeRow[] | null | undefined): { episodeId: string; status: "finished" | "failed" } | null {
  const e = started(list).find((x) => x.status === "finished" || x.status === "failed");
  return e ? { episodeId: e.id as string, status: e.status as "finished" | "failed" } : null;
}

/** Is the newest run that got going paused? (an old paused episode under a newer finished one is not "paused now") */
export function newestIsPaused(list: readonly EpisodeRow[] | null | undefined): boolean {
  return started(list)[0]?.status === "paused";
}

/** A score answer from GET /episodes/{id}/score, or null when it does not look like one. */
export function parseScore(v: unknown): Score | null {
  const o = v as Record<string, unknown> | null;
  if (!o || typeof o !== "object" || typeof o.dollars_extracted !== "number") return null;
  const n = (k: string) => (typeof o[k] === "number" ? (o[k] as number) : 0);
  return {
    dollars_extracted: n("dollars_extracted"),
    dollars_blocked: n("dollars_blocked"),
    false_positive_cost: n("false_positive_cost"),
    detection_latency_days: typeof o.detection_latency_days === "number" ? o.detection_latency_days : null,
    attacks_launched: n("attacks_launched"),
    attacks_caught: n("attacks_caught"),
    legit_blocked: n("legit_blocked"),
    legit_processed: n("legit_processed"),
  };
}

export interface RunStatusInput {
  /** NEXT_PUBLIC_MOCK: no backend at all, the feed's own note says so */
  mock: boolean;
  /** the feed's one-line note */
  note: string;
  /** the feed's health probe */
  backend: "checking" | "live" | "offline";
  /** the active-run poll (useRunPulse) */
  link: RunLink;
  /** something is on screen: a live or attached run, the recording, an act, the show */
  onScreen: boolean;
  paused: boolean;
}

export interface RunStatus {
  /** replaces the IDLE source badge when nothing is on screen and the backend answered */
  badge: "BETWEEN RUNS" | "PAUSED" | null;
  /** the HUD's status line */
  note: string;
  /** the backend answered something (its health, or the run poll): never call it offline then */
  reachable: boolean;
  /** nothing on screen and the backend answered: show the last finished run, if there is one */
  between: boolean;
}

const STALE_OFFLINE = /^backend (offline|unreachable)/;

/**
 * The HUD's status: "Between runs" (or "Paused") when the backend answers but nothing is on stage, "backend offline" only when neither
 * the health probe nor the run poll got an answer. The health probe can time out on a busy stack (it asks every agent) while the run
 * poll answers: an answer from either wins.
 */
export function runStatus(i: RunStatusInput): RunStatus {
  const reachable = !i.mock && (i.backend === "live" || i.link === "live" || i.link === "idle");
  if (i.mock || i.onScreen) return { badge: null, note: i.note, reachable, between: false };
  if (reachable && i.link !== "live") {
    return i.paused
      ? { badge: "PAUSED", note: "Paused · the run resumes when the operator says so", reachable, between: true }
      : { badge: "BETWEEN RUNS", note: "Between runs · the next one starts soon", reachable, between: true };
  }
  // a run is going and the screen is about to join it: never call that backend offline
  if (reachable) return { badge: null, note: STALE_OFFLINE.test(i.note) ? "backend live · joining the run in progress" : i.note, reachable, between: false };
  return { badge: null, note: i.note, reachable, between: false };
}

/** GET /episodes, kept for the pulse (the same read `currentRun` makes: no extra request). */
function remembering(reader: RunReader, keep: (list: EpisodeRow[]) => void): RunReader {
  return {
    ...reader,
    listEpisodes: async () => {
      const list = await reader.listEpisodes();
      keep(Array.isArray(list) ? (list as EpisodeRow[]) : []);
      return list;
    },
  };
}

const scores = new Map<string, Score>();

/** The final score of an ended run: GET /episodes/{id}/score once (a viewer may read it), null on any failure (asked again next poll). */
async function finalScore(id: string): Promise<Score | null> {
  const known = scores.get(id);
  if (known) return known;
  try {
    const r = await fetch(`/api/bf/episodes/${encodeURIComponent(id)}/score`, { headers: { Accept: "application/json" }, cache: "no-store", signal: AbortSignal.timeout(5000) });
    if (!r.ok) return null;
    const s = parseScore(await r.json());
    if (s) scores.set(id, s);
    return s;
  } catch {
    return null;
  }
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
    let list: EpisodeRow[] | null = null;
    const reader = remembering(api, (l) => { list = l; });
    const tick = async () => {
      if (busy || dead) return;
      busy = true;
      list = null;
      try {
        const got = await readRun(reader);
        if (dead || !got) return; // a hiccup (429, 403): keep what we have and ask again
        setLink(got.link);
        if (got.link === "offline") { useRunPulse.setState({ link: "offline" }); return; }
        const r = got.run;
        setRun((prev) => (prev?.episodeId === r?.episodeId && prev?.lineageId === r?.lineageId ? prev : r));
        onPoll.current?.(r);
        const ended = newestEnded(list);
        const prev = useRunPulse.getState().last;
        const score = ended && prev?.episodeId === ended.episodeId ? prev.score : null;
        useRunPulse.setState({ link: got.link, paused: newestIsPaused(list), last: ended ? { ...ended, score } : null });
        if (ended && !score) {
          const s = await finalScore(ended.episodeId);
          if (!dead && s && useRunPulse.getState().last?.episodeId === ended.episodeId) useRunPulse.setState({ last: { ...ended, score: s } });
        }
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
