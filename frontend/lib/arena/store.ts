// Low-frequency UI state for the arena (selection, hover, experience phase). Per-frame state (agent positions,
// camera) lives in the sim and the timeline, never here, so React does not re-render at 60 Hz.
import { create } from "zustand";
import type { ArenaPhase } from "./types";

/** Where the visitor is in the experience. */
export type Stage = "loading" | "intro" | "scroll" | "arena";

export type FeedSource = "idle" | "live" | "mock";

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
  actions: { converge: () => void; disperse: () => void };
  registerActions: (a: ArenaState["actions"]) => void;
  /** bumped by `converge()` callers that arrive before the sim exists */
  skipIntro: boolean;
  setSkipIntro: (v: boolean) => void;
  modelState: "pending" | "real" | "fallback";
  setModelState: (m: ArenaState["modelState"]) => void;
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
  actions: { converge: () => {}, disperse: () => {} },
  registerActions: (actions) => set({ actions }),
  skipIntro: false,
  setSkipIntro: (skipIntro) => set({ skipIntro }),
  modelState: "pending",
  setModelState: (modelState) => set({ modelState }),
}));

/** Public handle for host code and the browser console: `window.redledger.converge()`. */
export const arena = {
  converge: () => useArena.getState().actions.converge(),
  disperse: () => useArena.getState().actions.disperse(),
  select: (id: string | null) => useArena.getState().select(id),
};
