// The Evolution card's lead sentences say only what the scores say.
import { describe, expect, it } from "vitest";
import { evoLead } from "./evoSummary";
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
