import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { initialState, reduce } from "../reducer";
import type { RLEvent } from "../types";
import { ScriptRunner, schedule, type ScriptItem } from "./script";
import { buildOffAct, buildOnAct, finalScoreOf, projectBaseline } from "./showScripts";

const fixture: RLEvent[] = readFileSync("public/mocks/sample.jsonl", "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l));
const run = (items: ScriptItem[], ctxPatch?: (r: ScriptRunner) => void, stepMs = 100, maxMs = 120_000) => {
  const out: RLEvent[] = [];
  const r = new ScriptRunner(items, (e) => out.push(e));
  ctxPatch?.(r);
  for (let t = 0; t < maxMs && !r.done; t += stepMs) r.advance(stepMs);
  return { out, r };
};
const fold = (events: RLEvent[]) => events.reduce(reduce, initialState());

describe("ScriptRunner", () => {
  const ev = (id: number): RLEvent => ({ id, ts: "", episode_id: "x", day: 0, type: "t", agent: null, payload: {}, replay: true });

  it("emits in order as the clock passes each item", () => {
    const got: number[] = [];
    const r = new ScriptRunner([{ at: 300, e: ev(3) }, { at: 0, e: ev(1) }, { at: 100, e: ev(2) }], (e) => got.push(e.id));
    r.advance(50);
    expect(got).toEqual([1]);
    r.advance(100);
    expect(got).toEqual([1, 2]);
    r.advance(1000);
    expect(got).toEqual([1, 2, 3]);
    expect(r.done).toBe(true);
  });

  it("stops the clock on a hold until released, then carries on", () => {
    const got: number[] = [];
    let go = false;
    const r = new ScriptRunner(
      [{ at: 0, e: ev(1), hold: { until: () => go, maxMs: 10_000, timeout: () => {} } }, { at: 100, e: ev(2) }],
      (e) => got.push(e.id),
    );
    r.advance(10);
    expect(r.holding).toBe(true);
    r.advance(5000);
    expect(got).toEqual([1]);
    go = true;
    r.advance(10);
    expect(r.holding).toBe(false);
    r.advance(200);
    expect(got).toEqual([1, 2]);
  });

  it("times a hold out through its handler", () => {
    const got: number[] = [];
    const r = new ScriptRunner(
      [{ at: 0, e: ev(1), hold: { until: () => false, maxMs: 1000, timeout: (_c, emit) => emit(ev(99)) } }, { at: 50, e: ev(2) }],
      (e) => got.push(e.id),
    );
    r.advance(10);
    r.advance(1100);
    r.advance(100);
    expect(got).toEqual([1, 99, 2]);
  });

  it("skips items whose guard says no, and flush() empties the rest", () => {
    const got: number[] = [];
    const r = new ScriptRunner([{ at: 0, e: ev(1), when: () => false }, { at: 10, e: ev(2) }, { at: 9000, e: ev(3) }], (e) => got.push(e.id));
    r.advance(20);
    expect(got).toEqual([2]);
    r.flush();
    expect(got).toEqual([2, 3]);
  });
});

describe("schedule", () => {
  it("keeps order and fits the window", () => {
    const items = schedule(fixture, 20_000);
    expect(items).toHaveLength(fixture.length);
    for (let i = 1; i < items.length; i++) expect(items[i].at).toBeGreaterThanOrEqual(items[i - 1].at);
    expect(items[0].at).toBe(0);
    expect(items[items.length - 1].at).toBeLessThan(20_000);
    expect(items[items.length - 1].at).toBeGreaterThan(17_000);
  });

  it("gives a fraud attempt room before its outcome", () => {
    const items = schedule(fixture, 36_000);
    const launched = items.find((i) => i.e.type === "attack.launched")!;
    const outcome = items.find((i) => i.e.type === "attack.outcome")!;
    expect(outcome.at - launched.at).toBeGreaterThan(2500);
  });
});

describe("the controller-off baseline", () => {
  const off = projectBaseline(fixture);
  it("is never gated and every attack gets away with its target", () => {
    expect(off.some((e) => e.type === "gate.verdict" || e.type === "flag.raised")).toBe(false);
    const s = fold(off);
    const targets = fixture.filter((e) => e.type === "attack.launched").reduce((n, e) => n + Number((e.payload as any).target_amount), 0);
    expect(s.score.dollars_extracted).toBeCloseTo(targets, 2);
    expect(s.score.dollars_blocked).toBe(0);
    expect(s.score.attacks_caught).toBe(0);
    expect(s.score.attacks_launched).toBe(4);
    expect(s.controllerMode).toBe("off");
    expect(finalScoreOf(off)!.dollars_extracted).toBeCloseTo(targets, 2);
  });
  it("plays as a script inside its window", () => {
    const act = buildOffAct(fixture, 14_000);
    const { out } = run(act.items);
    expect(act.escalationId).toBeNull();
    expect(out.length).toBe(off.length);
  });
});

describe("the enforce act with a human in the loop", () => {
  const recorded = fold(fixture);
  const act = buildOnAct(fixture, 20_000, 6000);

  it("opens an escalation late in the run", () => {
    expect(act.escalationId).toBe("esc_show_1");
    const { out } = run(act.items, (r) => { r.ctx.decisions[act.escalationId!] = "block"; });
    const opened = out.findIndex((e) => e.type === "escalation.opened");
    expect(opened).toBeGreaterThan(out.findIndex((e) => e.type === "attack.launched" && (e.payload as any).scheme_id === "threshold_split"));
    expect(out.filter((e) => e.type === "gate.verdict" && (e.payload as any).verdict === "escalate")).toHaveLength(1);
  });

  it("with no decision, the hold times out into a block and the recorded result stands", () => {
    const { out } = run(act.items, undefined, 100, 200_000);
    const resolved = out.filter((e) => e.type === "escalation.resolved");
    expect(resolved).toHaveLength(1);
    expect((resolved[0].payload as any).decision).toBe("block");
    const s = fold(out);
    expect(s.score.dollars_extracted).toBe(recorded.score.dollars_extracted);
    expect(s.score.dollars_blocked).toBeCloseTo(recorded.score.dollars_blocked, 2);
    expect(s.escalations["esc_show_1"].status).toBe("block");
  });

  it("an early human block releases the hold without waiting", () => {
    const out: RLEvent[] = [];
    const r = new ScriptRunner(act.items, (e) => out.push(e));
    let t = 0;
    while (!r.holding && t < 60_000) { r.advance(100); t += 100; }
    expect(r.holding).toBe(true);
    r.ctx.decisions["esc_show_1"] = "block";
    r.advance(100);
    expect(r.holding).toBe(false);
  });

  it("approving lets that invoice through: the attack becomes partial and the money leaves", () => {
    const out: RLEvent[] = [];
    const r = new ScriptRunner(act.items, (e) => out.push(e));
    while (!r.holding) r.advance(100);
    r.ctx.decisions["esc_show_1"] = "approve";
    while (!r.done) r.advance(100);
    const s = fold(out);
    expect(s.score.dollars_extracted).toBe(recorded.score.dollars_extracted + 4800);
    expect(s.score.dollars_blocked).toBeCloseTo(recorded.score.dollars_blocked - 4800, 2);
    expect(s.score.attacks_launched).toBe(recorded.score.attacks_launched);
    expect(s.score.legit_processed).toBe(recorded.score.legit_processed);
    expect(Number.isFinite(s.score.false_positive_cost)).toBe(true);
    const split = Object.values(s.attacks).find((a) => a.scheme_id === "threshold_split")!;
    expect(split.outcome).toBe("partial");
    expect(split.amount_extracted).toBe(4800);
  });
});
