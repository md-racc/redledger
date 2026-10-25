// The Evolution card's lead sentences say only what the scores say.
import { describe, expect, it } from "vitest";
import { evoLead, plainRationale, ruleWords, schemeTakes, takeLabel } from "./evoSummary";
import type { GenReport } from "./lineage";

const gen = (generation: number, stolen: number, blocked: number, demo = false) =>
  ({ generation, demo, score: { dollars_extracted: stolen, dollars_blocked: blocked } }) as unknown as GenReport;

describe("evoLead", () => {
  it("compares the first finished generation with the last", () => {
    const l = evoLead([gen(1, 3000, 2000), gen(2, 4000, 3000), gen(3, 15500, 5000)])!;
    expect(l.red).toBe("Red's take went up from $3,000 in generation 1 to $15,500 in generation 3.");
    expect(l.blue).toBe("Blue's blocked total went up from $2,000 in generation 1 to $5,000 in generation 3.");
  });

  it("says down when it went down, and stayed when it did not move", () => {
    const l = evoLead([gen(1, 9000, 0), gen(2, 1800, 0)])!;
    expect(l.red).toMatch(/went down from \$9,000 in generation 1 to \$1,800 in generation 2/);
    expect(l.blue).toBe("Blue's blocked total stayed at $0 from generation 1 to generation 2.");
  });

  it("leaves out the run being watched, which has no score yet", () => {
    const l = evoLead([gen(1, 3000, 2000), gen(2, 4000, 3000), gen(3, 0, 0, true)])!;
    expect(l.red).toContain("generation 2");
    expect(l.red).not.toContain("generation 3");
  });

  it("has nothing to compare with fewer than two finished generations", () => {
    expect(evoLead([])).toBeNull();
    expect(evoLead([gen(1, 3000, 2000)])).toBeNull();
    expect(evoLead([gen(1, 3000, 2000), gen(2, 0, 0, true)])).toBeNull();
  });
});

// generations 1 and 3 of the live showcase lineage (ln_f52a3df83c8d): `amount_extracted` is the older scoring, the headline is not
const mixGen = (stolen: number, mix: Record<string, [Record<string, number>, number]>) =>
  ({ score: { dollars_extracted: stolen }, red_mix: Object.fromEntries(Object.entries(mix).map(([id, [outcomes, amt]]) => [id, { launched: 1, outcomes, amount_extracted: amt, target_amount: amt }])) }) as unknown as GenReport;
const sum = (t: { stolen: number }[]) => t.reduce((s, x) => s + x.stolen, 0);

describe("schemeTakes", () => {
  it("adds up to the headline: the bank swap paid into the vendor's own account is not counted as stolen", () => {
    const g1 = mixGen(18533.65, { bank_swap: [{ partial: 1 }, 542.54], duplicate_invoice: [{ blocked: 1, extracted: 1, pending: 2 }, 4733.65], ghost_employee: [{ blocked: 1 }, 0], threshold_split: [{ extracted: 1 }, 13800] });
    const t = schemeTakes(g1);
    expect(sum(t)).toBeCloseTo(18533.65, 2);
    const by = Object.fromEntries(t.map((x) => [x.id, x]));
    expect(takeLabel(by.bank_swap!)).toBe("paid to the real vendor");
    expect(takeLabel(by.duplicate_invoice!)).toBe("stole $4,734");
    expect(takeLabel(by.threshold_split!)).toBe("stole $13,800");
    expect(takeLabel(by.ghost_employee!)).toBe("stopped");
  });

  it("generation 3: threshold split is the whole $79,237, the bank swap none of it", () => {
    const t = schemeTakes(mixGen(79236.81, { bank_swap: [{ partial: 2 }, 7273.27], threshold_split: [{ extracted: 6 }, 79236.81] }));
    expect(sum(t)).toBeCloseTo(79236.81, 2);
    expect(t.find((x) => x.id === "bank_swap")!.stolen).toBe(0);
  });

  it("leaves consistent amounts alone", () => {
    const t = schemeTakes(mixGen(3000, { ghost_vendor: [{ extracted: 1 }, 3000], duplicate_invoice: [{ blocked: 1 }, 0] }));
    expect(t.map((x) => x.stolen)).toEqual([3000, 0]);
  });

  it("with no exact match, caps the shares so they never exceed the total, and says so", () => {
    const t = schemeTakes(mixGen(1000, { a: [{ extracted: 1 }, 800], b: [{ partial: 1 }, 700] }));
    expect(sum(t)).toBe(1000);
    expect(t.map((x) => x.stolen)).toEqual([800, 200]);
    expect(takeLabel(schemeTakes(mixGen(500, { a: [{ extracted: 1 }, 800], b: [{ partial: 1 }, 700] }))[1]!)).toBe("not counted as lost");
  });

  it("$0 stolen means every chip says so", () => {
    const t = schemeTakes(mixGen(0, { bank_swap: [{ blocked: 1 }, 0], duplicate_invoice: [{ pending: 2 }, 0] }));
    expect(t.map(takeLabel)).toEqual(["stopped", "nothing taken"]);
  });
});

describe("plain words", () => {
  it("names controls by what they look for", () => {
    expect(ruleWords("vendor_age_lt_7d")).toBe("new vendors under 7 days old");
    expect(ruleWords("learned:young_vendor_any_amount")).toBe("any invoice from a new vendor");
    expect(ruleWords("learned:split_sibling")).toBe("split sibling");
  });

  it("turns the clerk's after-action counts into a sentence", () => {
    const aar = "Green AAR: fraud_paid=20, fraud_approved=0, fraud_blocked=2, fraud_rejected=0, legit_blocked=0. Procedural memory only; AP execution unchanged.";
    const s = plainRationale("green", aar, 79236.81);
    expect(s).toBe("The clerk paid 20 fraudulent items; 2 more were blocked. It keeps notes only; how it pays is unchanged.");
    expect(s).not.toMatch(/=|AAR|_/);
  });

  it("cannot contradict a $0 generation", () => {
    const s = plainRationale("green", "Green AAR: fraud_paid=1, fraud_approved=0, fraud_blocked=4, fraud_rejected=0, legit_blocked=0. Procedural memory only; AP execution unchanged.", 0);
    expect(s).toMatch(/paid 1 fraudulent item, but none of the money reached red/);
  });

  it("explains red's and blue's notes, and hides machine output", () => {
    expect(plainRationale("red", "Fold own disclosed attack outcomes; prefer schemes without a recent catch.", 1)).toMatch(/^Learned from how its attacks turned out/);
    expect(plainRationale("blue", "Retained 4 learned review controls; retired 0 controls with legitimate-item impact.", 1)).toBe("Kept its 4 learned controls; switched none off.");
    expect(plainRationale("blue", "ghost_vendor got past me", 1)).toBe("ghost vendor got past me");
    expect(plainRationale("red", "weights={a: 1}", 1)).toBe("rewrote its playbook");
  });
});
