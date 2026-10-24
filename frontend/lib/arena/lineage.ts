// Evolution runs (README §15): shapes of GET /fe/lineages/{id}/report, a loader with a recorded fallback, and the story
// beats the Evolution card plays. Owner: Dev R.
import { api } from "../api";
import type { Score } from "../types";
import { blueIdForRule, redIdForScheme } from "./roster";

export type EvoAgent = "red" | "green" | "blue";

export interface RedMixEntry { launched: number; target_amount: number; amount_extracted: number; outcomes: Record<string, number> }
export interface BlueRuleStat { rule_id: string; fired: number; on_red: number; on_legit: number; precision: number | null; recall: number | null; attacks_hit: number }
export interface GenReport {
  generation: number;
  demo: boolean;
  days: number;
  seed: number;
  status: string;
  episode_id: string;
  score: Score;
  red_mix: Record<string, RedMixEntry>;
  blue_rules: BlueRuleStat[];
  green: { actions: number; fraud_paid: number; legit_blocked: number; legit_processed: number };
  who_beat_whom: Record<string, { attacks: number; caught: number; missed: number; rules: Record<string, number> }>;
  credits: number;
}
export interface PlaybookDiff { added: Record<string, unknown>; changed: Record<string, { from: unknown; to: unknown }>; removed: Record<string, unknown> }
export interface PlaybookVersion {
  version: number;
  parent_version: number | null;
  generation: number;
  source: "seed" | "turn" | "reflect" | "operator";
  day: number | null;
  rationale: string;
  content: Record<string, unknown>;
  diff: PlaybookDiff;
}
export interface LineageReport {
  lineage: { id: string; name: string; base_seed: number; status: string; current_generation: number; config: Record<string, unknown> };
  generations: GenReport[];
  playbooks: Record<EvoAgent, PlaybookVersion[]>;
  blue: { learned_rules: { rule_id: string; first_generation: number }[]; new_rules: { rule_id: string; first_generation: number }[]; retired_rules: { rule_id: string; last_generation: number }[] };
  red: { evolved_schemes: { scheme_id: string; parent: string; first_generation: number }[] };
  partial?: boolean;
}

export interface LoadedLineage { report: LineageReport; source: "live" | "recorded" }

/** The newest finished lineage of a running battlefield, else the recorded sample report. */
export async function loadLineageReport(preferLive: boolean): Promise<LoadedLineage> {
  if (preferLive) {
    try {
      const all = await api.lineages();
      const ln = all.find((l) => l.status === "finished" && (l.generations?.length ?? 0) >= 2) ?? all.find((l) => (l.generations?.length ?? 0) >= 1);
      if (ln) return { report: (await api.fe.lineageReport(ln.id)) as LineageReport, source: "live" };
    } catch { /* fall through to the recording */ }
  }
  const r = await fetch("/mocks/lineage-report.json");
  return { report: (await r.json()) as LineageReport, source: "recorded" };
}

// ---- the story -------------------------------------------------------------------------------------------------------

const val = (v: unknown): string => (Array.isArray(v) ? (v.length ? v.join(", ") : "none") : v && typeof v === "object" ? Object.entries(v).map(([k, n]) => `${k} ×${n}`).join(", ") : String(v));

/** A playbook diff as short human chips: "avoid + duplicate_invoice", "near band 0.95". */
export function diffChips(d: PlaybookDiff): string[] {
  const chips: string[] = [];
  for (const [k, v] of Object.entries(d.added)) chips.push(`+ ${k.replace(/_/g, " ")}: ${val(v)}`);
  for (const [k, v] of Object.entries(d.changed)) chips.push(`~ ${k.replace(/_/g, " ")}: ${val(v.to)}`);
  for (const [k, v] of Object.entries(d.removed)) chips.push(`− ${k.replace(/_/g, " ")}: ${val(v)}`);
  return chips;
}

export interface EvoNote { agent: EvoAgent; version: number; rationale: string; chips: string[]; /** arena agents this is about */ focus: string[] }

/** What each agent changed in its playbook when generation `g` ended (the after-action review). */
export function notesAfter(report: LineageReport, g: number): EvoNote[] {
  const out: EvoNote[] = [];
  for (const agent of ["red", "blue", "green"] as const) {
    for (const pb of report.playbooks[agent] ?? []) {
      if (pb.source !== "reflect" || pb.generation !== g) continue;
      const chips = diffChips(pb.diff);
      if (!chips.length) continue;
      out.push({ agent, version: pb.version, rationale: pb.rationale, chips, focus: focusOf(agent, pb) });
    }
  }
  return out;
}

function focusOf(agent: EvoAgent, pb: PlaybookVersion): string[] {
  const ids = new Set<string>();
  const text = JSON.stringify(pb.content);
  if (agent === "red") for (const m of text.matchAll(/"?([a-z_]+)"?/g)) { const id = redIdForScheme(m[1]); if (id) ids.add(id); }
  if (agent === "blue") for (const m of text.matchAll(/([a-z_0-9]+)/g)) { const id = blueIdForRule(m[1]); if (id) ids.add(id); }
  if (agent === "blue" && !ids.size) ids.add("blue:already_flagged_high");
  return [...ids].slice(0, 3);
}

export const evolvedIn = (report: LineageReport, g: number): { scheme_id: string; parent: string }[] => report.red.evolved_schemes.filter((s) => s.first_generation === g);
export const learnedIn = (report: LineageReport, g: number): string[] => report.blue.learned_rules.filter((r) => r.first_generation === g).map((r) => r.rule_id);
