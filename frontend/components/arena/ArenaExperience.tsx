"use client";
// redledger: the cinematic 3D front door. Composes the R3F scene, the scroll tour and the HTML overlays, and wires
// the episode feed (live battlefield, or the recorded run) into the arena. A 90-second show walks the whole site.
//
// Host integration:
//   <ArenaExperience agentDetails={{ "red:ghost_vendor": { story: "...", fields: { targeted: 4920 } } }} />
//   window.redledger.converge() / .disperse() / .select(id) / .run(mode) / .show() / .pitch()
//   ?show=1 starts the show on load; ?pitch=1 starts pitch mode (a live episode, components/arena/usePitch.ts)
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { AgentDetailOverrides } from "@/lib/arena/types";
import type { ArenaSim } from "@/lib/arena/sim";
import { cinema } from "@/lib/arena/cinema";
import { compareSides } from "@/lib/arena/compare";
import { focus } from "@/lib/arena/focus";
import { useArena } from "@/lib/arena/store";
import { tallyDays } from "@/lib/arena/ledgerStats";
import { useFeed } from "@/lib/arena/useFeed";
import Scene from "./Scene";
import { isAdmin } from "@/lib/role";
import { publish, setClientRole } from "@/lib/sync/client";
import { ROSTER_BY_ID } from "@/lib/arena/roster";
import { useShow } from "./useShow";
import { usePitch } from "./usePitch";
import { pitchQuery } from "@/lib/arena/pitch";
import { PitchOverlay } from "./overlays/PitchOverlay";
import { AgentModal } from "./overlays/AgentModal";
import { Chapters } from "./overlays/Chapters";
import { CompareCard } from "./overlays/CompareCard";
import { EvolutionCard } from "./overlays/EvolutionCard";
import { Hud } from "./overlays/Hud";
import { LabelLayer } from "./overlays/LabelLayer";
import { LendersCard } from "./overlays/LendersCard";
import { ReportCard } from "./overlays/ReportCard";
import { Loader } from "./overlays/Loader";
import { PopLayer } from "./overlays/PopLayer";
import { ShowBar } from "./overlays/ShowBar";
import { TitleOverlay } from "./overlays/TitleOverlay";

interface Props {
  agentDetails?: AgentDetailOverrides;
  /** send the agents in a moment after the visitor lands in the arena (default true) */
  autoConverge?: boolean;
}

/** long enough that each chapter's reading zone is a couple of wheel flicks (see lib/arena/pacing.ts) */
const SCROLL_VH = 780;

