import { describe, expect, it } from "vitest";
import { buildNavGrid } from "./nav";
import { ArenaSim } from "./sim";
import { Director } from "./director";
import { ROSTER, greenIdFor, blueIdForRule, guardForRule } from "./roster";
import { buildDetails, formatValue } from "./details";
import { initialState, reduce } from "../reducer";
import type { RLEvent } from "../types";

const ev = (id: number, type: string, payload: Record<string, unknown>, day = 0, agent: RLEvent["agent"] = "battlefield"): RLEvent => ({ id, ts: "2026-10-24T00:00:00Z", episode_id: "ep_test", day, type, agent, payload });
const run = (sim: ArenaSim, s: number) => { for (let i = 0; i < s * 30; i++) sim.update(1 / 30); };

describe("director", () => {
  const make = () => {
    const sim = new ArenaSim(ROSTER, buildNavGrid(), 3);
    return { sim, dir: new Director(sim, () => 0) };
  };

  it("converges on episode.started", () => {
    const { sim, dir } = make();
    dir.handle(ev(1, "episode.started", { controller_mode: "enforce", days: 4, seed: 1 }));
    expect(sim.phase).toBe("converging");
  });

  it("maps attack.launched to the red agent of that scheme and holds it until the outcome", () => {
    const { sim, dir } = make();
    dir.handle(ev(1, "episode.started", {}));
    run(sim, 60);
    dir.handle(ev(2, "attack.launched", { attack_id: "atk_a", scheme_id: "bank_swap", display_name: "Bank Account Swap", story: "", target_amount: 7000 }));
    run(sim, 30);
    const sc = sim.scenes.find((s) => s.attackId === "atk_a")!;
    expect(sc.redId).toBe("red:bank_swap");
    expect(sc.greenId).toBe(greenIdFor("atk_a"));
    expect(sc.stage).toBe("pitch");
    dir.handle(ev(3, "gate.verdict", { verdict_id: "vd_1", agent: "green", action: "invoices.pay", verdict: "block", reason: "x", rules_fired: ["recent_bank_change"], enforced: true }));
    dir.handle(ev(4, "attack.outcome", { attack_id: "atk_a", scheme_id: "bank_swap", outcome: "blocked", amount_extracted: 0, detected_day: 0 }));
    expect(sim.scenes.find((s) => s.attackId === "atk_a")!.guardId).toBe("blue:recent_bank_change");
    run(sim, 30);
    expect(sim.scenes.length).toBe(0);
  });

  it("copes with an outcome for an attack it never saw launch", () => {
    const { sim, dir } = make();
    dir.handle(ev(1, "episode.started", {}));
    run(sim, 60);
    dir.handle(ev(2, "attack.outcome", { attack_id: "atk_late", scheme_id: "ghost_vendor", outcome: "extracted", amount_extracted: 1200, detected_day: null }));
    expect(sim.scenes.some((s) => s.attackId === "atk_late" && s.outcome === "extracted")).toBe(true);
  });

  it("freezes the client bound to a vendor", () => {
    const { sim, dir } = make();
    dir.handle(ev(1, "vendor.frozen", { vendor_id: "ven_123" }));
    expect(sim.agents.get(greenIdFor("ven_123"))!.status).toBe("frozen");
    dir.handle(ev(2, "vendor.unfrozen", { vendor_id: "ven_123" }));
    expect(sim.agents.get(greenIdFor("ven_123"))!.status).toBe("ok");
  });

  it("maps rule ids, including aliases and unknown ids, to a guard", () => {
    expect(blueIdForRule("no_hr_record")).toBe("blue:employee_bank_matches_vendor");
    expect(blueIdForRule("duplicate_amount_match")).toBe("blue:duplicate_invoice");
    expect(blueIdForRule("totally_new_rule")).toBeNull();
    expect(guardForRule("totally_new_rule")).toMatch(/^blue:/);
  });
});

