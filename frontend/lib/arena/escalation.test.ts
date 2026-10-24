import { describe, expect, it } from "vitest";
import { explainEscalation } from "./escalation";

describe("the escalation card in plain words", () => {
  it("says what is about to happen, why it stopped, and what each button does", () => {
    const x = explainEscalation(
      { action: "invoices.pay", amount: 4800, reason: "Needs human review: vendor_age_lt_7d, near_threshold." },
      { rules_fired: ["vendor_age_lt_7d", "near_threshold"], reason: "young vendor + near threshold" },
    );
    expect(x.title).toBe("Pay this invoice?");
    expect(x.what).toBe("The finance clerk wants to pay an invoice for $4,800. The controller is not sure it is safe, so it is asking you.");
    expect(x.why).toHaveLength(2);
    expect(x.why[0]).toMatch(/only added in the last week/);
    expect(x.approve.result).toBe("The payment is sent. If it is fraud, $4,800 is gone.");
    expect(x.block.result).toBe("Nothing is paid. If it was a real bill, the vendor has to wait.");
  });

  it("never shows a developer id or the stand-in placeholder", () => {
    const all = JSON.stringify(explainEscalation({ action: "invoices.approve", amount: 14400, reason: "Needs human review: near_threshold." }, { rules_fired: ["near_threshold", "made_up_rule"], reason: "" }));
    expect(all).not.toMatch(/invoices\.approve|near_threshold|made_up_rule|Needs human review/);
  });

  it("knows the same rule under its other names, and lists each reason once", () => {
    const x = explainEscalation({ action: "invoices.pay", amount: 100, reason: "" }, { rules_fired: ["duplicate_amount_match", "duplicate_invoice"], reason: "" });
    expect(x.why).toEqual(["This vendor was already paid this exact amount, so it may be a double payment."]);
  });

  it("uses the controller's own sentence when no rule is known, and a plain fallback when there is none", () => {
    expect(explainEscalation({ action: "gl.post", amount: 0, reason: "Needs human review: x." }, { rules_fired: ["x"], reason: "Posting looks odd for a Sunday." }).why).toEqual(["Posting looks odd for a Sunday."]);
    expect(explainEscalation({ action: "gl.post", amount: 0, reason: "Needs human review: x." }, null).why[0]).toMatch(/could not tell whether this is safe/);
    expect(explainEscalation({ action: "gl.post", amount: 0, reason: "Entry exceeds the weekly limit." }, null).why).toEqual(["Entry exceeds the weekly limit."]);
  });

  it("handles actions that do not move money, and ones it has never heard of", () => {
    const books = explainEscalation({ action: "gl.post", amount: null, reason: "" }, null);
    expect(books.what).toBe("The finance clerk wants to post an entry to the books. The controller is not sure it is safe, so it is asking you.");
    expect(books.approve.result).not.toMatch(/gone/);
    const odd = explainEscalation({ action: "payroll.run_special", amount: 900, reason: "" }, null);
    expect(odd.what).toContain("payroll run special for $900");
    expect(odd.title).toBe("Allow this?");
  });

  it("explains a bank-detail change as that, not as a payment", () => {
    const x = explainEscalation({ action: "vendor_changes.approve", amount: null, reason: "" }, { rules_fired: ["bank_change_requested"], reason: "" });
    expect(x.title).toBe("Accept the new bank details?");
    expect(x.approve.result).toMatch(/later payments go to the new account/i);
    expect(x.why[0]).toMatch(/bank account changed recently/);
  });
});
