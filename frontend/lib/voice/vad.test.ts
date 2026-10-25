import { describe, expect, it } from "vitest";
import { createEndpointer, GIVE_UP_MS, PAUSE_MS } from "./vad";

// readings arrive every 90 ms, like the recorder's level meter
const STEP = 90;
function run(levels: number[], opts?: Parameters<typeof createEndpointer>[0]) {
  const ep = createEndpointer(opts);
  const out = levels.map((l, i) => ep.feed(l, 1000 + i * STEP));
  return { ep, out };
}
const talk = (n: number) => Array(n).fill(0.2);
const quiet = (n: number) => Array(n).fill(0.005);

describe("pause detector", () => {
  it("keeps listening while someone is talking", () => {
    const { out, ep } = run(talk(60));
    expect(out.every((v) => v === "keep_going")).toBe(true);
    expect(ep.heard).toBe(true);
  });

  it("says finished once they have talked and then paused long enough", () => {
    const pause = Math.ceil(PAUSE_MS / STEP) + 1;
    const { out } = run([...talk(20), ...quiet(pause + 2)]);
    expect(out.indexOf("finished")).toBeGreaterThan(20);
    expect(out.slice(0, 20).every((v) => v === "keep_going")).toBe(true);
  });

  it("does not finish on a short breath between words", () => {
    const { out } = run([...talk(10), ...quiet(8), ...talk(10), ...quiet(8)]);
    expect(out).not.toContain("finished");
  });

  it("a pause that is then followed by more talking starts the clock again", () => {
    const { out } = run([...talk(10), ...quiet(15), ...talk(5), ...quiet(15)]);
    expect(out).not.toContain("finished");
  });

  it("does not take one loud click for speech", () => {
    const { out, ep } = run([0.5, ...quiet(40)]);
    expect(ep.heard).toBe(false);
    expect(out).not.toContain("finished");
  });

  it("says nobody spoke when it never hears talking", () => {
    const n = Math.ceil(GIVE_UP_MS / STEP) + 2;
    const { out, ep } = run(quiet(n));
    expect(ep.heard).toBe(false);
    expect(out.indexOf("nobody_spoke")).toBeGreaterThan(Math.floor(GIVE_UP_MS / STEP) - 2);
    expect(out[10]).toBe("keep_going");
  });

  it("never says finished or nobody_spoke in a room that is loud the whole time", () => {
    const { out } = run(talk(400));
    expect(out).not.toContain("finished");
    expect(out).not.toContain("nobody_spoke");
  });

  it("honours custom thresholds", () => {
    const { out } = run([0.02, 0.02, 0.02, 0, 0, 0], { talking: 0.01, reads: 2, pauseMs: STEP * 2 });
    expect(out).toContain("finished");
  });
});
