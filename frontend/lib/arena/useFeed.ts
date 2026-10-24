"use client";
// Episode feed for the arena. The same reducer as the rest of the frontend, fed by the backend whenever there is one:
//
//   live      POST /episodes + WebSocket through the /api/bf proxy; days are run with POST /episodes/{id}/step on our own
//             clock, so a 90-second show can drive a real battlefield, and live events pass through a pacer so a day's
//             burst stays readable
//   recorded  the recorded episode (public/mocks/sample.jsonl) re-cut by lib/arena/showScripts.ts and played on our own
//             clock, when there is no backend (NEXT_PUBLIC_MOCK=true, unreachable, or not configured)
//
// and fanned out to listeners (the Director) event by event. It also owns what a judge can do to a running episode:
// launch an attack (a forced scheme on a live backend, played locally without one), flip the controller, decide an
// escalation. Owner: Dev R.
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { api } from "../api";
import { currentEpisodeOfLineage, lineageIsLive, parseActiveRun, type ActiveRun } from "./activeRun";
import { loadFixture } from "../mock";
import { initialState, reduce } from "../reducer";
import type { ControllerMode, RLEvent, Score, UIState } from "../types";
import type { FeedSource } from "./store";
import { connect } from "../ws";
import type { Catalogs } from "./details";
import { localAttack } from "./localAttack";
import { Pacer } from "./pacer";
import { RED_SCHEMES } from "./roster";
import { publish } from "../sync/client";
import { ScriptRunner } from "./script";
import { buildOffAct, buildOnAct, decisionEvent, finalScoreOf, projectBaseline } from "./showScripts";

const MOCK_ONLY = process.env.NEXT_PUBLIC_MOCK === "true";

const start = (): UIState => ({ ...initialState(), controllerMode: "enforce" });
type Action = RLEvent | { type: "__reset" };
const wrapped = (s: UIState, a: Action): UIState => (a.type === "__reset" ? start() : reduce(s, a as RLEvent));

/** How long a scripted escalation waits for a human before it times out into a block (the live backend waits 90 s). */
const FREE_PLAY_HOLD_MS = 14_000;
/** A recorded episode in free play: about half a minute, the story beats given room. */
const FREE_PLAY_WINDOW_MS = 34_000;
/** The seed the recorded episode and the show's live episodes share, so off vs on is a like-for-like comparison. */
const SHOW_SEED = 42;
const SHOW_DAYS = 4;

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

/** One finished run, kept for the compare card. */
export interface RunRecord {
  episodeId: string;
  mode: ControllerMode;
  score: Score;
  /** a controller-off run that never happened: the same attacks with nothing gating them */
  projected: boolean;
}

export interface AgentHealth { ok: boolean; model?: string; dry_run?: boolean }

export interface Backend {
  /** `checking` until the first probe answers */
  state: "checking" | "live" | "offline";
  agents: Record<string, AgentHealth> | null;
  /** every agent is keyless (DRY_RUN): episodes are free and fast, so the show can run on them */
  keyless: boolean;
}

export interface ActOptions {
  /** run on the battlefield (create + step a real episode) instead of the recording */
  live?: boolean;
  /** live acts: block an escalation nobody decided after this long, so the show never waits on the 90 s timeout */
  autoBlockMs?: number;
}

export interface Feed {
  state: UIState;
  source: FeedSource;
  /** one-line status for the HUD */
  note: string;
  catalogs: Catalogs;
  running: boolean;
  backend: Backend;
  probe: () => Promise<void>;
  /** finished runs, oldest first */
  runs: RunRecord[];
  /** start (or restart) an episode: live if a battlefield answers, else the recorded run */
  run: (mode?: ControllerMode) => Promise<void>;
  /** play one act of the show (or of free play) */
  startAct: (act: "off" | "on", windowMs?: number, holdMs?: number, opts?: ActOptions) => Promise<void>;
  stop: () => void;
  /** stop everything and empty the scoreboard (the run history stays) */
  reset: () => void;
  clearRuns: () => void;
  setPaused: (p: boolean) => void;
  setController: (mode: ControllerMode) => Promise<void>;
  /** a judge-picked attack: forced on a live backend, played out locally without one */
  launchAttack: (schemeId: string) => Promise<void>;
  resolveEscalation: (escalationId: string, decision: "approve" | "block") => Promise<void>;
  /** subscribe to every event as it is applied */
  subscribe: (fn: (e: RLEvent) => void) => () => void;
}

