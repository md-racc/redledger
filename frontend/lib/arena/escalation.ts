// Turns an open escalation into words anyone can follow. Owner: Dev R.
//
// The backend sends an action id (`invoices.pay`), an amount and a reason built for developers ("Needs human review:
// vendor_age_lt_7d, near_threshold."). The card a judge has to answer in a few seconds needs three things instead: what is about
// to happen, why the controller stopped it, and what each button does. Pure, tested.
import type { Escalation, VerdictCard } from "@/lib/types";
import { money } from "./headlines";

export interface EscalationExplained {
  /** the question, as a heading: "Pay this invoice?" */
  title: string;
  /** what is about to happen, one sentence */
  what: string;
  /** why the controller did not just allow or block it: one short plain reason per rule that fired */
  why: string[];
  /** the two buttons: a label and what it does */
  approve: { label: string; result: string };
  block: { label: string; result: string };
}

/** What each gated action means, and what the money does if it is let through. */
interface ActionWords {
  /** "pay an invoice" */
  doing: string;
  /** the question */
  title: string;
  /** does money leave the company if it goes ahead? */
  moneyOut: boolean;
  approve: string;
  block: string;
}

const ACTIONS: Record<string, ActionWords> = {
  "invoices.pay": { doing: "pay an invoice", title: "Pay this invoice?", moneyOut: true, approve: "the payment is sent", block: "nothing is paid" },
  "invoices.approve": { doing: "approve an invoice", title: "Approve this invoice?", moneyOut: true, approve: "the invoice is cleared to be paid", block: "the invoice is held back" },
  "invoices.match": { doing: "match an invoice to its purchase order", title: "Match this invoice?", moneyOut: false, approve: "the invoice is matched and moves on", block: "the invoice stays unmatched" },
  "invoices.reject": { doing: "reject an invoice", title: "Reject this invoice?", moneyOut: false, approve: "the invoice is rejected", block: "the invoice stays open" },
  "expenses.pay": { doing: "reimburse an expense claim", title: "Reimburse this expense?", moneyOut: true, approve: "the reimbursement is sent", block: "nothing is paid" },
  "expenses.approve": { doing: "approve an expense claim", title: "Approve this expense?", moneyOut: true, approve: "the claim is cleared to be paid", block: "the claim is held back" },
  "vendor_changes.approve": { doing: "accept new bank details for a vendor", title: "Accept the new bank details?", moneyOut: true, approve: "later payments go to the new account", block: "the old account stays" },
  "vendor_changes.reject": { doing: "turn down a vendor's change request", title: "Turn down this change?", moneyOut: false, approve: "the request is turned down", block: "the request stays open" },
  "gl.post": { doing: "post an entry to the books", title: "Post this entry?", moneyOut: false, approve: "the entry is posted", block: "the books stay as they are" },
};

/** Why each rule makes the controller stop and ask, in plain words. */
const WHY: Record<string, string> = {
  vendor_age_lt_7d: "The vendor was only added in the last week, and this is over $1,000.",
  near_threshold: "The amount sits just under the limit where bills are approved without a look, a common way to slip a payment past review.",
  duplicate_invoice: "This vendor was already paid this exact amount, so it may be a double payment.",
  recent_bank_change: "The vendor's bank account changed recently, right before a large payment.",
  bank_change_with_open_invoices: "Someone asked to change the vendor's bank account while bills to them are still unpaid.",
  no_po_from_po_vendor: "This vendor always sends a purchase order, and this bill has none.",
  over_po_amount: "The bill is more than 10% above what was ordered.",
  recurring_drift: "The amount is well above what this vendor normally charges.",
  employee_bank_matches_vendor: "The payee's bank account matches a vendor's, or there is no HR record for them: it could be a made-up employee.",
  already_flagged_high: "The auditor has already marked this one as high risk.",
};
const ALIAS: Record<string, string> = {
  no_hr_record: "employee_bank_matches_vendor",
  already_flagged: "already_flagged_high",
  duplicate_amount_match: "duplicate_invoice",
  bank_change_requested: "recent_bank_change",
};

/** Why one rule makes the controller stop, in plain words; null for a rule this file does not know. */
export const ruleWhy = (rule: string): string | null => WHY[ALIAS[rule] ?? rule] ?? null;

const pretty = (id: string) => id.replace(/^[a-z_]*:/, "").replace(/[._]/g, " ");

export function explainEscalation(esc: Pick<Escalation, "action" | "amount" | "reason">, verdict?: Pick<VerdictCard, "rules_fired" | "reason"> | null): EscalationExplained {
  const w: ActionWords = ACTIONS[esc.action] ?? { doing: pretty(esc.action), title: "Allow this?", moneyOut: false, approve: "it goes ahead", block: "it is stopped" };
  const amount = money(esc.amount);
  const rules = verdict?.rules_fired ?? [];
  const why: string[] = [];
  for (const r of rules) {
    const text = WHY[ALIAS[r] ?? r];
    if (text && !why.includes(text)) why.push(text);
  }
  if (!why.length) {
    // no rule we know: the controller's own sentence is the best there is, unless it is the placeholder the stand-ins send
    const own = verdict?.reason || (/^Needs human review/i.test(esc.reason) ? "" : esc.reason);
    why.push(own || "The controller could not tell whether this is safe, so it is asking a person.");
  }
  const sum = amount ? ` for ${amount}` : "";
  const lost = w.moneyOut && amount ? ` If it is fraud, ${amount} is gone.` : w.moneyOut ? " If it is fraud, the money is gone." : "";
  const kept = w.moneyOut ? " If it was a real bill, the vendor has to wait." : "";
  return {
    title: w.title,
    what: `The finance clerk wants to ${w.doing}${sum}. The controller is not sure it is safe, so it is asking you.`,
    why,
    approve: { label: "Approve", result: `${cap(w.approve)}.${lost}` },
    block: { label: "Block", result: `${cap(w.block)}.${kept}` },
  };
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
