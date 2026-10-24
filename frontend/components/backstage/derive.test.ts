import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { initialState, reduce } from "@/lib/reducer";
import type { RLEvent } from "@/lib/types";
import { attacksNewestFirst, avgLatency, confusion, greenActions, ruleBoard, schemeBoard, thoughts, toolRows, verdictCounts } from "./derive";

const fixture: RLEvent[] = readFileSync("public/mocks/sample.jsonl", "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l));
const state = fixture.reduce((s, e) => reduce(s, { ...e, replay: true }), initialState());

describe("backstage derivations", () => {
  it("red: the scheme board totals what the attacks did, newest attack first", () => {
    const board = schemeBoard(Object.values(state.attacks));
    expect(board.map((r) => r.scheme).sort()).toEqual(["bank_swap", "duplicate_invoice", "ghost_vendor", "threshold_split"]);
    expect(board.reduce((n, r) => n + r.targeted, 0)).toBeCloseTo(Object.values(state.attacks).reduce((n, a) => n + a.target_amount, 0), 2);
    expect(board.find((r) => r.scheme === "ghost_vendor")!.caught).toBe(1);
    expect(attacksNewestFirst(state)[0].day_launched).toBeGreaterThanOrEqual(attacksNewestFirst(state)[3].day_launched);
  });

  it("blue: verdict counts add up and the rule board ranks the busiest rule first", () => {
    const c = verdictCounts(state.verdicts);
    expect(c.allow + c.block + c.escalate).toBe(c.total);
    expect(c.block).toBeGreaterThan(0);
    const rules = ruleBoard(state.verdicts);
    expect(rules[0].total).toBeGreaterThanOrEqual(rules[rules.length - 1].total);
    expect(rules.some((r) => r.rule === "near_threshold")).toBe(true);
  });

  it("green: every gated attempt is a row, blocked ones included", () => {
    const rows = greenActions(state.verdicts, 60);
    expect(rows.length).toBeGreaterThan(5);
    expect(rows.every((r) => r.action.includes("."))).toBe(true);
    expect(rows.some((r) => r.verdict === "block")).toBe(true); // blocked attempts are on the tape too
    expect(rows[0].id).toBe(state.verdicts[state.verdicts.length - 1].verdict_id); // newest first
  });

  it("confusion: red verdicts that stopped it are true blocks, legit ones are false blocks, and so on", () => {
    const c = confusion([{ verdict: "block", origin: "red", n: 4 }, { verdict: "escalate", origin: "sim", n: 1 }, { verdict: "allow", origin: "red", n: 2 }, { verdict: "allow", origin: "sim", n: 90 }])!;
    expect(c).toEqual({ trueBlock: 4, falseBlock: 1, missed: 2, trueAllow: 90 });
    expect(confusion([])).toBeNull();
    expect(confusion(undefined)).toBeNull();
  });

  it("latency averages the verdicts that report one", () => {
    expect(avgLatency([{ latency_ms: 100 }, { latency_ms: 200 }, { latency_ms: null }, {}])).toBe(150);
    expect(avgLatency(undefined)).toBeNull();
  });

  it("narration and tool calls are per agent", () => {
    const s = reduce(reduce(initialState(), { id: 1, ts: "", episode_id: "e", day: 2, type: "agent.thinking", agent: "red", payload: { text: "hello " } }), { id: 2, ts: "", episode_id: "e", day: 2, type: "agent.thinking", agent: "red", payload: { text: "world" } });
    expect(thoughts(s, "red")).toEqual([{ key: "red:2", day: 2, text: "hello world" }]);
    expect(thoughts(s, "blue")).toEqual([]);
    expect(toolRows(s, "red")).toEqual([]);
  });
});
