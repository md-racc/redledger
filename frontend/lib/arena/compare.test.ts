import { describe, expect, it } from "vitest";
import { initialState } from "../reducer";
import type { Score, UIState } from "../types";
import { compareSides, projectOff } from "./compare";
import type { RunRecord } from "./useFeed";

const score = (p: Partial<Score>): Score => ({ dollars_extracted: 0, dollars_blocked: 0, false_positive_cost: 0, detection_latency_days: null, attacks_launched: 0, attacks_caught: 0, legit_blocked: 0, legit_processed: 100, ...p });
const withAttacks = (targets: number[]): UIState => ({
  ...initialState(),
  attacks: Object.fromEntries(targets.map((t, i) => [`a${i}`, { attack_id: `a${i}`, scheme_id: "x", display_name: "X", story: "", target_amount: t, day_launched: i, outcome: "blocked" as const, amount_extracted: 0, detected_day: i }])),
});
const run = (mode: RunRecord["mode"], s: Score): RunRecord => ({ episodeId: `ep_${mode}`, mode, score: s, projected: false });

describe("compare sides", () => {
  it("projects the controller-off side from the attacks when only an enforce run exists", () => {
    const on = score({ dollars_blocked: 23000, attacks_caught: 3, attacks_launched: 4 });
    const sides = compareSides([run("enforce", on)], withAttacks([5000, 4000, 8000, 6000]))!;
    expect(sides.offProjected).toBe(true);
    expect(sides.off.dollars_extracted).toBe(23000);
    expect(sides.off.attacks_caught).toBe(0);
    expect(sides.off.legit_processed).toBe(100);
    expect(sides.on).toBe(on);
    expect(sides.live).toBe(false);
  });

  it("uses a real controller-off run when there is one", () => {
    const off = score({ dollars_extracted: 30000 });
    const on = score({ dollars_blocked: 25000 });
    const sides = compareSides([run("off", off), run("enforce", on)], withAttacks([1]))!;
    expect(sides.offProjected).toBe(false);
    expect(sides.off).toBe(off);
    expect(sides.onMode).toBe("enforce");
  });

  it("compares a run in flight with its projection, and has nothing to say before any attack", () => {
    const s = { ...withAttacks([7000]), controllerMode: "enforce" as const, score: score({ dollars_blocked: 7000 }) };
    const live = compareSides([], s)!;
    expect(live.live).toBe(true);
    expect(live.off.dollars_extracted).toBe(7000);
    expect(compareSides([], initialState())).toBeNull();
  });

  it("projectOff counts every target", () => {
    expect(projectOff(withAttacks([1000, 2500]), score({})).dollars_extracted).toBe(3500);
  });
});
