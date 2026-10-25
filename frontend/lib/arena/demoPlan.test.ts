import { describe, expect, it } from "vitest";
import { DEMO_PLAN_CYCLE, demoPlan, plannedEpisode, RUN_DAYS, SANDBOX_DAYS } from "./demoPlan";

describe("plannedEpisode", () => {
  it("pins one scheme for every day of an arena run", () => {
    const b = plannedEpisode("enforce", 42, RUN_DAYS);
    expect(b).toMatchObject({ controller_mode: "enforce", seed: 42, days: 12 });
    expect(b.attack_plan).toHaveLength(RUN_DAYS);
    expect(b.attack_plan.map((x) => x.day)).toEqual(Array.from({ length: RUN_DAYS }, (_, d) => d));
    expect(b.attack_plan.slice(0, 6).map((x) => x.scheme_id)).toEqual([...DEMO_PLAN_CYCLE]);
  });

  it("covers a judge's sandbox too", () => {
    const b = plannedEpisode("off", 42, SANDBOX_DAYS);
    expect(b.attack_plan).toEqual(demoPlan(SANDBOX_DAYS));
    expect(b.attack_plan).toHaveLength(30);
  });

  it("runs about 6 to 10 minutes live", () => {
    expect(RUN_DAYS).toBeGreaterThanOrEqual(10);
    expect(RUN_DAYS).toBeLessThanOrEqual(15);
  });
});