describe("agent details", () => {
  it("shows placeholders that name their source before any data arrives", () => {
    const d = buildDetails("red:ghost_vendor", initialState())!;
    expect(d.placeholder).toBe(true);
    const impact = d.sections[0].fields.find((f) => f.key === "expected_impact")!;
    expect(formatValue(impact)).toBeNull();
    expect(impact.source).toContain("/schemes");
  });

  it("fills red stats from the event stream", () => {
    let s = initialState();
    s = reduce(s, ev(1, "episode.started", { controller_mode: "enforce", days: 4, seed: 1 }));
    s = reduce(s, ev(2, "attack.launched", { attack_id: "a1", scheme_id: "ghost_vendor", display_name: "Ghost Vendor", story: "A story.", target_amount: 4920 }));
    s = reduce(s, ev(3, "attack.outcome", { attack_id: "a1", scheme_id: "ghost_vendor", outcome: "blocked", amount_extracted: 0, detected_day: 0 }));
    const d = buildDetails("red:ghost_vendor", s)!;
    const field = (k: string) => d.sections.flatMap((x) => x.fields).find((f) => f.key === k)!;
    expect(formatValue(field("attempts"))).toBe("1");
    expect(formatValue(field("targeted"))).toBe("$4,920");
    expect(formatValue(field("caught"))).toBe("1");
    expect(d.status).toEqual({ label: "blocked", tone: "ok" });
    expect(d.story).toBe("A story.");
  });

  it("counts a guard's verdicts and applies host overrides", () => {
    let s = initialState();
    s = reduce(s, ev(1, "episode.started", { controller_mode: "enforce", days: 4, seed: 1 }));
    s = reduce(s, ev(2, "gate.verdict", { verdict_id: "v1", agent: "green", action: "invoices.pay", verdict: "block", reason: "dup", rules_fired: ["duplicate_invoice"], enforced: true, amount: 900 }, 0, "blue"));
    const d = buildDetails("blue:duplicate_invoice", s, {}, { "blue:duplicate_invoice": { title: "Dup Guard", fields: { fired: 99 } } })!;
    expect(d.title).toBe("Dup Guard");
    const f = d.sections.flatMap((x) => x.fields);
    expect(formatValue(f.find((x) => x.key === "fired")!)).toBe("99");
    expect(formatValue(f.find((x) => x.key === "blocked_amount")!)).toBe("$900");
  });

  it("binds a client slot to a catalog vendor", () => {
    const d = buildDetails("green:client_01", initialState(), { vendors: [{ id: "ven_x", name: "Acme Freight", category: "logistics", risk_score: 12 }] })!;
    expect(d.title).toBe("Acme Freight");
    expect(formatValue(d.sections[1].fields.find((f) => f.key === "risk")!)).toBe("12");
  });
});

describe("ledger tallies", () => {
  it("counts allows, blocks and stolen dollars per day", async () => {
    const { tallyDays } = await import("./ledgerStats");
    let s = initialState();
    expect(tallyDays(s)).toEqual([]);
    s = reduce(s, ev(1, "episode.started", { controller_mode: "enforce", days: 4, seed: 1 }));
    s = reduce(s, ev(2, "gate.verdict", { verdict_id: "a", agent: "green", action: "x", verdict: "allow", reason: "", rules_fired: [], enforced: true }, 0));
    s = reduce(s, ev(3, "gate.verdict", { verdict_id: "b", agent: "green", action: "x", verdict: "block", reason: "", rules_fired: ["near_threshold"], enforced: true }, 1));
    s = reduce(s, ev(4, "attack.launched", { attack_id: "k", scheme_id: "ghost_vendor", display_name: "g", story: "", target_amount: 100 }, 1));
    s = reduce(s, ev(5, "attack.outcome", { attack_id: "k", scheme_id: "ghost_vendor", outcome: "extracted", amount_extracted: 250, detected_day: null }, 1));
    const t = tallyDays(s);
    expect(t.map((x) => [x.day, x.allow, x.block, x.stolen])).toEqual([[0, 1, 0, 0], [1, 0, 1, 250]]);
  });
});
