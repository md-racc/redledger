import { describe, expect, it } from "vitest";
import { initialState } from "../reducer";
import type { UIState } from "../types";
import { daySummary, reportDays, reportText } from "./report";

const base = (): UIState => initialState();

describe("report text", () => {
  it("finds the markdown whatever the field is called, and says null when there is none", () => {
    expect(reportText({ markdown: "# Day 1" })).toBe("# Day 1");
    expect(reportText({ content: "x" })).toBe("x");
    expect(reportText({ body: "y" })).toBe("y");
    expect(reportText("  plain  ")).toBe("plain");
    expect(reportText({ markdown: "   " })).toBeNull();
    expect(reportText(null)).toBeNull();
    expect(reportText({ id: "r1", day: 2 })).toBeNull();
  });
});

describe("report days", () => {
  it("lists one report per day, oldest first, newest report winning", () => {
    const s = base();
    s.reports = [{ report_id: "r3", day: 3 }, { report_id: "r1", day: 1 }, { report_id: "r1b", day: 1 }];
    expect(reportDays(s)).toEqual([{ day: 1, report_id: "r1b" }, { day: 3, report_id: "r3" }]);
    expect(reportDays(base())).toEqual([]);
  });
});

describe("a day's summary from the events", () => {
  it("counts what happened that day and nothing from other days", () => {
    const s = base();
    s.verdicts = [
      { verdict_id: "v1", day: 2, agent: "green", action: "invoices.pay", verdict: "allow", reason: "ok", rules_fired: [], enforced: true },
      { verdict_id: "v2", day: 2, agent: "green", action: "invoices.pay", verdict: "block", reason: "Bank details changed 3 days ago", amount: 4380, rules_fired: ["recent_bank_change"], enforced: true },
      { verdict_id: "v3", day: 2, agent: "green", action: "vendor_changes.approve", verdict: "escalate", reason: "Bank change on a vendor with open invoices", rules_fired: [], enforced: true },
      { verdict_id: "v4", day: 5, agent: "green", action: "invoices.pay", verdict: "block", reason: "other day", rules_fired: [], enforced: true },
    ];
    s.attacks = {
      a1: { attack_id: "a1", scheme_id: "bank_swap", display_name: "Bank Account Swap", story: "", target_amount: 4380, day_launched: 2, outcome: "blocked", amount_extracted: 0, detected_day: 2 },
      a2: { attack_id: "a2", scheme_id: "ghost_vendor", display_name: "Ghost Vendor", story: "", target_amount: 4380, day_launched: 2, outcome: "extracted", amount_extracted: 4380, detected_day: null },
      a3: { attack_id: "a3", scheme_id: "ghost_vendor", display_name: "Ghost Vendor", story: "", target_amount: 100, day_launched: 4, outcome: "extracted", amount_extracted: 100, detected_day: null },
    };
    s.flags = [{ flag_id: "f1", day: 2, entity_type: "vendor", entity_id: "v9", severity: "high", reason: "New vendor, large invoice" }];
    const md = daySummary(s, 2);
    expect(md).toContain("# Day 2");
    expect(md).toContain("**Payments judged:** 3 (1 allowed, 1 blocked, 1 sent to a person)");
    expect(md).toContain("**Fraud attempts:** 2: 1 stopped, 1 got through ($4,380)");
    expect(md).toContain("**Flags raised:** 1");
    expect(md).toContain("high: New vendor, large invoice");
    expect(md).toContain("Blocked ($4,380): Bank details changed 3 days ago");
    expect(md).toContain("Sent to a person: Bank change on a vendor with open invoices");
    expect(md).not.toContain("other day");
  });

  it("says plainly when nothing happened", () => {
    const md = daySummary(base(), 1);
    expect(md).toContain("**Payments judged:** 0");
    expect(md).toContain("**Fraud attempts:** none today");
    expect(md).toContain("**Flags raised:** 0");
  });

  it("is itself valid input for the markdown reader", async () => {
    const { parseMarkdown } = await import("../markdown");
    const blocks = parseMarkdown(daySummary(base(), 1));
    expect(blocks[0]).toEqual({ t: "h", level: 1, text: "Day 1" });
    expect(blocks.some((b) => b.t === "ul")).toBe(true);
  });
});
