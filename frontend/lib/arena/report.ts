// The end-of-day report, for the arena's Report card. Owner: Dev R.
//
// With a live backend the text is blue's own report: report.posted gives `{report_id, day}` and GET /reports/{id} the markdown (`api.fe.report`).
// With no backend (the recorded show, offline) there is no text to fetch, so the card shows a summary built from the day's events and
// says so. It never passes that summary off as blue's report.
import type { UIState } from "../types";

const usd = (n: number) => `$${Math.round(n).toLocaleString()}`;
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** The markdown body of a report row, whatever the backend called the field; null when there is none. */
export function reportText(row: unknown): string | null {
  if (typeof row === "string") return row.trim() || null;
  if (!row || typeof row !== "object") return null;
  const r = row as Record<string, unknown>;
  for (const k of ["markdown", "content", "body", "text"]) {
    const v = r[k];
    if (typeof v === "string" && v.trim()) return v;
  }
  return null;
}

/** The days that have a report, oldest first, with the newest report id for each. */
export function reportDays(state: UIState): { day: number; report_id: string }[] {
  const byDay = new Map<number, string>();
  for (const r of state.reports) byDay.set(r.day, r.report_id);
  return [...byDay].map(([day, report_id]) => ({ day, report_id })).sort((a, b) => a.day - b.day);
}

/** A plain summary of one day, from the events the arena already holds. Markdown, in the report's own vocabulary. */
export function daySummary(state: UIState, day: number): string {
  const verdicts = state.verdicts.filter((v) => v.day === day);
  const allowed = verdicts.filter((v) => v.verdict === "allow").length;
  const blocked = verdicts.filter((v) => v.verdict === "block").length;
  const asked = verdicts.filter((v) => v.verdict === "escalate").length;
  const attacks = Object.values(state.attacks).filter((a) => a.day_launched === day);
  const stopped = attacks.filter((a) => ["blocked", "flagged", "failed"].includes(a.outcome)).length;
  const through = attacks.filter((a) => a.outcome === "extracted" || a.outcome === "partial");
  const flags = state.flags.filter((f) => f.day === day);

  const lines = [`# Day ${day}`, ""];
  lines.push(`- **Payments judged:** ${verdicts.length}${verdicts.length ? ` (${allowed} allowed, ${blocked} blocked, ${asked} sent to a person)` : ""}`);
  if (attacks.length) {
    const money = through.reduce((s, a) => s + (a.amount_extracted || 0), 0);
    lines.push(`- **Fraud attempts:** ${attacks.length}: ${stopped} stopped, ${through.length} got through${money > 0 ? ` (${usd(money)})` : ""}`);
  } else {
    lines.push("- **Fraud attempts:** none today");
  }
  lines.push(`- **Flags raised:** ${flags.length}`);
  for (const f of flags.slice(0, 5)) lines.push(`  - ${f.severity}: ${f.reason}`);
  if (flags.length > 5) lines.push(`  - and ${plural(flags.length - 5, "more")}`);
  const stopsToday = verdicts.filter((v) => v.verdict !== "allow" && v.reason).slice(0, 4);
  if (stopsToday.length) {
    lines.push("", "## What the controller stopped or sent to a person", "");
    for (const v of stopsToday) lines.push(`- ${v.verdict === "block" ? "Blocked" : "Sent to a person"}${v.amount ? ` (${usd(v.amount)})` : ""}: ${v.reason}`);
  }
  return lines.join("\n");
}
