// Evolution runs (README §15): shapes of GET /fe/lineages/{id}/report, a loader with a synthetic fallback, and the story
// beats the Evolution card plays. Owner: Dev R (Ad since 2026-10-25).
import { ApiError, api } from "../api";
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
  /** battlefield's rule lifecycle. NB `retired_rules` means "fired in an earlier headless generation, not in the latest one":
   *  it is not blue switching anything off (that is in blue's playbook, see `blueControlsAfter`). */
  blue: { learned_rules: { rule_id: string; first_generation: number }[]; new_rules: { rule_id: string; first_generation: number }[]; retired_rules: { rule_id: string; last_generation: number }[] };
  red: { evolved_schemes: { scheme_id: string; parent: string; first_generation: number }[] };
  partial?: boolean;
}

/** `live`: a lineage of the running battlefield; `recorded`: the synthetic golden-test lineage shipped with the frontend (public/mocks; not a recorded run, whatever the name). */
export interface LoadedLineage { report: LineageReport; source: "live" | "recorded"; /** why this lineage and not the one asked for */ note?: string }

/** The showcase lineage on prod: five headless generations with live red, extraction ~$18.5k → ~$93.6k as scored since #207. */
export const PINNED_LINEAGE = "ln_f52a3df83c8d";

/** `?lineage=<id>` on the page URL, if any. */
export function lineageFromUrl(search: string | null = typeof window !== "undefined" ? window.location.search : null): string | null {
  if (!search) return null;
  const id = new URLSearchParams(search).get("lineage")?.trim();
  return id && /^[A-Za-z0-9_-]{1,64}$/.test(id) ? id : null;
}

type LineageApi = Pick<typeof api, "lineages"> & { fe: Pick<typeof api.fe, "lineageReport"> };

/** The lineage the Evolution card asks for: `?lineage=<id>`, else the pinned showcase lineage. */
export const cardLineage = (search?: string | null): string => (search === undefined ? lineageFromUrl() : lineageFromUrl(search)) ?? PINNED_LINEAGE;

/**
 * A lineage report. `requested` (the Evolution card passes `cardLineage()`) is tried first; if it is not on this
 * battlefield (404), or none was asked for, the newest finished lineage; with no backend, the synthetic sample report.
 */
export async function loadLineageReport(preferLive: boolean, requested: string | null = null, client: LineageApi = api, sample: () => Promise<LineageReport> = fetchSample): Promise<LoadedLineage> {
  if (!preferLive) return { report: await sample(), source: "recorded" };
  if (requested) {
    try {
      return { report: (await client.fe.lineageReport(requested)) as LineageReport, source: "live" };
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 404)) return { report: await sample(), source: "recorded", note: `could not load ${requested}` };
    }
  }
  const missing = requested ? `${requested} not found` : undefined;
  try {
    const all = await client.lineages(); // newest first
    const ln = all.find((l) => l.status === "finished" && (l.generations?.length ?? 0) >= 2) ?? all.find((l) => (l.generations?.length ?? 0) >= 1);
    if (ln) return { report: (await client.fe.lineageReport(ln.id)) as LineageReport, source: "live", note: missing && `${missing} · newest finished lineage` };
  } catch { /* fall through to the sample */ }
  return { report: await sample(), source: "recorded", note: missing };
}

async function fetchSample(): Promise<LineageReport> {
  const r = await fetch("/mocks/lineage-report.json");
  return (await r.json()) as LineageReport;
}

/** The columns the card draws: every generation up to `max`; past that the first (where the story starts) and the last `max - 1`. */
export function visibleGenerations<T extends { generation: number }>(gens: T[], max = 6): { shown: T[]; hidden: number } {
  if (gens.length <= max) return { shown: gens, hidden: 0 };
  return { shown: [gens[0], ...gens.slice(-(max - 1))], hidden: gens.length - max };
}

// ---- the story -------------------------------------------------------------------------------------------------------

export const prettyId = (s: string) => s.replace(/^learned:/, "").replace(/^evolved:/, "").replace(/_/g, " ");

/** playbook keys that are bookkeeping, not something the agent learned */
const BOOKKEEPING = /(^|\.)(blue_review|schema_version|version)$/;
/** blue's control lists: the card states them on their own line (see `blueControlsAfter`) */
const BLUE_CONTROL_KEYS = /^(learned|retired)$/;

