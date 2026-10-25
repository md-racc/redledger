// The Evolution card's words and numbers: the two lead sentences (what red got away with, what blue stopped, first generation to
// last), per-scheme amounts that add up to the headline, and plain words for controls and playbook notes. Pure, tested
// (evoSummary.test.ts). Nothing is estimated: each figure is one the battlefield reported. Owner: Dev R.
import { money } from "./headlines";
import type { GenReport } from "./lineage";

const usd = (n: number) => money(n) || "$0";

export interface EvoLead {
  red: string;
  blue: string;
}

function trend(who: string, what: string, a: number, b: number, from: number, to: number): string {
  const span = `generation ${from} to generation ${to}`;
  if (a === b) return `${who} ${what} stayed at ${usd(a)} from ${span}.`;
  return `${who} ${what} went ${b > a ? "up" : "down"} from ${usd(a)} in generation ${from} to ${usd(b)} in generation ${to}.`;
}

/** Null with fewer than two finished generations to compare (the run being watched has no score of its own yet). */
export function evoLead(gens: GenReport[]): EvoLead | null {
  const done = gens.filter((g) => !g.demo);
  if (done.length < 2) return null;
  const first = done[0]!, last = done[done.length - 1]!;
  return {
    red: trend("Red's", "take", first.score.dollars_extracted, last.score.dollars_extracted, first.generation, last.generation),
    blue: trend("Blue's", "blocked total", first.score.dollars_blocked, last.score.dollars_blocked, first.generation, last.generation),
  };
}

// ---- per-scheme amounts that add up to the headline ------------------------------------------------------------------
//
// The lineage report's `score.dollars_extracted` counts money as lost only when it reached an account the attacker controls.
// `red_mix[*].amount_extracted` is older scoring: it also counts money that was paid out but landed in a real party's
// account (a bank swap paid into the vendor's own account). So the per-scheme amounts can sum to more than the total, and the
// report carries no per-scheme figure on the new scoring. `schemeTakes` reconciles the two: it finds the schemes whose
// amounts make up the total exactly (to the cent) and shows the others as paid but not lost; if no combination matches it
// hands out the total in order (fully extracted schemes first), capped, so the chips never sum to more than the headline.

export interface SchemeTake {
  id: string;
  launched: number;
  /** this scheme's share of the generation's headline loss; the shares never sum to more than it */
  stolen: number;
  /** money moved (old scoring) but none of it counts as lost: `exact` when the total pins that down, else `capped` */
  notLost: "exact" | "capped" | null;
  /** at least one attempt was blocked or flagged */
  stopped: boolean;
}

const cents = (n: number) => Math.round(n * 100);

export function schemeTakes(g: Pick<GenReport, "red_mix" | "score">): SchemeTake[] {
  const rows = Object.entries(g.red_mix ?? {}).map(([id, m]) => ({ id, m, amount: Math.max(0, Number(m.amount_extracted) || 0) }));
  const total = Math.max(0, Number(g.score?.dollars_extracted) || 0);
  const take = (stolen: (i: number) => number, notLost: "exact" | "capped"): SchemeTake[] =>
    rows.map((r, i) => {
      const s = stolen(i);
      return { id: r.id, launched: r.m.launched, stolen: s, notLost: r.amount > 0 && s === 0 ? notLost : null, stopped: ["blocked", "flagged", "caught"].some((k) => (r.m.outcomes?.[k] ?? 0) > 0) };
    });
  if (rows.reduce((s, r) => s + cents(r.amount), 0) <= cents(total)) return take((i) => rows[i]!.amount, "exact");

  // fully extracted schemes are the likeliest to have reached red: among combinations that match, keep the most of them
  const full = (i: number) => (rows[i]!.m.outcomes?.extracted ?? 0) > 0;
  const paid = rows.map((_, i) => i).filter((i) => rows[i]!.amount > 0);
  let best: { mask: number; cost: number } | null = null;
  if (paid.length <= 16) {
    for (let mask = 0; mask < 1 << paid.length; mask++) {
      let s = 0, cost = 0;
      paid.forEach((i, b) => { if (mask & (1 << b)) s += cents(rows[i]!.amount); else cost += full(i) ? 10 : 1; });
      if (s === cents(total) && (!best || cost < best.cost)) best = { mask, cost };
    }
  }
  if (best) {
    const mask = best.mask;
    const kept = new Set(paid.filter((_, b) => mask & (1 << b)));
    return take((i) => (kept.has(i) ? rows[i]!.amount : 0), "exact");
  }
  const order = [...paid].sort((a, b) => Number(full(b)) - Number(full(a)) || rows[b]!.amount - rows[a]!.amount);
  const share = new Map<number, number>();
  let left = total;
  for (const i of order) { const s = Math.min(rows[i]!.amount, left); share.set(i, s); left -= s; }
  return take((i) => share.get(i) ?? 0, "capped");
}

