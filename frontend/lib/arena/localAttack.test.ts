import { describe, expect, it } from "vitest";
import { initialState, reduce } from "../reducer";
import type { ControllerMode, RLEvent } from "../types";
import { cardFor } from "./headlines";
import { localAttack } from "./localAttack";
import { ScriptRunner } from "./script";

const play = (scheme: string, mode: ControllerMode, decision?: "approve" | "block") => {
  const a = localAttack({ scheme, mode, day: 2, episodeId: "ep_t", seq: 1, holdMs: 5000 });
  const out: RLEvent[] = [];
  let state = initialState();
  const r = new ScriptRunner(a.items, (e) => { out.push(e); state = reduce(state, e); }, { decisions: {}, getScore: () => state.score });
  for (let t = 0; t < 60_000 && !r.done; t += 100) {
    r.advance(100);
    if (decision && a.escalationId && r.holding && !r.ctx.decisions[a.escalationId]) r.ctx.decisions[a.escalationId] = decision;
  }
  return { out, state, a };
};

describe("judge-picked attacks without a backend", () => {
  it("controller off: no gate, the money leaves", () => {
    const { out, state } = play("ghost_vendor", "off");
    expect(out.some((e) => e.type === "gate.verdict")).toBe(false);
    expect(state.score.dollars_extracted).toBe(4920);
    expect(state.score.dollars_blocked).toBe(0);
    expect(state.score.attacks_caught).toBe(0);
  });

  it("shadow: the gate says what it would block, and nothing is stopped", () => {
    const { out, state } = play("duplicate_invoice", "shadow");
    const v = out.find((e) => e.type === "gate.verdict")!;
    expect((v.payload as any).enforced).toBe(false);
    expect(cardFor(v)!.tag).toBe("WOULD BLOCK");
    expect(state.score.dollars_extracted).toBeCloseTo(4004.24, 2);
  });

  it("enforce: the gate blocks it", () => {
    const { state } = play("bank_swap", "enforce");
    expect(state.score.dollars_extracted).toBe(0);
    expect(state.score.dollars_blocked).toBe(8400);
    expect(state.score.attacks_caught).toBe(1);
    expect(Object.values(state.attacks)[0].outcome).toBe("blocked");
  });

  it("enforce, near-threshold: a human decides. Block keeps the money, approve lets that invoice through", () => {
    const blocked = play("threshold_split", "enforce", "block");
    expect(blocked.a.escalationId).toBe("esc_you_1");
    expect(blocked.state.score.dollars_extracted).toBe(0);
    expect(blocked.state.score.dollars_blocked).toBe(14400);
    const approved = play("threshold_split", "enforce", "approve");
    expect(approved.state.score.dollars_extracted).toBe(4800);
    expect(approved.state.score.dollars_blocked).toBe(14400 - 4800);
    expect(Object.values(approved.state.attacks)[0].outcome).toBe("partial");
  });

  it("enforce, nobody answers: the hold times out into a block", () => {
    const { state, out } = play("threshold_split", "enforce");
    expect(out.filter((e) => e.type === "escalation.resolved")).toHaveLength(1);
    expect(state.score.dollars_extracted).toBe(0);
  });

  it("enforce, a drift attack slips past the gate and is only flagged afterwards", () => {
    const { out, state } = play("amount_drift", "enforce");
    expect(out.some((e) => e.type === "flag.raised")).toBe(true);
    expect(state.score.dollars_extracted).toBe(Math.round(2100 * 0.6));
    expect(Object.values(state.attacks)[0].outcome).toBe("partial");
  });
});
