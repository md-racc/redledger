"use client";
// redledger: the cinematic 3D front door. Composes the R3F scene, the scroll tour and the HTML overlays, and wires
// the episode feed (live battlefield, or the recorded sample) into the arena.
//
// Host integration:
//   <ArenaExperience agentDetails={{ "red:ghost_vendor": { story: "...", fields: { targeted: 4920 } } }} />
//   window.redledger.converge() / .disperse() / .select(id) / .run(mode)
import { useCallback, useEffect, useRef, useState } from "react";
import type { AgentDetailOverrides } from "@/lib/arena/types";
import type { ArenaSim } from "@/lib/arena/sim";
import { useArena } from "@/lib/arena/store";
import { useFeed } from "@/lib/arena/useFeed";
import Scene from "./Scene";
import { AgentModal } from "./overlays/AgentModal";
import { Chapters } from "./overlays/Chapters";
import { Hud } from "./overlays/Hud";
import { LabelLayer } from "./overlays/LabelLayer";
import { Loader } from "./overlays/Loader";
import { PopLayer } from "./overlays/PopLayer";
import { TitleOverlay } from "./overlays/TitleOverlay";

interface Props {
  agentDetails?: AgentDetailOverrides;
  /** send the agents in a moment after the visitor lands in the arena (default true) */
  autoConverge?: boolean;
}

const SCROLL_VH = 640;

export default function ArenaExperience({ agentDetails, autoConverge = true }: Props) {
  const feed = useFeed();
  const stage = useArena((s) => s.stage);
  const modelState = useArena((s) => s.modelState);
  const [progress, setProgress] = useState(0);
  const [sim, setSim] = useState<ArenaSim | null>(null);
  const boot = useRef(0);

  const onProgress = useCallback((p: { progress: number }) => setProgress(p.progress), []);
  const onSim = useCallback((s: ArenaSim) => setSim(s), []);

  // loading → intro once the model and sim exist (with a floor so the title card is seen, and a ceiling so it never hangs)
  useEffect(() => {
    if (stage !== "loading") return;
    if (!boot.current) boot.current = performance.now();
    const ready = !!sim && modelState !== "pending";
    const wait = ready ? Math.max(0, 1800 - (performance.now() - boot.current)) : 35000;
    const t = setTimeout(() => useArena.getState().setStage("intro"), wait);
    return () => clearTimeout(t);
  }, [stage, sim, modelState]);

  // the page does not scroll while loading or flying
  useEffect(() => {
    const lock = stage === "loading" || stage === "intro";
    document.documentElement.style.overflow = lock ? "hidden" : "";
    document.body.style.overflow = lock ? "hidden" : "";
    return () => { document.documentElement.style.overflow = ""; document.body.style.overflow = ""; };
  }, [stage]);

  // first arrival in the arena: the stampede starts on its own
  const arrived = useRef(false);
  useEffect(() => {
    if (stage !== "arena" || arrived.current || !autoConverge) return;
    // `arrived` flips inside the timer, so a StrictMode remount (which clears the timer) re-arms it
    const t = setTimeout(() => {
      arrived.current = true;
      useArena.getState().actions.converge();
    }, 1400);
    return () => clearTimeout(t);
  }, [stage, autoConverge]);

  // public handle
  const runRef = useRef(feed.run);
  runRef.current = feed.run;
  useEffect(() => {
    const api = {
      converge: () => useArena.getState().actions.converge(),
      disperse: () => useArena.getState().actions.disperse(),
      select: (id: string | null) => useArena.getState().select(id),
      run: (mode?: "off" | "shadow" | "enforce") => runRef.current(mode),
    };
    (window as unknown as { redledger?: typeof api }).redledger = api;
    return () => { delete (window as unknown as { redledger?: typeof api }).redledger; };
  }, []);

  return (
    <div className="arena" data-stage={stage}>
      <div className="arena-canvas">
        <Scene subscribe={feed.subscribe} feedActive={feed.running} onSim={onSim} onProgress={onProgress} />
      </div>
      <TitleOverlay />
      <Chapters />
      <Hud feed={feed} />
      <AgentModal state={feed.state} catalogs={feed.catalogs} overrides={agentDetails} />
      <LabelLayer />
      <PopLayer />
      <Loader progress={progress} />
      <div className="arena-scroll" style={{ height: `${SCROLL_VH}vh` }} aria-hidden />
    </div>
  );
}
