// Which two runs the compare card puts side by side. Owner: Dev R.
//
// The backend's own comparison is GET /fe/compare?a=&b= on two episodes with the same seed, one controller off and one
// enforce. Here the pair comes from the runs this session has finished; when there is no real controller-off run, the
// off side is the same attacks with nothing gating them (every target walks out), and says so.
import type { ControllerMode, Score, UIState } from "../types";
import type { RunRecord } from "./useFeed";

export interface CompareSides {
  off: Score;
  on: Score;
  onMode: ControllerMode;
  /** the off side is a projection, not a run */
  offProjected: boolean;
  /** the on side is still running */
  live: boolean;
}

/** The same attacks with no controller: every target is extracted, nothing is blocked, nothing is a false positive. */
export function projectOff(state: UIState, like: Score): Score {
  const targets = Object.values(state.attacks).reduce((n, a) => n + (a.target_amount || 0), 0);
  return {
    dollars_extracted: targets,
    dollars_blocked: 0,
    false_positive_cost: 0,
    detection_latency_days: null,
    attacks_launched: Object.keys(state.attacks).length,
    attacks_caught: 0,
    legit_blocked: 0,
    legit_processed: like.legit_processed,
  };
}

export function compareSides(runs: RunRecord[], state: UIState): CompareSides | null {
  const on = [...runs].reverse().find((r) => r.mode !== "off");
  const off = [...runs].reverse().find((r) => r.mode === "off");
  if (on) {
    return { off: off ? off.score : projectOff(state, on.score), on: on.score, onMode: on.mode, offProjected: !off, live: false };
  }
  // nothing has finished yet: compare the run in flight with its projection
  if (Object.keys(state.attacks).length && state.controllerMode !== "off") {
    return { off: projectOff(state, state.score), on: state.score, onMode: state.controllerMode, offProjected: true, live: true };
  }
  return null;
}
