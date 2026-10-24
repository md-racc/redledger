// What the consoles show, derived from the event stream (so a console reads the same live or recorded) and from the REST reads
// the hook adds. Pure functions, tested. Owner: Dev R.
import { blueIdForRule, ROSTER_BY_ID } from "@/lib/arena/roster";
import type { PlaybookVersion, LineageReport, EvoAgent } from "@/lib/arena/lineage";
import type { Attack, RLEvent, UIState, VerdictCard } from "@/lib/types";

export const schemeName = (id: string) => ROSTER_BY_ID[`red:${id}`]?.name ?? id.replace(/^evolved:/, "evolved ").replace(/_/g, " ");
export const ruleName = (id: string) => {
  const g = blueIdForRule(id);
  return (g && ROSTER_BY_ID[g]?.name) || id.replace(/^learned:/, "learned ").replace(/_/g, " ");
};

// ---- red -------------------------------------------------------------------------------------------------------------

export interface SchemeRow { scheme: string; attempts: number; targeted: number; extracted: number; caught: number; latency: number | null }

/** Per scheme, the way GET /fe/episodes/{ep}/attacks/leaderboard reports it, from the events. */
export function schemeBoard(attacks: Attack[]): SchemeRow[] {
  const by = new Map<string, SchemeRow & { lat: number[] }>();
  for (const a of attacks) {
    const r = by.get(a.scheme_id) ?? { scheme: a.scheme_id, attempts: 0, targeted: 0, extracted: 0, caught: 0, latency: null, lat: [] };
    r.attempts += 1;
    r.targeted += a.target_amount || 0;
    r.extracted += a.amount_extracted || 0;
    if (a.outcome === "blocked" || a.outcome === "flagged" || a.outcome === "partial") r.caught += 1;
    if (a.detected_day != null) r.lat.push(a.detected_day - a.day_launched);
    by.set(a.scheme_id, r);
  }
  return [...by.values()].map(({ lat, ...r }) => ({ ...r, latency: lat.length ? lat.reduce((n, x) => n + x, 0) / lat.length : null })).sort((a, b) => b.extracted - a.extracted || b.attempts - a.attempts);
}

export const attacksNewestFirst = (s: UIState): Attack[] => Object.values(s.attacks).sort((a, b) => b.day_launched - a.day_launched);

// ---- agent narration and tools -------------------------------------------------------------------------------------------

export interface Thought { key: string; day: number; text: string }
/** An agent's thinking, concatenated per day (the reducer already does this), newest day first. */
export function thoughts(s: UIState, agent: string, max = 6): Thought[] {
  return Object.entries(s.thinking)
    .filter(([k]) => k.startsWith(`${agent}:`))
    .map(([k, text]) => ({ key: k, day: Number(k.split(":")[1]), text }))
    .sort((a, b) => b.day - a.day)
    .slice(0, max);
}

export interface ToolRow { id: string; day: number; tool: string; ok: boolean | undefined; summary: string }
export function toolRows(s: UIState, agent: string, max = 12): ToolRow[] {
  return s.toolCalls.filter((c) => c.agent === agent).slice(-max).reverse().map((c) => ({ id: c.tool_use_id, day: c.day, tool: c.tool, ok: c.ok, summary: c.summary ?? "" }));
}

/** An agent's turns: how long each took and what it spent. */
export function turnRows(s: UIState, agent: string, max = 6) {
  return s.turns.filter((t) => t.agent === agent).slice(-max).reverse();
}

// ---- green -----------------------------------------------------------------------------------------------------------------

export interface ActionRow { id: string; day: number; action: string; entity: string; amount: number | null; verdict: string; enforced: boolean; rules: string[]; reason: string }

/**
 * Green's gated attempts, newest first: every `gate.verdict` on an action green made. A blocked attempt never reaches the ledger
 * (so it has no ledger.mutation), which is why the verdicts, not the mutations, are the tape.
 */
export function greenActions(verdicts: VerdictCard[], max = 14): ActionRow[] {
  return verdicts
    .filter((v) => v.agent === "green")
    .slice(-max)
    .reverse()
    .map((v) => ({ id: v.verdict_id, day: v.day, action: v.action, entity: `${v.entity_type ?? ""} ${String(v.entity_id ?? "").slice(-6)}`.trim(), amount: v.amount ?? null, verdict: v.verdict, enforced: v.enforced, rules: v.rules_fired ?? [], reason: v.reason }));
}

// ---- blue ------------------------------------------------------------------------------------------------------------------

export interface VerdictCounts { allow: number; block: number; escalate: number; total: number }
export function verdictCounts(verdicts: VerdictCard[]): VerdictCounts {
  const c = { allow: 0, block: 0, escalate: 0, total: verdicts.length };
  for (const v of verdicts) c[v.verdict] += 1;
  return c;
}

export interface RuleRow { rule: string; block: number; escalate: number; allow: number; total: number }
/** Which rules did the work: every verdict counted under each rule that fired. */
export function ruleBoard(verdicts: VerdictCard[]): RuleRow[] {
  const by = new Map<string, RuleRow>();
  for (const v of verdicts) {
    for (const rule of v.rules_fired ?? []) {
      const r = by.get(rule) ?? { rule, block: 0, escalate: 0, allow: 0, total: 0 };
      r[v.verdict] += 1;
      r.total += 1;
      by.set(rule, r);
    }
  }
  return [...by.values()].sort((a, b) => b.total - a.total);
}

export interface Confusion { trueBlock: number; falseBlock: number; missed: number; trueAllow: number }
/** From GET /verdicts/confusion rows: verdict × origin → n (origin red = fraud, anything else is legit). Operator view only. */
export function confusion(rows: { verdict?: string; origin?: string; n?: number }[] | undefined): Confusion | null {
  if (!rows || !rows.length) return null;
  const c = { trueBlock: 0, falseBlock: 0, missed: 0, trueAllow: 0 };
  for (const r of rows) {
    const n = Number(r.n ?? 0);
    const fraud = r.origin === "red";
    const stopped = r.verdict === "block" || r.verdict === "escalate";
    if (stopped && fraud) c.trueBlock += n; else if (stopped) c.falseBlock += n; else if (fraud) c.missed += n; else c.trueAllow += n;
  }
  return c;
}

export function avgLatency(rows: { latency_ms?: number | null }[] | undefined): number | null {
  const xs = (rows ?? []).map((r) => r.latency_ms).filter((x): x is number => typeof x === "number");
  return xs.length ? xs.reduce((n, x) => n + x, 0) / xs.length : null;
}

// ---- playbooks -------------------------------------------------------------------------------------------------------------

export function playbookRows(report: LineageReport | null, agent: EvoAgent): PlaybookVersion[] {
  return report ? [...(report.playbooks[agent] ?? [])].reverse() : [];
}
