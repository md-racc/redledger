"use client";
// The data behind the backstage consoles. Owner: Dev R.
//
// Four laptops on stage: one runs the arena, the other three each show a team's side of the backend, live. They are separate
// browsers with no shared state, so each console follows the battlefield itself: it polls GET /episodes, attaches to the newest
// episode (whoever created it, the arena's show or a curl), opens the ticketed WebSocket with after_id=0 so a console that joins
// late still gets the whole episode, and folds the events with the same reducer as the arena. REST reads from /api/fe add what
// events do not carry (cash, AP aging, gate latency, the confusion matrix).
//
// With no backend it loops the recorded episode instead and says so (mode "recorded"), so a console can be rehearsed anywhere.
// If the backend answers but the socket will not open (a network that drops the upgrade, a dev server with no /api/ws), lib/ws.ts
// reads the events over REST instead and `feed` says which of the two is carrying them.
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { loadFixture } from "@/lib/mock";
import { initialState, reduce } from "@/lib/reducer";
import type { ControllerMode, RLEvent, UIState } from "@/lib/types";
import { connect, type FeedLink } from "@/lib/ws";
import { isUnreachable } from "@/lib/arena/activeRun";
import { loadLineageReport, type LineageReport } from "@/lib/arena/lineage";
import { ScriptRunner } from "@/lib/arena/script";
import { buildOnAct } from "@/lib/arena/showScripts";
import { recordingScript } from "@/lib/backstage/recording";

const MOCK_ONLY = process.env.NEXT_PUBLIC_MOCK === "true";
const EVENT_CAP = 900;

export interface EpisodeRow { id: string; seed: number; controller_mode: ControllerMode; days: number; status: string; current_day: number; created_at?: string }
export type Mode = "connecting" | "live" | "recorded";
export type Want = "snapshot" | "apAging" | "timeline" | "confusion" | "verdicts" | "activity" | "reports" | "escalations";

export interface Agg {
  snapshot?: any;
  apAging?: any[];
  timeline?: any[];
  confusion?: any[];
  verdicts?: any[];
  activity?: any;
  reports?: any[];
  escalations?: any[];
}

export interface Backstage {
  mode: Mode;
  health: any | null;
  episodes: EpisodeRow[];
  episode: EpisodeRow | null;
  pinned: string | null;
  pin: (id: string | null) => void;
  state: UIState;
  /** every event of the followed episode, oldest first (capped) */
  events: RLEvent[];
  agg: Agg;
  lineage: LineageReport | null;
  lineageSource: "live" | "recorded" | null;
  /** events per minute over the last minute */
  rate: number;
  /** wall clock, ticks once a second, for "3s ago" */
  now: number;
  /** how long the last GET /health took, ms (null before the first answer or when it failed) */
  healthMs: number | null;
  /** wall time of the last event that arrived over the socket */
  lastEventAt: number | null;
  /** the recording being replayed (mode "recorded" only), else null */
  recording: string | null;
  /** how events reach this window (live mode): the socket, or the REST read it falls back to when the socket will not open */
  feed: FeedLink | null;
  /** the last refusal from the proxy while the mode is still "connecting" (403 not signed in, 401 token, 429 rate limit), else null */
  answer: string | null;
  refresh: () => void;
}

type Action = RLEvent | { type: "__reset" };
const wrapped = (s: UIState, a: Action): UIState => (a.type === "__reset" ? initialState() : reduce(s, a as RLEvent));

const FETCH: Record<Want, (ep: string) => Promise<any>> = {
  snapshot: (ep) => api.fe.snapshot(ep),
  apAging: (ep) => api.fe.apAging(ep),
  timeline: (ep) => api.fe.timeline(ep),
  confusion: (ep) => api.fe.confusion(ep),
  verdicts: (ep) => api.fe.verdicts(ep, { limit: 200 }),
  activity: (ep) => api.fe.agentActivity(ep),
  reports: (ep) => api.fe.reports(ep),
  escalations: (ep) => api.fe.escalations(ep),
};

