// Pure helpers for the controls assessment page (/report/[ep]): the words a reader gets, derived from the report data.
// Nothing here fetches or renders; components/report/* do that.
import type { AgentModel, ControlRow, ControlsReport, Effect, Gap, GapWhy, SchemeRow } from "./types";

const USD = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 });
const USD0 = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

/** $1,234.56 (or $1,235 with `whole`). Anything that is not a finite number reads as $0.00. */
export function usd(n: unknown, whole = false): string {
  const v = typeof n === "number" && Number.isFinite(n) ? n : 0;
  return (whole ? USD0 : USD).format(v);
}

/** Share of `part` in `whole` as "74%"; "0%" when there is no whole. */
export function pct(part: number, whole: number): string {
  if (!whole || !Number.isFinite(part) || !Number.isFinite(whole)) return "0%";
  return `${Math.round((part / whole) * 100)}%`;
}

export const plural = (n: number, one: string, many = `${one}s`): string => `${n} ${n === 1 ? one : many}`;

/** The first `max` items as a list, the rest counted: "a, b, c and 2 more". */
export function listSome(items: string[], max = 3): string {
  return items.length > max ? `${items.slice(0, max).join(", ")} and ${items.length - max} more` : list(items);
}

/** "a, b and c" */
export function list(items: string[]): string {
  if (items.length <= 1) return items[0] ?? "";
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

// What each gate control checks, in a reader's words. Rule ids come from blue/gate/rules.py and blue/gate/learned.py.
const CONTROL_TEXT: Record<string, string> = {
  vendor_age_lt_7d: "Vendor has less than seven days of history",
  near_threshold: "Amount sits just under the approval threshold",
  threshold_split: "Several invoices together cross the approval threshold",
  duplicate_invoice: "Invoice duplicates one already paid",
  duplicate_amount_match: "Amount matches an invoice already paid",
  po_vendor_mismatch: "Purchase order belongs to another vendor",
  invalid_po: "Purchase order is cancelled",
  over_po_amount: "Invoice exceeds its purchase order by more than 10%",
  no_po_from_po_vendor: "No purchase order from a vendor that normally uses one",
  recurring_drift: "Amount exceeds the vendor's stable baseline by more than 15%",
  recent_bank_change: "Payment follows a recent bank account change",
  bank_change_with_open_invoices: "Bank account change while invoices are open",
  bank_change_requested: "Bank account change requested",
  unverified_vendor_exposure: "Exposure to an unverified vendor",
  employee_bank_matches_vendor: "Employee shares a payment account with a vendor",
  no_hr_record: "Employee has no HR onboarding record",
  inactive_employee: "Employee is not active",
  vendor_frozen: "Vendor is frozen",
  already_flagged_high: "A high-severity flag is open on this item",
  gate_timeout: "Controller unavailable; fallback verdict",
  "learned:young_vendor_any_amount": "Learned: new vendor with no PO or payment history, any amount",
  "learned:near_threshold_wide": "Learned: widened near-threshold band for unestablished vendors",
  "learned:duplicate_amount_loose": "Learned: amount close to a paid invoice under another number",
  "learned:bank_change_any_amount": "Learned: any payment soon after a bank change",
  "learned:verification_unavailable": "Learned: verification evidence unavailable",
};

/** A plain description of a control id; unknown ids are de-snaked ("foo_bar" → "Foo bar"). */
export function controlText(id: string): string {
  if (CONTROL_TEXT[id]) return CONTROL_TEXT[id]!;
  const bare = id.replace(/^learned:/, "").replace(/_/g, " ").trim();
  const text = bare ? bare[0]!.toUpperCase() + bare.slice(1) : id;
  return id.startsWith("learned:") ? `Learned: ${text}` : text;
}

export const EFFECT_LABEL: Record<Effect, string> = { block: "Preventive (blocks)", escalate: "Escalates to a human", note: "Detective note only" };

const OUTCOME_ORDER = ["extracted", "partial", "blocked", "flagged", "failed", "pending"];

/** "1 extracted, 1 partial" in a fixed order, zero counts left out; "none" when nothing resolved. */
export function outcomeText(outcomes: Record<string, number>): string {
  const keys = [...OUTCOME_ORDER, ...Object.keys(outcomes).filter((k) => !OUTCOME_ORDER.includes(k))];
  const parts = keys.filter((k) => (outcomes[k] ?? 0) > 0).map((k) => `${outcomes[k]} ${k}`);
  return parts.length ? parts.join(", ") : "none";
}

/** Controls that stopped at least one fraudulent item (blocked or escalated it), most items first. */
export function effectiveControls(r: ControlsReport): ControlRow[] {
  return r.controls.filter((c) => c.on_fraud.stopped > 0).sort((a, b) => b.on_fraud.stopped - a.on_fraud.stopped || b.on_fraud.dollars - a.on_fraud.dollars);
}

/** A control's assessment rating: did it stop fraud, and at what cost to legitimate work. */
export function controlRating(c: ControlRow): "effective" | "effective, noisy" | "noisy" | "ineffective" | "not tested" {
  const hitFraud = c.on_fraud.stopped > 0;
  const hitLegit = c.on_legit.stopped > 0;
  if (hitFraud) return hitLegit ? "effective, noisy" : "effective";
  if (hitLegit) return "noisy";
  return c.on_fraud.n > 0 ? "ineffective" : "not tested";
}

/** One-sentence explanation of why a scheme got money out, in plain English. */
export function gapExplanation(g: Gap, mode: string): string {
  const named = (ids: string[]) => list(ids.map((id) => `"${controlText(id)}"`));
  const elsewhere = g.caught_elsewhere.length
    ? ` The gate did act on another part of the scheme (${named(g.caught_elsewhere)}), but not on the payment that moved the money.`
    : "";
  const audit = g.audit_detected ? " The after-the-fact audit raised it, but only once the money had left." : "";
  const reasons: Record<GapWhy, string> = {
    "no control fired":
      mode === "off" ? "The controller was switched off for this run, so no control evaluated the payment." : "No gate control fired on the items that were paid." + elsewhere + audit,
    "note only": `${named(g.controls_on_paid)} fired, but only as a note: the payment was allowed.${elsewhere}${audit}`,
    "escalation approved": "The gate escalated the payment and a human reviewer approved it." + audit,
    "audit only": "The gate let the payment through; only the after-the-fact audit (flags, freezes) caught it, after the money had left.",
    "not enforced": "A control would have stopped the payment, but the controller ran in shadow mode, so its verdict was logged and not enforced.",
  };
  return reasons[g.why] ?? `Gap reason: ${g.why}.`;
}

/** What to do about a gap, in one sentence. */
export function gapRecommendation(g: Gap): string {
  switch (g.why) {
    case "note only":
      return `Promote ${list(g.controls_on_paid.map((id) => `"${controlText(id)}"`))} from a note to an escalation (or a block above a dollar limit).`;
    case "escalation approved":
      return "Give reviewers the evidence the control saw, and require independent verification before approving this pattern.";
    case "audit only":
      return "Move the audit signal that caught this into the pre-payment gate.";
    case "not enforced":
      return "Enforce the controller before deployment; shadow mode only measures.";
    default:
      return "Add a pre-payment control for this pattern; today nothing checks it.";
  }
}

/** The executive summary: one sentence each for dollars, controls that worked, open gaps, false-positive cost, and mode. */
export function executiveSummary(r: ControlsReport): string[] {
  const t = r.totals;
  const out: string[] = [];
  if (!t.attacks) {
    out.push("The attacker made no attempts in this run, so no control was tested against fraud.");
  } else {
    out.push(
      `An adaptive attacker made ${plural(t.attacks, "attempt")} across ${plural(t.schemes, "scheme")} worth ${usd(t.attempted)}; ` +
        `${usd(t.extracted)} (${pct(t.extracted, t.attempted)}) left the company and ${usd(t.blocked)} was stopped.`,
    );
  }
  const worked = effectiveControls(r);
  if (worked.length) {
    const named = worked.map((c) => `"${controlText(c.control_id)}" (${plural(c.on_fraud.stopped, "item")}${c.on_fraud.dollars ? `, ${usd(c.on_fraud.dollars)}` : ""})`);
    out.push(`${plural(worked.length, "control")} stopped fraudulent items: ${listSome(named)}.`);
  } else if (t.attacks) {
    out.push("No control stopped a fraudulent item before payment.");
  }
  if (r.gaps.length) {
    const named = r.gaps.map((g) => `${g.display_name} (${usd(g.extracted)}, ${g.why})`);
    out.push(`${plural(r.gaps.length, "scheme")} still extracted money: ${listSome(named)}.`);
  } else if (t.attacks) {
    out.push("No scheme extracted money: there are no open gaps from this run.");
  }
  const fp = r.false_positives;
  out.push(
    fp.legit_blocked || fp.legit_escalated
      ? `False positives cost ${usd(fp.cost)}: ${plural(fp.legit_blocked, "legitimate item")} blocked and ${fp.legit_escalated} escalated for review.`
      : "No legitimate item was blocked or escalated: false-positive cost is $0.00.",
  );
  const mode = r.episode.controller_mode;
  if (mode === "shadow") out.push("The controller ran in shadow mode: verdicts were recorded but not enforced, so the dollar figures show what got through without it.");
  if (mode === "off") out.push("The controller was off: this run is the uncontrolled baseline.");
  return out;
}

/** The agents' models from GET /health (`agents.<name>.model`), in red, green, blue order. */
export function agentModels(health: unknown): AgentModel[] {
  const agents = health && typeof health === "object" ? (health as { agents?: unknown }).agents : undefined;
  if (!agents || typeof agents !== "object") return [];
  return ["red", "green", "blue"]
    .filter((a) => a in (agents as Record<string, unknown>))
    .map((agent) => {
      const h = (agents as Record<string, unknown>)[agent];
      const o = h && typeof h === "object" ? (h as Record<string, unknown>) : {};
      return {
        agent,
        model: typeof o.model === "string" && o.model ? o.model : null,
        dry_run: typeof o.dry_run === "boolean" ? o.dry_run : null,
        ok: o.ok === true,
      };
    });
}

/** "gpt-5.4-mini", "gpt-5.4-mini (dry run)", "unknown" */
export function modelText(m: AgentModel): string {
  if (m.dry_run) return m.model ? `${m.model} (dry run: canned turns)` : "dry run (canned turns)";
  return m.model ?? (m.ok ? "unknown" : "unreachable");
}

const ROLE: Record<string, string> = { red: "Attacker", green: "AP agent under test", blue: "Controller (gate + audit)" };
export const agentRole = (agent: string): string => ROLE[agent] ?? agent;

/** The date the run finished (or started, or was created) as "25 October 2026"; "" when unknown. */
export function reportDate(r: ControlsReport): string {
  const raw = r.episode.finished_at ?? r.episode.started_at ?? r.episode.created_at;
  if (!raw) return "";
  const d = new Date(raw);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
}

export const reportFilename = (r: ControlsReport): string => `controls-assessment-${r.episode.id.replace(/[^A-Za-z0-9_-]/g, "-")}.json`;

/** Schemes worst first: most money out, then most targeted. */
export function schemesByLoss(rows: SchemeRow[]): SchemeRow[] {
  return [...rows].sort((a, b) => b.extracted - a.extracted || b.targeted - a.targeted || a.first_day - b.first_day);
}

/** The proxy's answer to a viewer who asks before the run ends (app/api/bf/[...path]/route.ts, notFinalYet). */
export function isNotFinalAnswer(status: number, body: string): boolean {
  if (status !== 403) return false;
  try {
    const b = JSON.parse(body) as { error?: unknown; detail?: unknown };
    return b.error === "viewer" && b.detail === "available when the run ends";
  } catch {
    return false;
  }
}

/** Models shown with NEXT_PUBLIC_MOCK=true: the recorded demo (docs/recordings/demo-enforce-redblue-live.jsonl) ran live red and blue. */
export const MOCK_MODELS: AgentModel[] = [
  { agent: "red", model: "gpt-5.4-mini", dry_run: false, ok: true },
  { agent: "green", model: null, dry_run: true, ok: true },
  { agent: "blue", model: "gpt-5.4-mini", dry_run: false, ok: true },
];
