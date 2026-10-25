// Low-frequency UI state for the arena (selection, hover, experience phase). Per-frame state (agent positions,
// camera) lives in the sim and the timeline, never here, so React does not re-render at 60 Hz.
import { create } from "zustand";
import type { ControllerMode } from "../types";
import type { BeatId, ShowStatus } from "./show";
import type { FxTone } from "./sim";
import type { ArenaPhase } from "./types";

/** Where the visitor is in the experience. */
export type Stage = "loading" | "intro" | "scroll" | "arena";

export type FeedSource = "idle" | "live" | "mock";

/** A card over the arena: the off-vs-on comparison, the evolution report, the end-of-day report, or what the lenders have said. */
export type Panel = "compare" | "evolve" | "report" | "lenders" | null;

export interface ShowState { status: ShowStatus; beat: BeatId | null; caption: string | null; sub: string | null; }

interface ArenaState {
  stage: Stage;
  setStage: (s: Stage) => void;
  /** the arena camera controls are live and the HUD is shown */
  hoveredId: string | null;
  selectedId: string | null;
  setHovered: (id: string | null) => void;
  select: (id: string | null) => void;
  /** mirrors sim.phase for the HUD */
  simPhase: ArenaPhase;
  setSimPhase: (p: ArenaPhase) => void;
  /** imperative hooks the 3D side registers so the HUD / host app can drive the sim */
  actions: { converge: () => void; disperse: () => void; pulse: (id: string, tone: FxTone, text?: string) => void };
  registerActions: (a: ArenaState["actions"]) => void;
  /** bumped by `converge()` callers that arrive before the sim exists */
  skipIntro: boolean;
  setSkipIntro: (v: boolean) => void;
  modelState: "pending" | "real" | "fallback";
  setModelState: (m: ArenaState["modelState"]) => void;
  /** auto-cam: the arena camera frames each fraud attempt as it plays out */
  cinematic: boolean;
  setCinematic: (v: boolean) => void;
  panel: Panel;
  setPanel: (p: Panel) => void;
  /** the 90-second show */
  show: ShowState;
  setShow: (s: Partial<ShowState>) => void;
  /** mirrors the episode's controller mode */
  controllerMode: ControllerMode;
  setControllerMode: (m: ControllerMode) => void;
  /** bumped when the show rewinds to day 0 between acts (the rewind flash replays) */
  rewind: number;
  bumpRewind: () => void;
}

export const useArena = create<ArenaState>((set) => ({
  stage: "loading",
  setStage: (stage) => set({ stage }),
  hoveredId: null,
  selectedId: null,
  setHovered: (hoveredId) => set((s) => (s.hoveredId === hoveredId ? s : { hoveredId })),
  select: (selectedId) => set({ selectedId }),
  simPhase: "idle",
  setSimPhase: (simPhase) => set((s) => (s.simPhase === simPhase ? s : { simPhase })),
  actions: { converge: () => {}, disperse: () => {}, pulse: () => {} },
  registerActions: (actions) => set({ actions }),
  skipIntro: false,
  setSkipIntro: (skipIntro) => set({ skipIntro }),
  modelState: "pending",
  setModelState: (modelState) => set({ modelState }),
  cinematic: true,
  setCinematic: (cinematic) => set({ cinematic }),
  panel: null,
  setPanel: (panel) => set({ panel }),
  show: { status: "off", beat: null, caption: null, sub: null },
  setShow: (s) => set((st) => ({ show: { ...st.show, ...s } })),
  controllerMode: "shadow",
  setControllerMode: (controllerMode) => set((s) => (s.controllerMode === controllerMode ? s : { controllerMode })),
  rewind: 0,
  bumpRewind: () => set((s) => ({ rewind: s.rewind + 1 })),
}));

/** Public handle for host code and the browser console: `window.redledger.converge()`. */
export const arena = {
  converge: () => useArena.getState().actions.converge(),
  disperse: () => useArena.getState().actions.disperse(),
  select: (id: string | null) => useArena.getState().select(id),
};
