import { describe, expect, it } from "vitest";
import type { RLEvent } from "../types";
import { delayAfter, Pacer } from "./pacer";

const ev = (id: number, type: string, payload: Record<string, unknown> = {}): RLEvent => ({ id, ts: "", episode_id: "x", day: 0, type, agent: null, payload });

describe("Pacer", () => {
  it("hands a burst on one beat at a time, in order, without losing any", () => {
    const p = new Pacer();
    const got: number[] = [];
    [ev(1, "day.started"), ev(2, "attack.launched"), ev(3, "gate.verdict", { verdict: "block" }), ev(4, "attack.outcome"), ev(5, "score.updated")].forEach((e) => p.push(e));
    p.advance(0, (e) => got.push(e.id));
    expect(got).toEqual([1]); // the day opens, then it waits
    p.advance(100, (e) => got.push(e.id));
    expect(got).toEqual([1]);
    for (let i = 0; i < 20; i++) p.advance(250, (e) => got.push(e.id));
    expect(got).toEqual([1, 2, 3, 4, 5]);
  });

  it("lets an attack breathe before its outcome", () => {
    expect(delayAfter(ev(1, "attack.launched"))).toBeGreaterThan(1000);
    expect(delayAfter(ev(2, "gate.verdict", { verdict: "allow" }))).toBe(0);
  });

  it("speeds up when it is far behind", () => {
    const slow = new Pacer();
    const fast = new Pacer();
    for (let i = 0; i < 80; i++) { slow.push(ev(i, "attack.outcome")); }
    for (let i = 0; i < 5; i++) { fast.push(ev(i, "attack.outcome")); }
    const a: number[] = [], b: number[] = [];
    for (let t = 0; t < 4000; t += 100) { slow.advance(100, (e) => a.push(e.id)); fast.advance(100, (e) => b.push(e.id)); }
    expect(a.length).toBeGreaterThan(b.length * 3);
  });
});
