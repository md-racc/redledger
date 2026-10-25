// The 30 agents of the arena and their backend identities. Owner: Dev R.
//
//   red   = fraudsters. One per scheme in the red catalog (README §8). id key = scheme_id, the same string
//           that arrives in `attack.launched.payload.scheme_id`.
//   blue  = guards. One per gate rule in blue/gate/rules.py (README §9). id key = rule id, the same string
//           that arrives in `gate.verdict.payload.rules_fired[]`.
//   green = clients / victims. Slots for the synthetic company's counterparties. They are bound to real vendors
//           by the director (lib/arena/director.ts) as vendor/attack events arrive.
import type { AgentSpec, Team } from "./types";

export const TEAMS: Team[] = ["red", "blue", "green"];

export const TEAM_META: Record<Team, { label: string; singular: string; role: string; hex: string; glow: string; tagline: string }> = {
  red: { label: "Fraudsters", singular: "Fraudster", role: "Red team", hex: "#ff2e49", glow: "#ff5a6e", tagline: "Eight on the wall, a scheme built for each: money out the door." },
  blue: { label: "Guards", singular: "Guard", role: "Controller", hex: "#3d86ff", glow: "#7fb0ff", tagline: "Ten guards between the clerk and the ledger." },
  green: { label: "Clients", singular: "Client", role: "Finance ops", hex: "#27d99a", glow: "#7dffcf", tagline: "The vendors and staff the company pays." },
};

interface RedDef { key: string; name: string; blurb: string }
interface BlueDef { key: string; name: string; severity: 1 | 2 | 3; blurb: string }

export const RED_SCHEMES: RedDef[] = [
  { key: "ghost_vendor", name: "Ghost Vendor", blurb: "A brand-new vendor appears and immediately invoices for services never delivered." },
  { key: "bank_swap", name: "Bank Account Swap", blurb: "A real vendor's bank details are 'updated' right before a large invoice is paid." },
  { key: "duplicate_invoice", name: "Duplicate Invoice", blurb: "A paid invoice is resubmitted with a new number and the amount off by a few cents." },
  { key: "threshold_split", name: "Threshold Splitting", blurb: "One large job is billed as several invoices just under the auto-approval line." },
  { key: "ghost_employee", name: "Ghost Employee", blurb: "A payroll record with no HR trail collects a salary." },
  { key: "expense_inflation", name: "Expense Inflation", blurb: "Reimbursements creep above what was actually spent." },
  { key: "po_mismatch", name: "PO Mismatch", blurb: "An invoice is billed well above its purchase order." },
  { key: "amount_drift", name: "Amount Drift", blurb: "A recurring vendor's invoices climb a little every month." },
];

export const BLUE_RULES: BlueDef[] = [
  { key: "vendor_age_lt_7d", name: "Young Vendor", severity: 2, blurb: "Vendor created under 7 days ago and the invoice is over $1,000." },
  { key: "near_threshold", name: "Near Threshold", severity: 1, blurb: "Amount sits within 5% below the auto-approval line." },
  { key: "duplicate_invoice", name: "Duplicate Check", severity: 3, blurb: "Amount matches an invoice already paid to this vendor." },
  { key: "recent_bank_change", name: "Bank Change Watch", severity: 3, blurb: "Bank account changed within 14 days of a payment over $2,500." },
  { key: "bank_change_with_open_invoices", name: "Bank Swap Trap", severity: 3, blurb: "Bank change requested while invoices are open with that vendor." },
  { key: "no_po_from_po_vendor", name: "PO Discipline", severity: 2, blurb: "Vendor history is fully PO-backed but this invoice has no PO." },
  { key: "over_po_amount", name: "PO Ceiling", severity: 2, blurb: "Invoice exceeds its purchase order by more than 10%." },
  { key: "recurring_drift", name: "Drift Sentinel", severity: 1, blurb: "Amount is over 15% above the vendor's trailing mean." },
  { key: "employee_bank_matches_vendor", name: "Payroll Match", severity: 3, blurb: "Employee bank account matches a vendor's, or no HR record exists." },
  { key: "already_flagged_high", name: "Flag Memory", severity: 3, blurb: "Entity already carries a high-severity flag from the audit." },
];

export const GREEN_COUNT = 12;

export const RED_ROSTER: AgentSpec[] = RED_SCHEMES.map((d, index) => ({ id: `red:${d.key}`, team: "red", index, name: d.name, blurb: d.blurb }));
export const BLUE_ROSTER: AgentSpec[] = BLUE_RULES.map((d, index) => ({ id: `blue:${d.key}`, team: "blue", index, name: d.name, blurb: d.blurb }));
export const GREEN_ROSTER: AgentSpec[] = Array.from({ length: GREEN_COUNT }, (_, index) => {
  const n = String(index + 1).padStart(2, "0");
  return { id: `green:client_${n}`, team: "green" as const, index, name: `Client ${n}`, blurb: "A counterparty of the company." };
});

export const ROSTER: AgentSpec[] = [...RED_ROSTER, ...BLUE_ROSTER, ...GREEN_ROSTER];
export const ROSTER_BY_ID: Record<string, AgentSpec> = Object.fromEntries(ROSTER.map((a) => [a.id, a]));
export const rosterOf = (team: Team): AgentSpec[] => (team === "red" ? RED_ROSTER : team === "blue" ? BLUE_ROSTER : GREEN_ROSTER);

export const redIdForScheme = (schemeId: string): string | null => (ROSTER_BY_ID[`red:${schemeId}`] ? `red:${schemeId}` : null);
/** Rule ids that reach the stream under a different name than the gate rule function: `no_hr_record` comes from
 *  the same function as `employee_bank_matches_vendor`; the mock blue (battlefield/mock_agents) uses its own ids. */
const RULE_ALIAS: Record<string, string> = {
  no_hr_record: "employee_bank_matches_vendor",
  already_flagged: "already_flagged_high",
  duplicate_amount_match: "duplicate_invoice",
  bank_change_requested: "recent_bank_change",
};
export const blueIdForRule = (ruleId: string): string | null => {
  const key = RULE_ALIAS[ruleId] ?? ruleId;
  return ROSTER_BY_ID[`blue:${key}`] ? `blue:${key}` : null;
};
/** Like `blueIdForRule`, but an unknown rule id still maps to some guard (stable per id). */
export const guardForRule = (ruleId: string): string => blueIdForRule(ruleId) ?? BLUE_ROSTER[Math.floor(hash01(ruleId) * BLUE_ROSTER.length)].id;
export const ruleSeverity = (ruleKey: string): 1 | 2 | 3 | null => BLUE_RULES.find((r) => r.key === ruleKey)?.severity ?? null;

/** Stable string hash → [0, 1). Used to bind backend entities (attack ids, vendor ids) to green slots. */
export function hash01(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return ((h >>> 0) % 100000) / 100000;
}
export const greenIdFor = (entityId: string): string => GREEN_ROSTER[Math.floor(hash01(entityId) * GREEN_ROSTER.length)].id;
