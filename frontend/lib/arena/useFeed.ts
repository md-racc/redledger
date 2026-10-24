"use client";
// Episode feed for the arena: the same reducer as the rest of the frontend, fed by (in order of preference)
//   live  - POST /episodes + WebSocket through the /api/bf proxy
//   mock  - public/mocks/sample.jsonl, paced for the arena (NEXT_PUBLIC_MOCK=true, or the backend is unreachable)
// and fanned out to listeners (the Director) event by event. Owner: Dev R.
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { api } from "../api";
import { loadFixture } from "../mock";
import { initialState, reduce } from "../reducer";
import type { ControllerMode, RLEvent, UIState } from "../types";
import type { FeedSource } from "./store";
import { connect } from "../ws";
import type { Catalogs } from "./details";

const MOCK_ONLY = process.env.NEXT_PUBLIC_MOCK === "true";

type Action = RLEvent | { type: "__reset" };
const wrapped = (s: UIState, a: Action): UIState => (a.type === "__reset" ? initialState() : reduce(s, a as RLEvent));

/** Replay pacing: quiet bookkeeping events fly by, the story beats get room to play out in 3D. */
export function paceMs(e: RLEvent): number {
  switch (e.type) {
    case "day.started": return 3200;
    case "attack.launched": return 900;
    case "attack.outcome": return 6500;
    case "gate.verdict": return (e.payload as { verdict?: string }).verdict === "allow" ? 140 : 900;
    case "flag.raised": return 900;
    case "episode.ended": return 400;
    default: return 90;
  }
}

export interface Feed {
  state: UIState;
  source: FeedSource;
  /** one-line status for the HUD */
  note: string;
  catalogs: Catalogs;
  running: boolean;
  /** start (or restart) an episode: live if a battlefield answers, else the recorded sample */
  run: (mode?: ControllerMode) => Promise<void>;
  stop: () => void;
  setController: (mode: ControllerMode) => Promise<void>;
  /** subscribe to every event as it is applied */
  subscribe: (fn: (e: RLEvent) => void) => () => void;
}

export function useFeed(): Feed {
  const [state, dispatch] = useReducer(wrapped, undefined, initialState);
  const [source, setSource] = useState<FeedSource>("idle");
  const [note, setNote] = useState(MOCK_ONLY ? "mock mode · recorded episode" : "ready");
  const [catalogs, setCatalogs] = useState<Catalogs>({});
  const [running, setRunning] = useState(false);
  const listeners = useRef(new Set<(e: RLEvent) => void>());
  const cancel = useRef<() => void>(() => {});
  const episode = useRef<string | null>(null);

  const emit = useCallback((e: RLEvent) => {
    dispatch(e);
    listeners.current.forEach((fn) => fn(e));
  }, []);

  const stop = useCallback(() => {
    cancel.current();
    cancel.current = () => {};
    setRunning(false);
  }, []);

  useEffect(() => stop, [stop]);

  const playFixture = useCallback(async () => {
    const events = await loadFixture();
    let i = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let dead = false;
    const tick = () => {
      if (dead) return;
      if (i >= events.length) { setRunning(false); setNote("recorded episode finished"); return; }
      const e = events[i++];
      emit({ ...e, replay: true });
      timer = setTimeout(tick, paceMs(e));
    };
    cancel.current = () => { dead = true; clearTimeout(timer); };
    tick();
  }, [emit]);

  const run = useCallback(async (mode: ControllerMode = "enforce") => {
    stop();
    dispatch({ type: "__reset" });
    setRunning(true);
    if (!MOCK_ONLY) {
      try {
        const ep = await api.createEpisode({ controller_mode: mode, seed: 42, days: 5 });
        episode.current = ep.id;
        const off = connect(ep.id, emit);
        cancel.current = off;
        await api.start(ep.id);
        setSource("live");
        setNote(`live · ${ep.id}`);
        api.schemes().then((schemes) => setCatalogs((c) => ({ ...c, schemes }))).catch(() => {});
        api.fe.vendors(ep.id, "spend").then((vendors) => setCatalogs((c) => ({ ...c, vendors: vendors.slice(0, 12) }))).catch(() => {});
        return;
      } catch {
        cancel.current();
        setNote("backend offline · replaying the recorded sample episode");
      }
    }
    setSource("mock");
    if (MOCK_ONLY) setNote("mock mode · recorded episode");
    await playFixture();
  }, [emit, playFixture, stop]);

  const setController = useCallback(async (mode: ControllerMode) => {
    if (source === "live" && episode.current) await api.setController(episode.current, mode);
    else emit({ id: Date.now(), ts: new Date().toISOString(), episode_id: state.episodeId ?? "local", day: state.currentDay, type: "controller.changed", agent: "human", payload: { from: state.controllerMode, to: mode }, replay: true });
  }, [emit, source, state.controllerMode, state.currentDay, state.episodeId]);

  const subscribe = useCallback((fn: (e: RLEvent) => void) => {
    listeners.current.add(fn);
    return () => { listeners.current.delete(fn); };
  }, []);

  return useMemo(() => ({ state, source, note, catalogs, running, run, stop, setController, subscribe }), [state, source, note, catalogs, running, run, stop, setController, subscribe]);
}