/** What a scheme chip says about the money, in words. */
export function takeLabel(t: SchemeTake): string {
  if (t.stolen > 0) return `stole ${usd(t.stolen)}`;
  if (t.notLost === "exact") return "paid to the real vendor";
  if (t.notLost === "capped") return "not counted as lost";
  return t.stopped ? "stopped" : "nothing taken";
}

// ---- plain words for controls and playbook notes ---------------------------------------------------------------------

/** What each of blue's controls looks for, short enough for a list. Rule ids: blue/gate/rules.py and blue/gate/learned.py. */
const RULE_WORDS: Record<string, string> = {
  vendor_age_lt_7d: "new vendors under 7 days old",
  near_threshold: "amounts just under the approval limit",
  threshold_split: "invoices split to stay under the limit",
  invoice_threshold_split: "invoices split to stay under the limit",
  duplicate_invoice: "duplicate invoices",
  duplicate_amount_match: "amounts matching a paid invoice",
  po_vendor_mismatch: "purchase orders from another vendor",
  invalid_po: "cancelled purchase orders",
  over_po_amount: "invoices over their purchase order",
  no_po_from_po_vendor: "missing purchase orders",
  recurring_drift: "recurring amounts creeping up",
  recent_bank_change: "payments soon after a bank change",
  bank_change_with_open_invoices: "bank changes with invoices open",
  bank_change_requested: "bank change requests",
  unverified_vendor_exposure: "unverified vendors",
  employee_bank_matches_vendor: "employees sharing a vendor's bank account",
  no_hr_record: "employees with no HR record",
  inactive_employee: "inactive employees",
  vendor_frozen: "frozen vendors",
  already_flagged_high: "items already flagged",
  already_flagged: "items already flagged",
  "learned:young_vendor_any_amount": "any invoice from a new vendor",
  "learned:near_threshold_wide": "a wider just-under-the-limit band",
  "learned:duplicate_amount_loose": "near-duplicate amounts",
  "learned:bank_change_any_amount": "any payment after a bank change",
  "learned:verification_unavailable": "vendors it could not verify",
};

/** A control id as words: "vendor_age_lt_7d" → "new vendors under 7 days old"; unknown ids are de-snaked. */
export const ruleWords = (id: string): string => RULE_WORDS[id] ?? id.replace(/^learned:/, "").replace(/^evolved:/, "").replace(/_/g, " ");

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/**
 * A playbook note's rationale in plain words. The agents write these for themselves ("Green AAR: fraud_paid=20, …"); the card
 * says what they mean. `stolen` is the generation's headline loss, so the clerk's line cannot contradict a $0.
 */
export function plainRationale(agent: "red" | "green" | "blue", rationale: string, stolen: number): string {
  const t = (rationale ?? "").trim();
  const num = (k: string) => { const m = new RegExp(`\\b${k}=(\\d+)`).exec(t); return m ? Number(m[1]) : null; };
  if (agent === "green" && /fraud_paid=\d/.test(t)) {
    const paid = num("fraud_paid") ?? 0, blocked = (num("fraud_blocked") ?? 0) + (num("fraud_rejected") ?? 0), legit = num("legit_blocked") ?? 0;
    const parts = [paid === 0 ? "The clerk paid no fraudulent items" : `The clerk paid ${plural(paid, "fraudulent item")}${stolen > 0 ? "" : ", but none of the money reached red"}`];
    if (blocked > 0) parts.push(`${blocked} more ${blocked === 1 ? "was" : "were"} blocked`);
    if (legit > 0) parts.push(`${plural(legit, "real invoice")} ${legit === 1 ? "was" : "were"} held up`);
    return `${parts.join("; ")}. It keeps notes only; how it pays is unchanged.`;
  }
  if (agent === "blue") {
    const m = /Retained (\d+) learned review controls?; retired (\d+)/i.exec(t);
    if (m) {
      const kept = Number(m[1]), off = Number(m[2]);
      return `Kept its ${plural(kept, "learned control")}; ${off === 0 ? "switched none off" : `switched ${off} off for catching real invoices`}.`;
    }
  }
  if (agent === "red" && /fold own disclosed attack outcomes/i.test(t)) return "Learned from how its attacks turned out; favours schemes that haven't been caught lately.";
  // empty, or machine output (key=value pairs, JSON): say only that it changed
  if (!t || /\w=\d|[{}[\]]/.test(t)) return "rewrote its playbook";
  return t.replace(/_/g, " ");
}
