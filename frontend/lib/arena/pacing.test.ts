import { describe, expect, it } from "vitest";
import { DWELL_HALF, railOf, railSpeed, scrollOf } from "./pacing";
import { CHAPTERS } from "./timeline";

describe("scroll pacing", () => {
  it("covers the whole rail and round-trips", () => {
    expect(railOf(0)).toBeCloseTo(0, 6);
    expect(railOf(1)).toBeCloseTo(1, 6);
    for (let u = 0; u <= 1; u += 0.037) expect(railOf(scrollOf(u))).toBeCloseTo(u, 3);
  });

  it("never runs backwards", () => {
    let prev = -1;
    for (let s = 0; s <= 1; s += 0.002) {
      const u = railOf(s);
      expect(u).toBeGreaterThanOrEqual(prev);
      prev = u;
    }
  });

  it("is several times slower at a chapter than between chapters", () => {
    const mid = (CHAPTERS[1].at + CHAPTERS[2].at) / 2;
    expect(railSpeed(mid) / railSpeed(CHAPTERS[1].at)).toBeGreaterThan(3.5);
  });

  it("gives every chapter room to be read without making the transits a blink", () => {
    let dwell = 0;
    for (const c of CHAPTERS) {
      const share = scrollOf(Math.min(1, c.at + DWELL_HALF)) - scrollOf(Math.max(0, c.at - DWELL_HALF));
      dwell += share;
      expect(share).toBeGreaterThan(0.06);
    }
    expect(dwell).toBeGreaterThan(0.5);
    expect(dwell).toBeLessThan(0.9);
    for (let i = 0; i < CHAPTERS.length - 1; i++) {
      const gap = scrollOf(CHAPTERS[i + 1].at - DWELL_HALF) - scrollOf(CHAPTERS[i].at + DWELL_HALF);
      expect(gap).toBeGreaterThan(0.02);
    }
  });

  it("holds the camera nearly still across a reading zone", () => {
    const c = CHAPTERS[2];
    const du = railOf(scrollOf(c.at) + 0.02) - railOf(scrollOf(c.at) - 0.02);
    const dTransit = railOf(scrollOf((CHAPTERS[1].at + c.at) / 2) + 0.02) - railOf(scrollOf((CHAPTERS[1].at + c.at) / 2) - 0.02);
    expect(dTransit / du).toBeGreaterThan(3.5);
  });
});