const MAX_ITEMS = 4;

/** A short human summary of one playbook value: never "[object Object]". */
export function brief(v: unknown): string {
  if (v == null) return "none";
  if (Array.isArray(v)) return tally(v.map(brief));
  if (typeof v === "object") {
    const o = v as Record<string, unknown>;
    const id = [o.scheme_id, o.scheme, o.rule_id, o.name].find((x) => typeof x === "string") as string | undefined;
    if (id) {
      const key = [o.outcome, o.verdict, o.status].find((x) => typeof x === "string");
      const amt = [o.amount, o.target_amount].find((x) => typeof x === "number") as number | undefined;
      return [prettyId(id), key, amt != null ? `$${Math.round(amt).toLocaleString()}` : null].filter(Boolean).join(" ");
    }
    const parts = Object.entries(o).filter(([k]) => !BOOKKEEPING.test(k)).map(([k, x]) => (typeof x === "number" ? `${prettyId(k)} ×${x}` : x != null && typeof x === "object" ? `${prettyId(k)} (${brief(x)})` : `${prettyId(k)} ${brief(x)}`));
    return parts.length ? cap(parts) : "none";
  }
  return typeof v === "string" ? clipText(prettyId(v)) : String(v);
}

const clipText = (t: string, n = 60) => (t.length > n ? `${t.slice(0, n - 1).trimEnd()}…` : t);

/** a plain record (no id of its own) worth one chip per key */
const isRecord = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v) && !["scheme_id", "scheme", "rule_id", "name"].some((k) => typeof (v as Record<string, unknown>)[k] === "string");

/** identical summaries collapse to "x ×n", most frequent first */
function tally(parts: string[]): string {
  if (!parts.length) return "none";
  const n = new Map<string, number>();
  for (const p of parts) n.set(p, (n.get(p) ?? 0) + 1);
  return cap([...n.entries()].sort((a, b) => b[1] - a[1]).map(([p, c]) => (c > 1 ? `${p} ×${c}` : p)));
}

const cap = (parts: string[]) => (parts.length > MAX_ITEMS ? `${parts.slice(0, MAX_ITEMS).join(", ")} +${parts.length - MAX_ITEMS} more` : parts.join(", "));

/** a dotted playbook path as words: its last two segments ("green_reflection.last_review_counts.fraud_paid" → "last review counts fraud paid") */
const label = (path: string) => path.split(".").slice(-2).map(prettyId).join(" ");

/** what an array gained: entries of `to` not in `from` (by value) */
function gained(from: unknown[], to: unknown[]): unknown[] {
  const had = new Map<string, number>();
  for (const x of from) { const k = JSON.stringify(x); had.set(k, (had.get(k) ?? 0) + 1); }
  return to.filter((x) => { const k = JSON.stringify(x); const c = had.get(k) ?? 0; if (c > 0) { had.set(k, c - 1); return false; } return true; });
}

/** A playbook diff as short human chips: "+ avoid: duplicate invoice", "~ near band: 0.95", "+ observations: threshold split extracted ×3". */
export function diffChips(d: PlaybookDiff, skip: RegExp | null = null): string[] {
  const keep = (k: string) => !BOOKKEEPING.test(k) && !(skip && skip.test(k));
  const chips: string[] = [];
  for (const [k, v] of Object.entries(d.added)) {
    if (!keep(k)) continue;
    if (isRecord(v)) for (const [k2, v2] of Object.entries(v)) { if (keep(`${k}.${k2}`)) chips.push(`+ ${label(`${k}.${k2}`)}: ${brief(v2)}`); }
    else chips.push(`+ ${label(k)}: ${brief(v)}`);
  }
  for (const [k, v] of Object.entries(d.changed)) {
    if (!keep(k)) continue;
    if (Array.isArray(v.from) && Array.isArray(v.to)) {
      const plus = gained(v.from, v.to), minus = gained(v.to, v.from);
      if (plus.length) chips.push(`+ ${label(k)}: ${brief(plus)}`);
      if (minus.length && !plus.length) chips.push(`− ${label(k)}: ${brief(minus)}`);
    } else chips.push(`~ ${label(k)}: ${brief(v.to)}`);
  }
  for (const [k, v] of Object.entries(d.removed)) if (keep(k)) chips.push(`− ${label(k)}: ${brief(v)}`);
  return chips;
}