export interface BackstageOptions {
  /** replay this recording (public/mocks/<name>.jsonl, the real live-red run) instead of the mock loop when there is no backend */
  recording?: string;
  /** replay the recording even though a backend answers (`?replay=1`), for showing the messy stream on demand */
  forceRecorded?: boolean;
}

export function useBackstage(want: Want[] = [], opts: BackstageOptions = {}): Backstage {
  const recName = opts.recording ?? null;
  const forced = !!opts.forceRecorded;
  const [mode, setMode] = useState<Mode>(MOCK_ONLY || forced ? "recorded" : "connecting");
  const [health, setHealth] = useState<any | null>(null);
  const [episodes, setEpisodes] = useState<EpisodeRow[]>([]);
  const [pinned, setPinned] = useState<string | null>(null);
  const [state, dispatch] = useReducer(wrapped, undefined, initialState);
  const [events, setEvents] = useState<RLEvent[]>([]);
  const [agg, setAgg] = useState<Agg>({});
  const [lineage, setLineage] = useState<LineageReport | null>(null);
  const [lineageSource, setLineageSource] = useState<"live" | "recorded" | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [healthMs, setHealthMs] = useState<number | null>(null);
  const [feed, setFeed] = useState<FeedLink | null>(null);
  const [answer, setAnswer] = useState<string | null>(null);
  const lastEvent = useRef<number | null>(null);
  const arrivals = useRef<number[]>([]);
  const wantKey = want.join(",");
  const current = useRef<string | null>(null);
  const bump = useRef(0);
  const [tick, setTick] = useState(0);

  const push = useCallback((e: RLEvent) => {
    dispatch(e);
    setEvents((list) => {
      const next = list.length >= EVENT_CAP ? list.slice(list.length - EVENT_CAP + 1) : list.slice();
      next.push(e);
      return next;
    });
    arrivals.current.push(Date.now());
    lastEvent.current = Date.now();
  }, []);

  const clear = useCallback(() => {
    dispatch({ type: "__reset" });
    setEvents([]);
    setAgg({});
    arrivals.current = [];
  }, []);

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  // the backend: health, and the newest episode, every couple of seconds
  useEffect(() => {
    if (MOCK_ONLY || forced) return;
    let dead = false;
    const look = async () => {
      try {
        const t0 = performance.now();
        const [h, list] = await Promise.all([api.health(AbortSignal.timeout(3500)), api.listEpisodes()]);
        if (dead) return;
        setHealthMs(Math.round(performance.now() - t0));
        setHealth(h);
        setEpisodes(list as EpisodeRow[]);
        setAnswer(null);
        setMode("live");
      } catch (e) {
        if (dead) return;
        // only a backend that is really gone (network, timeout, 5xx) means the recorded loop; a 429 or 403 is an answer: ask again,
        // and say what it was, or the console would sit on "connecting" with no word why
        if (!isUnreachable(e)) { setAnswer(e instanceof ApiError ? `${e.status} ${e.body.replace(/\s+/g, " ").slice(0, 60)}` : e instanceof Error ? e.message : "refused"); return; }
        setAnswer(null);
        setHealth(null);
        setHealthMs(null);
        setMode("recorded");
      }
    };
    void look();
    const t = setInterval(look, 2500);
    return () => { dead = true; clearInterval(t); };
  }, [forced]);

  const episode = useMemo<EpisodeRow | null>(() => {
    if (mode !== "live") return null;
    if (pinned) return episodes.find((e) => e.id === pinned) ?? null;
    // battlefield allows one active run: while one is running that is the one on stage (a site that lost the race leaves an empty,
    // newer episode behind, which must not steal the screen). Otherwise the newest episode.
    return episodes.find((e) => e.status === "running") ?? episodes[0] ?? null; // newest first
  }, [mode, episodes, pinned]);

  // follow it: a fresh socket (catch-up from event 0) whenever the followed episode changes
  const followId = episode?.id ?? null;
  useEffect(() => {
    if (mode !== "live" || !followId) { setFeed(null); return; }
    current.current = followId;
    clear();
    return connect(followId, push, 0, setFeed);
  }, [mode, followId, clear, push]);

  // no backend: loop the recorded episode so a console can be rehearsed offline
  useEffect(() => {
    if (mode !== "recorded") return;
    let dead = false;
    let raf = 0;
    let runner: ScriptRunner | null = null;
    let last = performance.now();
    let round = 0;
    const startRound = async () => {
      const fixture = await loadFixture(recName ?? "sample");
      if (dead) return;
      clear();
      round++;
      // a named recording is the real live-red run, messy and at its own rhythm; otherwise the mock episode re-cut for the show
      const items = recName ? recordingScript(fixture, 90_000) : buildOnAct(fixture, 44_000, 5_000, `recorded_${round}`).items;
      runner = new ScriptRunner(items, (e) => push({ ...e, ts: new Date().toISOString() })); // stamped now, so "4s ago" means something
    };
    void startRound();
    const loop = (t: number) => {
      raf = requestAnimationFrame(loop);
      const dt = Math.min(100, t - last);
      last = t;
      if (!runner) return;
      runner.advance(dt);
      if (runner.done) { runner = null; setTimeout(() => { if (!dead) void startRound(); }, 4000); }
    };
    raf = requestAnimationFrame(loop);
    return () => { dead = true; cancelAnimationFrame(raf); };
  }, [mode, clear, push, recName]);

  // REST reads: what the events do not carry. Refreshed on a timer and shortly after the moments that change the books.
  const refresh = useCallback(() => { bump.current++; setTick((n) => n + 1); }, []);
  useEffect(() => {
    if (mode !== "live" || !followId || !want.length) return;
    let dead = false;
    const run = async () => {
      const keys = wantKey.split(",") as Want[];
      const out = await Promise.allSettled(keys.map((k) => FETCH[k](followId)));
      if (dead || current.current !== followId) return;
      setAgg((a) => {
        const next = { ...a };
        keys.forEach((k, i) => { const r = out[i]; if (r.status === "fulfilled") (next as any)[k] = r.value; });
        return next;
      });
    };
    void run();
    const t = setInterval(run, 4000);
    return () => { dead = true; clearInterval(t); };
  }, [mode, followId, wantKey, tick, want.length]);

  const lastType = events.length ? events[events.length - 1].type : "";
  useEffect(() => {
    if (!["day.ended", "attack.outcome", "episode.ended", "escalation.resolved", "report.posted"].includes(lastType)) return;
    const t = setTimeout(refresh, 700);
    return () => clearTimeout(t);
  }, [lastType, events.length, refresh]);

  // the lineage (playbooks) changes rarely
  useEffect(() => {
    let dead = false;
    void loadLineageReport(mode === "live").then((l) => { if (!dead) { setLineage(l.report); setLineageSource(l.source); } }).catch(() => {});
    return () => { dead = true; };
  }, [mode]);

  const rate = useMemo(() => {
    const cutoff = now - 60_000;
    arrivals.current = arrivals.current.filter((t) => t >= cutoff);
    return arrivals.current.length;
  }, [now]); // eslint-disable-line react-hooks/exhaustive-deps -- `arrivals` is a ref: the clock tick is what refreshes the count

  const pin = useCallback((id: string | null) => setPinned(id), []);

  // offline there is no episode row: describe the recording the same way so the consoles have something to show
  const shown = useMemo<EpisodeRow | null>(
    () => (mode === "recorded" ? { id: state.episodeId ?? "recorded", seed: 42, controller_mode: state.controllerMode, days: state.days, status: state.finished ? "finished" : "running", current_day: state.currentDay } : episode),
    [mode, episode, state.episodeId, state.controllerMode, state.days, state.finished, state.currentDay],
  );

  return { mode, health, episodes, episode: shown, pinned, pin, state, events, agg, lineage, lineageSource, rate, now, healthMs, lastEventAt: lastEvent.current, recording: mode === "recorded" ? recName : null, feed, answer, refresh };
}