const OFFLINE: Backend = { state: "offline", agents: null, keyless: false };

export function useFeed(): Feed {
  const [state, dispatch] = useReducer(wrapped, undefined, start);
  const [source, setSource] = useState<FeedSource>("idle");
  const [note, setNote] = useState(MOCK_ONLY ? "mock mode · recorded episode" : "checking the backend…");
  const [catalogs, setCatalogs] = useState<Catalogs>({});
  const [running, setRunning] = useState(false);
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [backend, setBackend] = useState<Backend>(MOCK_ONLY ? OFFLINE : { state: "checking", agents: null, keyless: false });
  const listeners = useRef(new Set<(e: RLEvent) => void>());
  const cancel = useRef<() => void>(() => {});
  const episode = useRef<string | null>(null);
  const runners = useRef<ScriptRunner[]>([]);
  const act = useRef<ScriptRunner | null>(null);
  const pacer = useRef(new Pacer());
  const paused = useRef(false);
  const seq = useRef(0);
  const token = useRef(0);
  /** what a live episode is: a continuous run, a show act, a sandbox the judge steps by hand, or someone else's run we are watching */
  const liveKind = useRef<"run" | "act" | "sandbox" | "attached" | null>(null);
  const followTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const autoBlock = useRef<number | null>(null);
  const live = useRef({ state, source, mode: "enforce" as ControllerMode, backend });
  live.current.state = state;
  live.current.source = source;
  live.current.backend = backend;

  const resolveRef = useRef<(id: string, d: "approve" | "block") => Promise<void>>(async () => {});

  const emit = useCallback((e: RLEvent) => {
    if (e.type === "episode.started") live.current.mode = (e.payload as { controller_mode: ControllerMode }).controller_mode;
    if (e.type === "controller.changed") live.current.mode = (e.payload as { to: ControllerMode }).to;
    if (e.type === "episode.ended") {
      const score = (e.payload as { final_score?: Score }).final_score;
      if (score) setRuns((r) => [...r.filter((x) => x.episodeId !== e.episode_id), { episodeId: e.episode_id, mode: live.current.mode, score, projected: false }].slice(-6));
      if (liveKind.current === "act" || (liveKind.current === "attached" && !followTimer.current)) setRunning(false);
    }
    if (e.type === "escalation.opened" && autoBlock.current !== null) {
      const id = (e.payload as { escalation_id: string }).escalation_id;
      setTimeout(() => { void resolveRef.current(id, "block"); }, autoBlock.current);
    }
    dispatch(e);
    listeners.current.forEach((fn) => fn(e));
  }, []);

  const getScore = useCallback((): Score => live.current.state.score, []);
  const newRunner = useCallback((items: ConstructorParameters<typeof ScriptRunner>[0]) => new ScriptRunner(items, emit, { decisions: {}, getScore }), [emit, getScore]);
  const pushLive = useCallback((e: RLEvent) => pacer.current.push(e), []);

  const stop = useCallback(() => {
    if (followTimer.current) { clearInterval(followTimer.current); followTimer.current = null; }
    cancel.current();
    cancel.current = () => {};
    runners.current = [];
    act.current = null;
    pacer.current.clear();
    liveKind.current = null;
    autoBlock.current = null;
    setRunning(false);
  }, []);

  const reset = useCallback(() => {
    token.current++; // anything still loading or stepping for the previous act is void
    stop();
    dispatch({ type: "__reset" });
    episode.current = null;
  }, [stop]);

  useEffect(() => stop, [stop]);

  // one clock for everything that is playing: scripts (the recorded act, attacks launched on top of it) and the live pacer
  useEffect(() => {
    let raf = 0;
    let last = performance.now();
    const loop = (now: number) => {
      raf = requestAnimationFrame(loop);
      const dt = Math.min(100, now - last);
      last = now;
      if (paused.current) return;
      pacer.current.advance(dt, emit);
      if (!runners.current.length) return;
      for (const r of runners.current) r.advance(dt);
      runners.current = runners.current.filter((r) => !r.done);
      if (act.current?.done) { act.current = null; setRunning(false); }
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [emit]);

  // ---- the backend -------------------------------------------------------------------------------------------------

  const probe = useCallback(async () => {
    if (MOCK_ONLY) return;
    try {
      const h = await api.health(AbortSignal.timeout(3500));
      const agents = (h?.agents ?? {}) as Record<string, AgentHealth>;
      const list = Object.values(agents);
      const keyless = list.length > 0 && list.every((a) => a?.ok !== false && a?.dry_run === true);
      setBackend({ state: "live", agents, keyless });
      setNote((n) => (n.startsWith("checking") || n.startsWith("backend unreachable") ? `backend live${keyless ? " · keyless agents" : ""}` : n));
    } catch {
      setBackend(OFFLINE);
      setNote((n) => (n.startsWith("checking") || n.startsWith("backend live") ? "backend offline · recorded run" : n));
    }
  }, []);

  useEffect(() => {
    void probe();
    // keep looking: a backend that comes up (or goes away) while the page is open should be noticed
    const t = setInterval(() => { if (!paused.current && liveKind.current === null) void probe(); }, 12_000);
    return () => clearInterval(t);
  }, [probe]);

  // ---- acts and runs -----------------------------------------------------------------------------------------------

  const startRecorded = useCallback(async (which: "off" | "on", windowMs: number, holdMs: number) => {
    const mine = ++token.current;
    setRunning(true);
    setSource("mock");
    const fixture = await loadFixture();
    if (mine !== token.current) return;
    const built = which === "off" ? buildOffAct(fixture, windowMs) : buildOnAct(fixture, windowMs, holdMs);
    const r = newRunner(built.items);
    act.current = r;
    runners.current = [r];
    setNote(which === "off" ? "recorded run · controller off (projected)" : "recorded run · controller on");
  }, [newRunner]);

  /**
   * Battlefield allows one active run at a time. When it says another run is active (409), watch that one: the operator runs the
   * live episode or lineage and the screen simply shows it. A lineage moves from one generation's episode to the next, so it is
   * followed until it finishes. Returns false when there is nothing to watch (the caller falls back to the recording).
   */
  const attach = useCallback(async (found: ActiveRun): Promise<boolean> => {
    const lineage = found.lineageId ? await api.lineage(found.lineageId).catch(() => null) : null;
    const first = found.episodeId ?? currentEpisodeOfLineage(lineage);
    if (!first) return false;
    const mine = ++token.current;
    const watch = (id: string) => {
      cancel.current();
      pacer.current.clear();
      dispatch({ type: "__reset" });
      episode.current = id;
      liveKind.current = "attached";
      cancel.current = connect(id, pushLive);
      setSource("live");
      setNote(`live · watching the run already in progress · ${id}`);
      api.schemes().then((schemes) => setCatalogs((c) => ({ ...c, schemes }))).catch(() => {});
    };
    watch(first);
    setRunning(true);
    if (found.lineageId) {
      followTimer.current = setInterval(() => {
        if (mine !== token.current) return;
        void api.lineage(found.lineageId!).then((l) => {
          if (mine !== token.current) return;
          const id = currentEpisodeOfLineage(l);
          if (id && id !== episode.current) watch(id);
          if (!lineageIsLive(l) && followTimer.current) { clearInterval(followTimer.current); followTimer.current = null; setRunning(false); }
        }).catch(() => {});
      }, 3000);
    }
    return true;
  }, [pushLive]);

  /** Is another run going already? (asking first spares battlefield an empty episode and the consoles a decoy) */
  const findBusy = useCallback(async (): Promise<ActiveRun | null> => {
    try {
      const list = await api.listEpisodes();
      const busy = list.find((e) => e.status === "running" && !String(e.id).startsWith("replay_"));
      return busy ? { episodeId: busy.id, lineageId: busy.lineage_id ?? null } : null;
    } catch { return null; }
  }, []);

  /** Create a real episode and run its days on our own clock: one POST /step per `perDay`, escalations auto-blocked. */
  const startLive = useCallback(async (which: "off" | "on", windowMs: number, autoBlockMs: number): Promise<boolean> => {
    const mine = ++token.current;
    setRunning(true);
    setSource("live");
    try {
      // someone else's run holds the battlefield: this act cannot run live, so play it from the recording without creating a decoy
      if (await findBusy()) {
        if (mine !== token.current) return true;
        await startRecorded(which, windowMs, autoBlockMs);
        setNote((n) => `${n} · the backend is busy with another run`);
        return true;
      }
      const mode: ControllerMode = which === "off" ? "off" : "enforce";
      const ep = await api.createEpisode({ controller_mode: mode, seed: SHOW_SEED, days: SHOW_DAYS });
      if (mine !== token.current) return true;
      episode.current = ep.id;
      liveKind.current = "act";
      autoBlock.current = autoBlockMs;
      cancel.current = connect(ep.id, pushLive);
      setNote(`live · ${ep.id} · controller ${mode}`);
      api.schemes().then((schemes) => setCatalogs((c) => ({ ...c, schemes }))).catch(() => {});
      const perDay = Math.max(2800, windowMs / SHOW_DAYS);
      void (async () => {
        for (let d = 0; d < SHOW_DAYS; d++) {
          if (mine !== token.current) return;
          const t0 = performance.now();
          try { await api.step(ep.id); } catch (e) {
            // someone else's run holds the battlefield (one active run at a time): this act cannot run live, so play it from the recording
            if (mine === token.current && parseActiveRun(e)) {
              cancel.current();
              cancel.current = () => {};
              pacer.current.clear();
              dispatch({ type: "__reset" });
              liveKind.current = null;
              autoBlock.current = null;
              episode.current = null;
              await startRecorded(which, windowMs, autoBlockMs);
              setNote((n) => `${n} · the backend is busy with another run`);
            }
            return; // any other failed day ends the act; the show moves on
          }
          if (mine !== token.current) return;
          await sleep(Math.max(0, perDay - (performance.now() - t0)));
        }
      })();
      return true;
    } catch {
      return false; // not reachable after all: the caller falls back to the recording
    }
  }, [findBusy, pushLive, startRecorded]);

  const startAct = useCallback(async (which: "off" | "on", windowMs = FREE_PLAY_WINDOW_MS, holdMs = FREE_PLAY_HOLD_MS, opts: ActOptions = {}) => {
    reset();
    publish("act", { act: which, live: !!opts.live });
    if (opts.live) {
      const ok = await startLive(which, windowMs, opts.autoBlockMs ?? holdMs);
      if (ok) return;
      setBackend(OFFLINE);
      setNote("backend unreachable · recorded run");
    }
    await startRecorded(which, windowMs, holdMs);
  }, [reset, startLive, startRecorded]);

  const run = useCallback(async (mode: ControllerMode = "enforce") => {
    reset();
    publish("run", { mode });
    setRunning(true);
    if (!MOCK_ONLY) {
      const busy = await findBusy();
      if (busy && (await attach(busy))) return; // another run is going: watch it instead of starting one
      try {
        const ep = await api.createEpisode({ controller_mode: mode, seed: SHOW_SEED, days: 5 });
        episode.current = ep.id;
        liveKind.current = "run";
        cancel.current = connect(ep.id, pushLive);
        await api.start(ep.id);
        setSource("live");
        setNote(`live · ${ep.id}`);
        api.schemes().then((schemes) => setCatalogs((c) => ({ ...c, schemes }))).catch(() => {});
        api.fe.vendors(ep.id, "spend").then((vendors) => setCatalogs((c) => ({ ...c, vendors: vendors.slice(0, 12) }))).catch(() => {});
        return;
      } catch (e) {
        cancel.current();
        liveKind.current = null;
        const found = parseActiveRun(e);
        if (found && (await attach(found))) return; // another run is going: watch it
        if (!found) setBackend(OFFLINE);
        else setNote("another run is active and could not be found · recorded run");
      }
    }
    await startRecorded(mode === "off" ? "off" : "on", FREE_PLAY_WINDOW_MS, FREE_PLAY_HOLD_MS);
    if (!MOCK_ONLY && live.current.backend.state !== "live") setNote("backend unreachable · recorded run");
  }, [attach, findBusy, pushLive, reset, startRecorded]);

  const setPaused = useCallback((p: boolean) => { paused.current = p; }, []);
  const clearRuns = useCallback(() => setRuns([]), []);

  // ---- what a judge can do -----------------------------------------------------------------------------------------

  const setController = useCallback(async (mode: ControllerMode) => {
    live.current.mode = mode;
    publish("controller", { mode, route: "user" });
    if (live.current.source === "live" && episode.current) { await api.setController(episode.current, mode); return; }
    const s = live.current.state;
    emit({ id: Date.now(), ts: new Date().toISOString(), episode_id: s.episodeId ?? "local", day: s.currentDay, type: "controller.changed", agent: "human", payload: { from: s.controllerMode, to: mode }, replay: true });
  }, [emit]);

  /** A live sandbox: a paused episode the judge drives. Each attack is forced for red's next turn and the day is stepped at once. */
  const sandboxAttack = useCallback(async (schemeId: string) => {
    setRunning(true);
    try {
      if (liveKind.current !== "sandbox" || !episode.current || live.current.state.finished) {
        const busy = liveKind.current === "attached" ? null : await findBusy();
        if (busy && (await attach(busy))) {
          await api.forceAttack(episode.current!, schemeId);
          setNote(`attack queued on the run in progress: ${schemeId} · red picks it up on its next turn`);
          return;
        }
        reset();
        const ep = await api.createEpisode({ controller_mode: live.current.mode, seed: SHOW_SEED, days: 30 });
        episode.current = ep.id;
        liveKind.current = "sandbox";
        cancel.current = connect(ep.id, pushLive);
        setSource("live");
        setNote(`live sandbox · ${ep.id} · every attack steps one business day`);
        api.schemes().then((schemes) => setCatalogs((c) => ({ ...c, schemes }))).catch(() => {});
      }
      await api.forceAttack(episode.current!, schemeId);
      try { await api.step(episode.current!); } catch (e) {
        const found = parseActiveRun(e);
        if (!found || !(await attach(found))) throw e;
        // the judge's attack goes into the run that is going: red picks it up on its next turn
        await api.forceAttack(episode.current!, schemeId);
        setNote(`attack queued on the run in progress: ${schemeId} · red picks it up on its next turn`);
      }
    } finally {
      setRunning(false);
    }
  }, [attach, findBusy, pushLive, reset]);

  const launchAttack = useCallback(async (schemeId: string) => {
    const backendUp = live.current.backend.state === "live";
    publish("launch", { scheme: schemeId, name: RED_SCHEMES.find((s) => s.key === schemeId)?.name ?? schemeId, mode: live.current.state.controllerMode, route: backendUp ? "backend" : "local" });
    // a continuous live run: the scheme is queued for red's next turn
    if (live.current.source === "live" && episode.current && (liveKind.current === "run" || liveKind.current === "attached")) {
      await api.forceAttack(episode.current, schemeId);
      setNote(`attack queued: ${schemeId} · red picks it up on its next turn`);
      return;
    }
    if (backendUp && liveKind.current !== "act") {
      try { await sandboxAttack(schemeId); return; } catch (e) {
        if (!(e instanceof TypeError)) throw e; // a rejected call is the backend's answer: show it; a network failure falls through to local play
        setBackend(OFFLINE);
        setNote("backend unreachable · attacks play out locally");
      }
    }
    // no backend: the attack plays out from the mock agents' rules
    const s = live.current.state;
    const fresh = !s.episodeId || s.finished || liveKind.current === "sandbox";
    if (fresh) reset();
    setSource((x) => (x === "idle" || x === "live" ? "mock" : x));
    if (fresh) setNote("sandbox · attacks you launch play out locally");
    const mode = fresh ? live.current.mode : s.controllerMode;
    const items = [];
    const id = `sandbox_${Date.now()}`;
    if (fresh) {
      items.push(
        { at: 0, e: { id: Date.now(), ts: new Date().toISOString(), episode_id: id, day: 0, type: "episode.started", agent: "battlefield" as const, payload: { controller_mode: mode, days: 5, seed: SHOW_SEED }, replay: true } },
        { at: 0, e: { id: Date.now() + 1, ts: new Date().toISOString(), episode_id: id, day: 0, type: "day.started", agent: "battlefield" as const, payload: { day: 0, legit_injected: { invoices: 6, purchase_orders: 4, expenses: 2, bank_lines: 1 } }, replay: true } },
      );
    }
    const ep = fresh ? id : s.episodeId!;
    const a = localAttack({ scheme: schemeId, mode, day: fresh ? 0 : s.currentDay, episodeId: ep, seq: ++seq.current, holdMs: FREE_PLAY_HOLD_MS });
    const shift = fresh ? 300 : 0;
    const r = newRunner([...items, ...a.items.map((it) => ({ ...it, at: it.at + shift }))]);
    runners.current = [...runners.current, r];
  }, [newRunner, reset, sandboxAttack]);

  const resolveEscalation = useCallback(async (escalationId: string, decision: "approve" | "block") => {
    const esc = live.current.state.escalations[escalationId];
    if (esc && esc.status !== "open") return;
    publish("decision", { escalation_id: escalationId, decision, action: esc?.action ?? null, amount: esc?.amount ?? null });
    if (live.current.source === "live") { await api.resolve(escalationId, decision).catch(() => {}); return; }
    for (const r of runners.current) r.ctx.decisions[escalationId] = decision;
    emit(decisionEvent({ escalation_id: escalationId, episode_id: live.current.state.episodeId ?? "local", day: live.current.state.currentDay }, decision, "judge"));
  }, [emit]);
  resolveRef.current = resolveEscalation;

  const subscribe = useCallback((fn: (e: RLEvent) => void) => {
    listeners.current.add(fn);
    return () => { listeners.current.delete(fn); };
  }, []);

  return useMemo(
    () => ({ state, source, note, catalogs, running, backend, probe, runs, run, startAct, stop, reset, clearRuns, setPaused, setController, launchAttack, resolveEscalation, subscribe }),
    [state, source, note, catalogs, running, backend, probe, runs, run, startAct, stop, reset, clearRuns, setPaused, setController, launchAttack, resolveEscalation, subscribe],
  );
}

/** A controller-off run that never happened, for the compare card when only the controller-on run exists. */
export function projectedOff(fixture: RLEvent[]): Score | null {
  return finalScoreOf(projectBaseline(fixture));
}
