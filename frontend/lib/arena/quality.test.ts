import { describe, expect, it } from "vitest";
import { QUALITY } from "./quality";

const levels = [3, 2, 1, 0] as const;

describe("quality ladder", () => {
  it("never turns shadows off: toggling them on a live renderer blacks out the scene (GL sampler mismatch)", () => {
    for (const l of levels) expect(QUALITY[l].shadows).toBe(true);
  });

  it("each step down is no more expensive than the one above it", () => {
    for (let i = 1; i < levels.length; i++) {
      const hi = QUALITY[levels[i - 1]], lo = QUALITY[levels[i]];
      expect(lo.level).toBe(levels[i]);
      expect(lo.dpr[1]).toBeLessThanOrEqual(hi.dpr[1]);
      expect(lo.shadowEvery).toBeGreaterThanOrEqual(hi.shadowEvery);
      expect(lo.shadowMap).toBeLessThanOrEqual(hi.shadowMap);
    }
  });

  it("refreshes the shadow map at a whole-frame cadence", () => {
    for (const l of levels) {
      expect(Number.isInteger(QUALITY[l].shadowEvery)).toBe(true);
      expect(QUALITY[l].shadowEvery).toBeGreaterThanOrEqual(1);
    }
  });
});