export interface EvoNote { agent: EvoAgent; version: number; rationale: string; chips: string[]; /** arena agents this is about */ focus: string[] }

/** What each agent changed in its playbook when generation `g` ended (the after-action review). */
export function notesAfter(report: LineageReport, g: number): EvoNote[] {
  const out: EvoNote[] = [];
  const blueLists = blueKeepsControlLists(report);
  for (const agent of ["red", "blue", "green"] as const) {
    for (const pb of report.playbooks[agent] ?? []) {
      if (pb.source !== "reflect" || pb.generation !== g) continue;
      const memory = agent === "red" ? redMemoryOf(pb, g) : null;
      const chips = memory ? [memory, ...diffChips(pb.diff, OBSERVATIONS)] : diffChips(pb.diff, agent === "blue" && blueLists ? BLUE_CONTROL_KEYS : null);
      if (!chips.length) continue;
      out.push({ agent, version: pb.version, rationale: pb.rationale, chips, focus: focusOf(agent, pb) });
    }
  }
  return out;
}

const OBSERVATIONS = /(^|\.)observations$/;

/** Red's reflection keeps every attack outcome disclosed to it (`red_evolution.observations`): the ones from generation `g`,
 *  as "threshold split extracted ×3, bank swap partial". Null when its playbook has no such list. */
function redMemoryOf(pb: PlaybookVersion, g: number): string | null {
  const c = pb.content ?? {};
  const list = (c.red_evolution as { observations?: unknown } | undefined)?.observations ?? c.observations;
  if (!Array.isArray(list)) return null;
  const mine = list.filter((o) => o && typeof o === "object" && (o as { generation?: unknown }).generation === g);
  return mine.length ? `outcomes of gen ${g}: ${brief(mine)}` : null;
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

const strings = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);

/** blue's playbook carries its control lists (`learned`, `retired`): what it switched on and off is then on record */
export const blueKeepsControlLists = (report: LineageReport): boolean => (report.playbooks.blue ?? []).some((v) => Array.isArray(v.content?.learned));

export interface BlueControls {
  /** `playbook`: read from blue's own reflect versions; `report`: blue's playbook has no control lists, only rule-fire stats */
  basis: "playbook" | "report";
  /** controls blue switched on in its after-action review of generation `g` (playbook), or rules that first fired in `g` (report) */
  on: string[];
  /** controls blue switched off after `g` (playbook only; the report cannot tell) */
  off: string[];
  /** rules that fired in `g` and in no later headless generation (battlefield's `retired_rules`; nothing was switched off) */
  quiet: string[];
}

/** What blue's controls did after generation `g`, from blue's playbook when it records them, never from rule silence. */
export function blueControlsAfter(report: LineageReport, g: number): BlueControls {
  const quiet = report.blue.retired_rules.filter((r) => r.last_generation === g).map((r) => r.rule_id);
  if (!blueKeepsControlLists(report)) return { basis: "report", on: report.blue.learned_rules.filter((r) => r.first_generation === g).map((r) => r.rule_id), off: [], quiet };
  const versions = [...(report.playbooks.blue ?? [])].sort((a, b) => a.version - b.version);
  const on = new Set<string>(), off = new Set<string>();
  for (const v of versions) {
    if (v.source !== "reflect" || v.generation !== g) continue;
    const prev = versions.find((p) => p.version === v.parent_version) ?? versions.filter((p) => p.version < v.version).at(-1);
    const was = strings(prev?.content?.learned), now = strings(v.content?.learned);
    const wasOff = strings(prev?.content?.retired), nowOff = strings(v.content?.retired);
    now.filter((x) => !was.includes(x)).forEach((x) => on.add(x));
    was.filter((x) => !now.includes(x)).forEach((x) => off.add(x));
    nowOff.filter((x) => !wasOff.includes(x)).forEach((x) => off.add(x));
  }
  return { basis: "playbook", on: [...on], off: [...off].filter((x) => !on.has(x)), quiet };
}