export default function ArenaExperience({ agentDetails, autoConverge = true }: Props) {
  const feed = useFeed();
  const show = useShow(feed);
  const showStop = useRef(show.stop);
  showStop.current = show.stop;
  const showStatus = useRef(show.status);
  showStatus.current = show.status;
  // pitch mode and the show never run together: starting one leaves the other
  const pitch = usePitch(feed, { onStart: () => { if (showStatus.current === "playing" || showStatus.current === "paused") showStop.current(); } });
  const inPitchIntro = pitch.phase === "intro";
  const stage = useArena((s) => s.stage);
  const modelState = useArena((s) => s.modelState);
  const panel = useArena((s) => s.panel);
  const setPanel = useArena((s) => s.setPanel);
  const [progress, setProgress] = useState(0);
  const [sim, setSim] = useState<ArenaSim | null>(null);
  const boot = useRef(0);
  const tallies = useMemo(() => tallyDays(feed.state), [feed.state]);
  const sides = useMemo(() => compareSides(feed.runs, feed.state), [feed.runs, feed.state]);
  const inShow = show.status === "playing" || show.status === "paused";

  const onProgress = useCallback((p: { progress: number }) => setProgress(p.progress), []);
  const onSim = useCallback((s: ArenaSim) => setSim(s), []);

  // the controller mode is mirrored into the store (the HUD and anything else that wants it read it from there)
  useEffect(() => { useArena.getState().setControllerMode(feed.state.controllerMode); }, [feed.state.controllerMode]);

  // loading → intro once the model and sim exist (with a floor so the title card is seen, and a ceiling so it never hangs)
  useEffect(() => {
    if (stage !== "loading") return;
    if (!boot.current) boot.current = performance.now();
    const ready = !!sim && modelState !== "pending";
    const wait = ready ? Math.max(0, 1800 - (performance.now() - boot.current)) : 35000;
    const t = setTimeout(() => useArena.getState().setStage("intro"), wait);
    return () => clearTimeout(t);
  }, [stage, sim, modelState]);

  // ?show=1: the show starts as soon as the flight does (?pitch=1: pitch mode does)
  const autostart = useRef(false);
  useEffect(() => {
    if (stage !== "intro" || autostart.current) return;
    if (pitchQuery(window.location.search).on) { autostart.current = true; pitch.start(); return; }
    const q = new URLSearchParams(window.location.search).get("show");
    if (q === "1" || q === "live" || q === "recorded") { autostart.current = true; show.start(); }
  }, [stage, show, pitch]);

  // the show started while pitch mode was on: pitch mode steps aside
  const pitchStop = pitch.stop;
  const pitchOn = pitch.phase !== "off";
  useEffect(() => { if (pitchOn && (show.status === "playing" || show.status === "paused")) pitchStop(); }, [show.status, pitchOn, pitchStop]);

  // the page does not scroll while loading or flying...
  useEffect(() => {
    const lock = stage === "loading" || stage === "intro";
    document.documentElement.style.overflow = lock ? "hidden" : "";
    document.body.style.overflow = lock ? "hidden" : "";
    return () => { document.documentElement.style.overflow = ""; document.body.style.overflow = ""; };
  }, [stage]);

  // ...nor while the show is driving it: the visitor's wheel, touch and paging keys are swallowed (no overflow:hidden, which
  // would drop the scrollbar and shift the layout under the show)
  const lockScroll = inShow || inPitchIntro;
  useEffect(() => {
    if (!lockScroll) return;
    const stopEvent = (e: Event) => e.preventDefault();
    const stopKey = (e: KeyboardEvent) => { if (["PageUp", "PageDown", "Home", "End", "ArrowUp", "ArrowDown"].includes(e.key)) e.preventDefault(); };
    window.addEventListener("wheel", stopEvent, { passive: false });
    window.addEventListener("touchmove", stopEvent, { passive: false });
    window.addEventListener("keydown", stopKey);
    return () => {
      window.removeEventListener("wheel", stopEvent);
      window.removeEventListener("touchmove", stopEvent);
      window.removeEventListener("keydown", stopKey);
    };
  }, [lockScroll]);

  // first arrival in the arena: the stampede starts on its own
  const arrived = useRef(false);
  useEffect(() => {
    if (stage !== "arena" || arrived.current || !autoConverge) return;
    // `arrived` flips inside the timer, so a StrictMode remount (which clears the timer) re-arms it
    const t = setTimeout(() => {
      arrived.current = true;
      useArena.getState().actions.converge();
    }, 800);
    return () => clearTimeout(t);
  }, [stage, autoConverge]);

  // leaving the arena for the tour sends everyone back to their spawn lawns (the chapters show them there);
  // coming back sends them in again
  const prevStage = useRef(stage);
  useEffect(() => {
    if (prevStage.current === "arena" && stage === "scroll") {
      useArena.getState().actions.disperse();
      arrived.current = false;
    }
    prevStage.current = stage;
  }, [stage]);

  // the other laptops: tell them this one is here, and mirror every selection and view change to them (lib/sync)
  useEffect(() => {
    setClientRole("arena");
    publish("hello", {});
    const hb = setInterval(() => publish("hello", {}), 8000);
    const off = useArena.subscribe((s, p) => {
      if (s.selectedId !== p.selectedId) { const a = s.selectedId ? ROSTER_BY_ID[s.selectedId] : null; publish("select", { id: s.selectedId, name: a?.name ?? null, team: a?.team ?? null }); }
      if (s.panel !== p.panel) publish("panel", { panel: s.panel });
      if (s.stage !== p.stage) publish("stage", { stage: s.stage });
      if (s.show.beat !== p.show.beat || s.show.status !== p.show.status) publish("show", { status: s.show.status, beat: s.show.beat });
    });
    return () => { clearInterval(hb); off(); };
  }, []);

  // backstage: the consoles for the other laptops. Not linked anywhere; for an admin, B opens the hub in a new tab.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
      if ((e.key === "b" || e.key === "B") && !e.metaKey && !e.ctrlKey && !e.altKey && isAdmin()) window.open("/backstage", "_blank", "noopener"); // admins only: nobody else is told it exists
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // a card (compare, evolution, report) belongs to the arena: scrolling back up to the tour closes it. The lenders card is the
  // exception: the pitch opens with it, over the title, before anyone has scrolled (L opens it from anywhere).
  useEffect(() => {
    if (stage !== "arena" && panel && panel !== "lenders" && !inShow) setPanel(null);
  }, [stage, panel, inShow, setPanel]);

  // L: what the big lenders have said, with sources (the pitch's opening beat)
  useEffect(() => {
    if (inShow) return;
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;
      if ((e.key === "l" || e.key === "L") && !e.metaKey && !e.ctrlKey && !e.altKey) setPanel(useArena.getState().panel === "lenders" ? null : "lenders");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [inShow, setPanel]);

  // escape closes a card
  useEffect(() => {
    if (!panel || inShow) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setPanel(null); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [panel, inShow, setPanel]);

  // public handle
  const runRef = useRef(feed.run);
  runRef.current = feed.run;
  const showRef = useRef(show.start);
  showRef.current = show.start;
  const pitchRef = useRef(pitch.start);
  pitchRef.current = pitch.start;
  useEffect(() => {
    const api = {
      converge: () => useArena.getState().actions.converge(),
      disperse: () => useArena.getState().actions.disperse(),
      select: (id: string | null) => useArena.getState().select(id),
      run: (mode?: "off" | "shadow" | "enforce") => runRef.current(mode),
      show: () => showRef.current(),
      pitch: () => pitchRef.current(),
      /** what the camera and the spotlight are looking at (for debugging a shot) */
      debug: () => ({ phase: useArena.getState().simPhase, focus: [...focus.ids], pinned: [...focus.pinned], level: +focus.level.toFixed(2), cinema: { ...cinema } }),
    };
    (window as unknown as { redledger?: typeof api }).redledger = api;
    return () => { delete (window as unknown as { redledger?: typeof api }).redledger; };
  }, []);

  return (
    <div className="arena" data-stage={stage} data-show={show.status} data-pitch={pitch.phase} data-panel={panel ?? ""}>
      <div className="arena-canvas">
        <Scene subscribe={feed.subscribe} feedActive={feed.running || inShow || feed.state.episodeId !== null} onSim={onSim} onProgress={onProgress} tallies={tallies} />
      </div>
      <div className="spot" aria-hidden />
      <TitleOverlay key={`${show.runKey}:${pitch.runKey}`} onShow={show.start} onPitch={pitch.start} />
      <Chapters />
      <Hud feed={feed} show={show} pitch={pitch} />
      <PitchOverlay feed={feed} pitch={pitch} />
      <CompareCard sides={sides} open={panel === "compare"} onClose={() => setPanel(null)} />
      <EvolutionCard open={panel === "evolve"} driven={inShow} preferLive={feed.backend.state === "live"} onClose={() => setPanel(null)} />
      <ReportCard state={feed.state} live={feed.source === "live"} open={panel === "report"} onClose={() => setPanel(null)} />
      <LendersCard open={panel === "lenders"} onClose={() => setPanel(null)} />
      <ShowBar show={show} />
      <AgentModal state={feed.state} catalogs={feed.catalogs} overrides={agentDetails} />
      <LabelLayer />
      <PopLayer />
      <Loader progress={progress} />
      <div className="arena-scroll" style={{ height: `${SCROLL_VH}vh` }} aria-hidden />
    </div>
  );
}
