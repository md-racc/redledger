import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { RLEvent } from "../types";
import { cardFor } from "./headlines";

const fixture: RLEvent[] = readFileSync("public/mocks/sample.jsonl", "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l));
const ev = (type: string, payload: Record<string, unknown>, agent: RLEvent["agent"] = "battlefield"): RLEvent => ({ id: 1, ts: "", episode_id: "x", day: 1, type, agent, payload });

describe("feed headlines", () => {
  it("every card the recorded episode produces has a tag and a headline, and quiet events make none", () => {
    const cards = fixture.map(cardFor).filter(Boolean);
    expect(cards.length).toBeGreaterThan(10);
    for (const c of cards) { expect(c!.tag.length).toBeGreaterThan(0); expect(c!.head.length).toBeGreaterThan(0); }
    expect(fixture.filter((e) => e.type === "ledger.mutation").map(cardFor).every((c) => c === null)).toBe(true);
    expect(fixture.filter((e) => e.type === "gate.verdict" && (e.payload as any).verdict === "allow").every((e) => cardFor(e) === null)).toBe(true);
  });

  it("ties a block to the guard that fired and an attack to its fraudster, so a click can find them", () => {
    const block = cardFor(ev("gate.verdict", { verdict: "block", enforced: true, action: "invoices.approve", amount: 4920, rules_fired: ["vendor_age_lt_7d", "near_threshold"] }, "blue"))!;
    expect(block.tone).toBe("blue");
    expect(block.agentId).toBe("blue:vendor_age_lt_7d");
    expect(block.head).toContain("$4,920");
    const attack = cardFor(ev("attack.launched", { attack_id: "a", scheme_id: "ghost_vendor", display_name: "Ghost Vendor", story: "s", target_amount: 100 }))!;
    expect(attack.agentId).toBe("red:ghost_vendor");
    expect(attack.tone).toBe("red");
  });

  it("says plainly who decided an escalation", () => {
    expect(cardFor(ev("escalation.resolved", { escalation_id: "e", decision: "approve", by: "judge" }, "human"))!.tone).toBe("red");
    expect(cardFor(ev("escalation.resolved", { escalation_id: "e", decision: "block", by: "judge" }, "human"))!.head).toMatch(/blocked/);
    expect(cardFor(ev("escalation.resolved", { escalation_id: "e", decision: "timeout", by: "system" }))!.tag).toBe("TIMEOUT");
  });

  it("a shadow verdict reads as a would-have, not a block", () => {
    const c = cardFor(ev("gate.verdict", { verdict: "block", enforced: false, action: "invoices.pay", amount: 1000, rules_fired: ["near_threshold"] }, "blue"))!;
    expect(c.tag).toBe("WOULD BLOCK");
    expect(c.head).toContain("would have stopped");
  });
});
