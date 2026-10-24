import { describe, expect, it } from "vitest";
import { QualityGovernor, type Level } from "./governor";

/** run `seconds` of frames at `fps`, returning the levels the governor announced */
function run(g: QualityGovernor, seconds: number, fps: number): Level[] {
  const out: Level[] = [];
  const dt = 1 / fps;
  for (let t = 0; t < seconds; t += dt) { const l = g.frame(dt); if (l !== null) out.push(l); }
  return out;
}

describe("quality governor", () => {
  it("leaves a healthy machine alone", () => {
    const g = new QualityGovernor(3);
    expect(run(g, 60, 58)).toEqual([]);
    expect(g.level).toBe(3);
  });

  it("ignores the first seconds after load, however slow they are", () => {
    const g = new QualityGovernor(3);
    expect(run(g, 5.5, 8)).toEqual([]);
  });

  it("ignores stalls: a hidden pane or a window drag is not a slow machine", () => {
    const g = new QualityGovernor(3);
    run(g, 7, 60);
    for (let i = 0; i < 40; i++) expect(g.frame(1.2)).toBeNull(); // 1 fps, as a throttled background page delivers
    expect(g.level).toBe(3);
    expect(run(g, 3, 8)).toEqual([]); // and a short dip is not enough either
  });

  it("steps down only after several whole seconds of low frame rate, one level at a time", () => {
    const g = new QualityGovernor(3);
    run(g, 7, 60);
    expect(run(g, 3.5, 15)).toEqual([]);
    expect(run(g, 1.8, 15)).toEqual([2]);
    expect(run(g, 5.2, 15)).toEqual([1]);
    expect(run(g, 5.2, 15)).toEqual([0]);
    expect(run(g, 30, 10)).toEqual([]); // the floor
    expect(g.level).toBe(0);
  });

  it("steps back up when there turns out to be headroom, but not straight away", () => {
    const g = new QualityGovernor(3);
    run(g, 7, 60);
    expect(run(g, 5.2, 15)).toEqual([2]);
    expect(run(g, 15, 60)).toEqual([]); // cooldown
    expect(run(g, 12, 60)).toEqual([3]);
  });

  it("gives up on the higher level if it cannot hold it, and never goes past where it started", () => {
    const g = new QualityGovernor(2);
    run(g, 7, 60);
    expect(run(g, 5.2, 15)).toEqual([1]);
    expect(run(g, 40, 60)).toEqual([2]);
    expect(run(g, 5.2, 15)).toEqual([1]);
    expect(run(g, 80, 60)).toEqual([]); // locked at 1 now
    expect(g.level).toBe(1);
    expect(new QualityGovernor(3, { settleSeconds: 0 }).level).toBe(3);
  });
});
