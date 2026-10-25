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
//
// Joining: whenever nothing of its own is on screen, the feed watches the run that is going on the battlefield (polled by
// useActiveRun; a running episode, or the current generation of a running lineage), so every window shows the current session on
// load and follows a lineage from generation to generation. A viewer (lib/role.ts) only ever watches: it never creates an episode,
// and the recording plays only when the backend is genuinely unreachable (activeRun.ts `isUnreachable`), never on a 409 or a 403.
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { api } from "../api";
import { currentEpisodeOfLineage, currentRun, isUnreachable, parseActiveRun, shouldJoin, type ActiveRun, type CurrentRun } from "./activeRun";
import { useActiveRun } from "./useActiveRun";
import { isAdmin } from "../role";
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

/** A scheme in the judge's own words: spoken or typed, in any language. */
export interface Spoken { text: string; language: string | null }

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
  /** a judge-picked attack: forced on a live backend, played out locally without one. `spoken` is the judge's own description of it:
   *  red is told in those words, and `schemeId` is the closest built-in scheme that battlefield can be forced to run */
  launchAttack: (schemeId: string, spoken?: Spoken) => Promise<void>;
  resolveEscalation: (escalationId: string, decision: "approve" | "block") => Promise<void>;
  /** subscribe to every event as it is applied */
  subscribe: (fn: (e: RLEvent) => void) => () => void;
  /** watch the run that is going whenever nothing else is on screen (on by default; the show turns it off while it plays) */
  setFollow: (on: boolean) => void;
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
  /** join the active run when idle (see the header); off while the show plays */
  const follow = useRef(true);
  /** an admin's run, act or sandbox is being set up: the poller must not attach underneath it */
  const starting = useRef(0);
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
      // a lineage's next generation is attached (and running again) by the poller as soon as it starts
      if (liveKind.current === "act" || liveKind.current === "attached") setRunning(false);
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
    } catch (e) {
      if (!isUnreachable(e)) return; // the backend answered (a 429, say): it is there, ask again later
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
   * followed until it finishes (by the poller below, which moves to each new generation's episode). Returns false when there is
   * nothing to watch.
   */
  const watch = useCallback((id: string) => {
    token.current++; // whatever was loading or stepping for what was on screen is void
    cancel.current();
    cancel.current = () => {};
    runners.current = [];
    act.current = null;
    autoBlock.current = null;
    pacer.current.clear();
    dispatch({ type: "__reset" });
    episode.current = id;
    liveKind.current = "attached";
    cancel.current = connect(id, pushLive);
    setSource("live");
    setRunning(true);
    setNote(`live · watching the run already in progress · ${id}`);
    api.schemes().then((schemes) => setCatalogs((c) => ({ ...c, schemes }))).catch(() => {});
  }, [pushLive]);

  const attach = useCallback(async (found: ActiveRun): Promise<boolean> => {
    const lineage = !found.episodeId && found.lineageId ? await api.lineage(found.lineageId).catch(() => null) : null;
    const first = found.episodeId ?? currentEpisodeOfLineage(lineage);
    if (!first) return false;
    watch(first);
    return true;
  }, [watch]);

  /** Is another run going already? (asking first spares battlefield an empty episode and the consoles a decoy) */
  const findBusy = useCallback(async (): Promise<ActiveRun | null> => {
    try { return await currentRun(api); } catch { return null; }
  }, []);

  /**
   * Every poll of the active run (useActiveRun): join it when nothing of ours is on screen. Not while the show plays, not over an
   * admin's own run, act or sandbox until it has finished, not over the recording or locally played attacks while they play.
   */
  const followActive = useCallback((found: CurrentRun | null) => {
    if (MOCK_ONLY) return;
    const join = shouldJoin(found, {
      liveKind: liveKind.current,
      episodeId: episode.current,
      finished: live.current.state.finished,
      playingLocal: !!act.current || runners.current.length > 0,
      follow: follow.current && !paused.current && starting.current === 0,
    });
    if (join && found) watch(found.episodeId);
  }, [watch]);

  useActiveRun({ enabled: !MOCK_ONLY, onPoll: followActive });

  const setFollow = useCallback((on: boolean) => { follow.current = on; }, []);

  /** The backend answered but would not start what we asked (not a network failure): say so, and play no recording instead. */
  const refused = useCallback((what: string, e: unknown) => {
    setRunning(false);
    setNote(`${what} · the backend said ${(e as { status?: unknown } | null)?.status ?? "no"}`);
  }, []);

  /**
   * Create a real episode and run its days on our own clock: one POST /step per `perDay`, escalations auto-blocked. False only
   * when the backend is unreachable (the caller then plays the recording).
   */
  const startLive = useCallback(async (which: "off" | "on", windowMs: number, autoBlockMs: number): Promise<boolean> => {
    const mine = ++token.current;
    setRunning(true);
    setSource("live");
    starting.current++;
    try {
      // someone else's run holds the battlefield: this act cannot run live without colliding, so the screen watches that run
      const busy = await findBusy();
      if (busy) {
        if (mine !== token.current) return true;
        if (!(await attach(busy))) refused("another run is active and could not be found", null);
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
            // someone else's run holds the battlefield (one active run at a time): this act cannot run live, so watch that run
            const found = mine === token.current ? parseActiveRun(e) : null;
            if (found) await attach(found);
            return; // any other failed day ends the act; the show moves on
          }
          if (mine !== token.current) return;
          await sleep(Math.max(0, perDay - (performance.now() - t0)));
        }
      })();
      return true;
    } catch (e) {
      if (isUnreachable(e)) return false; // not reachable after all: the caller falls back to the recording
      if (mine === token.current) refused("could not start a live act", e);
      return true;
    } finally {
      starting.current--;
    }
  }, [attach, findBusy, pushLive, refused]);

  const startAct = useCallback(async (which: "off" | "on", windowMs = FREE_PLAY_WINDOW_MS, holdMs = FREE_PLAY_HOLD_MS, opts: ActOptions = {}) => {
    reset();
    // a viewer's show is always the recording: only admins create episodes
    const goLive = !!opts.live && (MOCK_ONLY || isAdmin());
    publish("act", { act: which, live: goLive });
    if (goLive) {
      const ok = await startLive(which, windowMs, opts.autoBlockMs ?? holdMs);
      if (ok) return;
      setBackend(OFFLINE);
      setNote("backend unreachable · recorded run");
    }
    await startRecorded(which, windowMs, holdMs);
  }, [reset, startLive, startRecorded]);

  const run = useCallback(async (mode: ControllerMode = "enforce") => {
    if (!MOCK_ONLY && !isAdmin()) return; // viewers watch the current run; they never start one (the proxy refuses it anyway)
    reset();
    publish("run", { mode });
    setRunning(true);
    if (!MOCK_ONLY) {
      starting.current++;
      try {
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
          // the backend answered (a 409 whose run can't be found, a 403, a 4xx): no recording in place of the live run
          if (found || !isUnreachable(e)) {
            episode.current = null;
            refused(found ? "another run is active and could not be found" : "could not start a run", e);
            return;
          }
          setBackend(OFFLINE);
        }
      } finally {
        starting.current--;
      }
    }
    await startRecorded(mode === "off" ? "off" : "on", FREE_PLAY_WINDOW_MS, FREE_PLAY_HOLD_MS);
    if (!MOCK_ONLY && live.current.backend.state !== "live") setNote("backend unreachable · recorded run");
  }, [attach, findBusy, pushLive, refused, reset, startRecorded]);

  const setPaused = useCallback((p: boolean) => { paused.current = p; }, []);
  const clearRuns = useCallback(() => setRuns([]), []);

  // ---- what a judge can do -----------------------------------------------------------------------------------------

  const setController = useCallback(async (mode: ControllerMode) => {
    if (!MOCK_ONLY && !isAdmin()) return; // only admins change the sim
    live.current.mode = mode;
    publish("controller", { mode, route: "user" });
    if (live.current.source === "live" && episode.current) { await api.setController(episode.current, mode); return; }
    const s = live.current.state;
    emit({ id: Date.now(), ts: new Date().toISOString(), episode_id: s.episodeId ?? "local", day: s.currentDay, type: "controller.changed", agent: "human", payload: { from: s.controllerMode, to: mode }, replay: true });
  }, [emit]);

  /** A live sandbox: a paused episode the judge drives. Each attack is forced for red's next turn and the day is stepped at once. */
  const tellRed = useCallback(async (ep: string, schemeId: string, spoken?: Spoken) => {
    if (!spoken) return;
    await api.sendInput(ep, "red", { kind: "custom_fraud_scheme", text: spoken.text, language: spoken.language, closest_built_in: schemeId });
  }, []);

  const sandboxAttack = useCallback(async (schemeId: string, spoken?: Spoken) => {
    setRunning(true);
    starting.current++;
    try {
      if (liveKind.current !== "sandbox" || !episode.current || live.current.state.finished) {
        const busy = liveKind.current === "attached" ? null : await findBusy();
        if (busy && (await attach(busy))) {
          await tellRed(episode.current!, schemeId, spoken);
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
      await tellRed(episode.current!, schemeId, spoken);
      await api.forceAttack(episode.current!, schemeId);
      try { await api.step(episode.current!); } catch (e) {
        const found = parseActiveRun(e);
        if (!found || !(await attach(found))) throw e;
        // the judge's attack goes into the run that is going: red picks it up on its next turn
        await tellRed(episode.current!, schemeId, spoken);
        await api.forceAttack(episode.current!, schemeId);
        setNote(`attack queued on the run in progress: ${schemeId} · red picks it up on its next turn`);
      }
    } finally {
      starting.current--;
      setRunning(false);
    }
  }, [attach, findBusy, pushLive, reset, tellRed]);

  const launchAttack = useCallback(async (schemeId: string, spoken?: Spoken) => {
    if (!MOCK_ONLY && !isAdmin()) return; // only admins change the sim
    const backendUp = live.current.backend.state === "live";
    const builtIn = RED_SCHEMES.find((s) => s.key === schemeId)?.name ?? schemeId;
    // the other laptops see what was said (the relay keeps strings short), and which built-in scheme it was matched to
    publish("launch", { scheme: schemeId, name: spoken ? spoken.text.slice(0, 120) : builtIn, via: spoken ? "voice" : "button", lang: spoken?.language ?? "", mode: live.current.state.controllerMode, route: backendUp ? "backend" : "local" });
    // a continuous live run: the scheme is queued for red's next turn
    if (live.current.source === "live" && episode.current && (liveKind.current === "run" || liveKind.current === "attached")) {
      await tellRed(episode.current, schemeId, spoken);
      await api.forceAttack(episode.current, schemeId);
      setNote(spoken ? `red has your words · queued the closest built-in scheme: ${builtIn} · red picks it up on its next turn` : `attack queued: ${schemeId} · red picks it up on its next turn`);
      return;
    }
    if (backendUp && liveKind.current !== "act") {
      try {
        await sandboxAttack(schemeId, spoken);
        if (spoken) setNote((n) => `${n} · red has your words, running the closest built-in scheme: ${builtIn}`);
        return;
      } catch (e) {
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
    if (spoken) setNote(`offline · playing the closest built-in scheme to what you said: ${builtIn}`);
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
  }, [newRunner, reset, sandboxAttack, tellRed]);

  const resolveEscalation = useCallback(async (escalationId: string, decision: "approve" | "block") => {
    const esc = live.current.state.escalations[escalationId];
    if (esc && esc.status !== "open") return;
    if (!MOCK_ONLY && !isAdmin()) return; // a human decision, but an admin's
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
    () => ({ state, source, note, catalogs, running, backend, probe, runs, run, startAct, stop, reset, clearRuns, setPaused, setController, launchAttack, resolveEscalation, subscribe, setFollow }),
    [state, source, note, catalogs, running, backend, probe, runs, run, startAct, stop, reset, clearRuns, setPaused, setController, launchAttack, resolveEscalation, subscribe, setFollow],
  );
}

/** A controller-off run that never happened, for the compare card when only the controller-on run exists. */
export function projectedOff(fixture: RLEvent[]): Score | null {
  return finalScoreOf(projectBaseline(fixture));
}
