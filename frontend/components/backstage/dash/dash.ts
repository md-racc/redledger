// What the red and blue dashboards show, derived from the raw event list of the followed run (so the same code reads a live run and
// the recorded loop) and from the lineage timeline read. Pure, tested. Owner: Dev R.
//
// The reducer keeps an agent's thinking per day and its tool calls without timestamps; the dashboards need more: which turn a thought
// or a call belongs to, how long a tool took (event ts of the call to the ts of its result), and what each turn cost. So these walk
// the events themselves, in arrival order, the way contracts/events.md orders them: turn.started(agent) → that agent's agent.* events
// → turn.ended(agent).
//
// Never shows ground truth: `origin` / `entity_origin` keys are dropped from anything printed verbatim (scrub).
import { RED_SCHEMES } from "@/lib/arena/roster";
import type { Attack, RLEvent, UIState } from "@/lib/types";

const P = (e: RLEvent) => (e.payload ?? {}) as Record<string, any>;
const ms = (ts: string | null | undefined): number | null => {
  if (!ts) return null;
  const t = Date.parse(ts);
  return Number.isNaN(t) ? null : t;
};
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const str = (v: unknown): string => (typeof v === "string" ? v : v == null ? "" : String(v));

// ---- formatting ---------------------------------------------------------------------------------------------------------------

export const fmtUsd = (n: unknown): string => {
  const v = Number(n);
  if (!Number.isFinite(v)) return "-";
  return `$${v.toLocaleString("en-US", { minimumFractionDigits: v % 1 ? 2 : 0, maximumFractionDigits: 2 })}`;
};
export const fmtMs = (n: number | null | undefined): string => (n == null ? "-" : n < 1000 ? `${Math.round(n)}ms` : `${(n / 1000).toFixed(n < 10_000 ? 2 : 1)}s`);
export const fmtSec = (s: number | null | undefined): string => (s == null ? "-" : s < 60 ? `${s.toFixed(s < 10 ? 2 : 1)}s` : `${Math.floor(s / 60)}m${String(Math.round(s % 60)).padStart(2, "0")}s`);
export const fmtCredits = (c: number | null | undefined): string => (c == null ? "-" : c >= 100 ? c.toFixed(0) : c >= 10 ? c.toFixed(1) : c.toFixed(2));
export const fmtCountdown = (sec: number): string => `${sec < 0 ? "-" : ""}${Math.floor(Math.abs(sec) / 60)}:${String(Math.floor(Math.abs(sec) % 60)).padStart(2, "0")}`;
export const clip = (s: string, n: number): string => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

/** Drops `origin` / `entity_origin` keys at any depth: the dashboards print args and payloads verbatim and must never print those. */
export function scrub(v: unknown, depth = 0): unknown {
  if (depth > 8 || v === null || typeof v !== "object") return v;
  if (Array.isArray(v)) return v.map((x) => scrub(x, depth + 1));
  const out: Record<string, unknown> = {};
  for (const [k, x] of Object.entries(v as Record<string, unknown>)) {
    if (k === "origin" || k === "entity_origin") continue;
    out[k] = scrub(x, depth + 1);
  }
  return out;
}

/** One-line JSON of a value, scrubbed, clipped. */
export const compactJson = (v: unknown, n = 160): string => {
  if (v === undefined) return "";
  let s: string;
  try { s = JSON.stringify(scrub(v)) ?? ""; } catch { s = String(v); }
  return clip(s, n);
};
export const prettyJson = (v: unknown): string => {
  try { return JSON.stringify(scrub(v), null, 2) ?? ""; } catch { return String(v); }
};

/** `mcp__ledger__list_vendors` → `{ ns: "mcp__ledger__", name: "list_vendors" }`: the namespace is printed dim. */
export function splitTool(tool: string): { ns: string; name: string } {
  const m = /^(.*__)([^_].*)$/.exec(tool);
  return m ? { ns: m[1]!, name: m[2]! } : { ns: "", name: tool };
}

// ---- turns: thinking, tool calls, playbook writes -------------------------------------------------------------------------------

export interface ToolCallRow {
  key: string;
  tool_use_id: string | null;
  tool: string;
  args: unknown;
  day: number;
  callTs: string;
  resultTs: string | null;
  /** undefined while the call has no result yet */
  ok: boolean | undefined;
  summary: string;
  latencyMs: number | null;
}

export interface TurnNote { ts: string; text: string }

export interface TurnBlock {
  key: string;
  agent: string;
  day: number;
  /** 1-based count of this agent's turns in the run */
  n: number;
  startTs: string | null;
  endTs: string | null;
  ended: boolean;
  /** no turn.started was seen: the events of this block arrived outside a turn */
  implicit: boolean;
  ok?: boolean;
  summary?: string;
  durationSec?: number | null;
  credits?: number | null;
  thinking: string;
  tools: ToolCallRow[];
  notes: TurnNote[];
}

/**
 * An agent's turns, oldest first, each with its thinking (deltas concatenated), its tool calls paired with their results, and the
 * playbook versions it wrote. A result pairs with its call by `tool_use_id`; a result that carries none (or an unknown one) takes the
 * oldest call of the same agent still waiting.
 */
export function agentTurns(events: RLEvent[], agent: string): TurnBlock[] {
  const blocks: TurnBlock[] = [];
  const byUseId = new Map<string, ToolCallRow>();
  const pending: ToolCallRow[] = [];
  const seen = new Set<number>();
  let cur: TurnBlock | null = null;

  const open = (day: number, ts: string | null, implicit: boolean): TurnBlock => {
    const b: TurnBlock = { key: `${agent}:${blocks.length}`, agent, day, n: blocks.length + 1, startTs: ts, endTs: null, ended: false, implicit, thinking: "", tools: [], notes: [] };
    blocks.push(b);
    return b;
  };
  const target = (e: RLEvent): TurnBlock => {
    if (cur) return cur;
    const last = blocks[blocks.length - 1];
    if (last && last.day === e.day) return last;
    return open(e.day, e.ts, true);
  };

  for (const e of events) {
    if (typeof e.id === "number" && e.id > 0 && !e.replay) {
      if (seen.has(e.id)) continue;
      seen.add(e.id);
    }
    const p = P(e);
    if (e.type === "turn.started" && p.agent === agent) {
      cur = open(e.day, e.ts, false);
      continue;
    }
    if (e.type === "turn.ended" && p.agent === agent) {
      const b = cur ?? (blocks[blocks.length - 1]?.day === e.day && !blocks[blocks.length - 1]!.ended ? blocks[blocks.length - 1]! : open(e.day, null, true));
      b.ended = true;
      b.endTs = e.ts;
      b.ok = p.ok;
      b.summary = str(p.summary) || undefined;
      b.durationSec = num(p.duration_sec);
      b.credits = num(p.factory_credits);
      cur = null;
      continue;
    }
    if (e.type === "playbook.updated" && p.agent === agent) {
      target(e).notes.push({ ts: e.ts, text: `playbook v${p.version}${p.parent_version != null ? ` (from v${p.parent_version})` : ""} · ${str(p.source)}${p.rationale ? `: ${str(p.rationale)}` : ""}` });
      continue;
    }
    if (e.agent !== agent) continue;
    if (e.type === "agent.thinking") {
      target(e).thinking += str(p.text);
    } else if (e.type === "agent.tool_call") {
      const id = p.tool_use_id ? str(p.tool_use_id) : null;
      const row: ToolCallRow = { key: id ?? `${agent}#${e.id}`, tool_use_id: id, tool: str(p.tool) || "?", args: p.args, day: e.day, callTs: e.ts, resultTs: null, ok: undefined, summary: "", latencyMs: null };
      target(e).tools.push(row);
      pending.push(row);
      if (id) byUseId.set(id, row);
    } else if (e.type === "agent.tool_result") {
      const id = p.tool_use_id ? str(p.tool_use_id) : null;
      let row = id ? byUseId.get(id) : undefined;
      if (row && row.ok !== undefined) row = undefined; // a second result for the same id: treat as unpaired
      row ??= pending.find((r) => r.ok === undefined);
      if (!row) continue;
      row.ok = p.ok !== false;
      row.summary = str(p.summary);
      row.resultTs = e.ts;
      const a = ms(row.callTs);
      const b = ms(e.ts);
      row.latencyMs = a != null && b != null && b >= a ? b - a : null;
      const i = pending.indexOf(row);
      if (i >= 0) pending.splice(i, 1);
    }
  }
  return blocks;
}

/** Wall time of a turn: the reported duration, else start to end, else start to now for a turn still running. */
export function turnElapsedSec(b: TurnBlock, now: number): number | null {
  if (b.durationSec != null) return b.durationSec;
  const a = ms(b.startTs);
  if (a == null) return null;
  const z = b.ended ? ms(b.endTs) : now;
  return z == null ? null : Math.max(0, (z - a) / 1000);
}

export interface Credits { byAgent: Record<string, number>; total: number; /** at least one turn reported a number (DRY_RUN reports null) */ reported: boolean }
/** Credits spent this run, from `turn.ended.factory_credits` (null counts as 0, as the credit guard counts it). */
export function creditsOf(events: RLEvent[]): Credits {
  const byAgent: Record<string, number> = {};
  let total = 0;
  let reported = false;
  const seen = new Set<number>();
  for (const e of events) {
    if (e.type !== "turn.ended") continue;
    if (e.id > 0 && !e.replay) { if (seen.has(e.id)) continue; seen.add(e.id); }
    const c = num(P(e).factory_credits);
    if (c == null) continue;
    reported = true;
    const a = str(P(e).agent) || "?";
    byAgent[a] = (byAgent[a] ?? 0) + c;
    total += c;
  }
  return { byAgent, total, reported };
}

// ---- gate verdicts --------------------------------------------------------------------------------------------------------------

/** `noted` = allowed, but a rule fired or a cause was attached: worth a look, distinct from a clean allow. */
export type VerdictKind = "block" | "escalate" | "noted" | "allow";

export interface VerdictRow {
  key: string;
  ts: string;
  day: number;
  agent: string;
  action: string;
  amount: number | null;
  entityId: string;
  entityType: string;
  verdict: string;
  kind: VerdictKind;
  reason: string;
  confidence: number | null;
  rules: string[];
  enforced: boolean;
  latencyMs: number | null;
  cause: string;
}

export function verdictKind(p: { verdict?: unknown; rules_fired?: unknown; cause?: unknown }): VerdictKind {
  if (p.verdict === "block") return "block";
  if (p.verdict === "escalate") return "escalate";
  const rules = Array.isArray(p.rules_fired) ? p.rules_fired : [];
  return rules.length > 0 || (typeof p.cause === "string" && p.cause !== "") ? "noted" : "allow";
}

/** Every `gate.verdict` of the run, newest first. */
export function verdictRows(events: RLEvent[]): VerdictRow[] {
  const out: VerdictRow[] = [];
  const seen = new Set<string>();
  for (const e of events) {
    if (e.type !== "gate.verdict") continue;
    const p = P(e);
    const key = str(p.verdict_id) || `vd#${e.id}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({
      key,
      ts: e.ts,
      day: e.day,
      agent: str(p.agent),
      action: str(p.action) || "?",
      amount: num(p.amount),
      entityId: str(p.entity_id),
      entityType: str(p.entity_type),
      verdict: str(p.verdict),
      kind: verdictKind(p),
      reason: str(p.reason),
      confidence: num(p.confidence),
      rules: Array.isArray(p.rules_fired) ? p.rules_fired.map(str) : [],
      enforced: p.enforced !== false,
      latencyMs: num(p.latency_ms),
      cause: str(p.cause),
    });
  }
  return out.reverse();
}

/** Fills `latencyMs` from the verdicts read (GET /fe/episodes/{ep}/verdicts) where the event did not carry `latency_ms`. */
export function withLatency(rows: VerdictRow[], read: { verdict_id?: unknown; latency_ms?: unknown }[] | undefined): VerdictRow[] {
  if (!read?.length || rows.every((r) => r.latencyMs != null)) return rows;
  const by = new Map<string, number>();
  for (const r of read) { const l = num(r.latency_ms); if (typeof r.verdict_id === "string" && l != null) by.set(r.verdict_id, l); }
  return rows.map((r) => (r.latencyMs == null && by.has(r.key) ? { ...r, latencyMs: by.get(r.key)! } : r));
}

export interface VerdictStats { counts: Record<VerdictKind, number>; total: number; avgMs: number | null; p95Ms: number | null; shadow: number }
export function verdictStats(rows: VerdictRow[]): VerdictStats {
  const counts: Record<VerdictKind, number> = { block: 0, escalate: 0, noted: 0, allow: 0 };
  let shadow = 0;
  const lat: number[] = [];
  for (const r of rows) {
    counts[r.kind] += 1;
    if (!r.enforced) shadow += 1;
    if (r.latencyMs != null) lat.push(r.latencyMs);
  }
  lat.sort((a, b) => a - b);
  const avgMs = lat.length ? lat.reduce((n, x) => n + x, 0) / lat.length : null;
  const p95Ms = lat.length ? lat[Math.min(lat.length - 1, Math.ceil(lat.length * 0.95) - 1)]! : null;
  return { counts, total: rows.length, avgMs, p95Ms, shadow };
}

// ---- escalations ----------------------------------------------------------------------------------------------------------------

export interface EscRow { id: string; action: string; amount: number | null; reason: string; entityId: string; cause: string; status: string; by: string; expiresAt: string; remainingSec: number | null }
/** Open escalations first (soonest to expire first), then the resolved ones. */
export function escalationRows(s: UIState, now: number): EscRow[] {
  const rows = Object.values(s.escalations).map((e): EscRow => {
    const x = e as typeof e & { entity_id?: string; cause?: string };
    const exp = ms(e.expires_at);
    return { id: e.escalation_id, action: e.action, amount: e.amount ?? null, reason: e.reason, entityId: str(x.entity_id), cause: str(x.cause), status: e.status, by: str(e.by), expiresAt: e.expires_at, remainingSec: exp == null ? null : (exp - now) / 1000 };
  });
  const open = rows.filter((r) => r.status === "open").sort((a, b) => (a.remainingSec ?? 1e9) - (b.remainingSec ?? 1e9));
  const done = rows.filter((r) => r.status !== "open").reverse();
  return [...open, ...done];
}

// ---- red: attacks and the scheme catalog ----------------------------------------------------------------------------------------

export interface CatalogRow { id: string; name: string; blurb: string; used: number; extracted: number; caught: number; lastOutcome: string | null; evolved: boolean }
const CAUGHT = new Set(["blocked", "flagged", "partial"]);

/** The eight schemes red can run, each with how often this run used it; any evolved or unknown scheme seen is appended. */
export function schemeCatalog(attacks: Attack[]): CatalogRow[] {
  const rows = new Map<string, CatalogRow>(RED_SCHEMES.map((d) => [d.key, { id: d.key, name: d.name, blurb: d.blurb, used: 0, extracted: 0, caught: 0, lastOutcome: null, evolved: false }]));
  for (const a of [...attacks].sort((x, y) => x.day_launched - y.day_launched)) {
    let r = rows.get(a.scheme_id);
    if (!r) {
      r = { id: a.scheme_id, name: a.display_name || a.scheme_id.replace(/^evolved:/, "").replace(/_/g, " "), blurb: a.story ?? "", used: 0, extracted: 0, caught: 0, lastOutcome: null, evolved: true };
      rows.set(a.scheme_id, r);
    }
    r.used += 1;
    r.extracted += a.amount_extracted || 0;
    if (CAUGHT.has(a.outcome)) r.caught += 1;
    r.lastOutcome = a.outcome;
  }
  return [...rows.values()];
}

// ---- evolution ------------------------------------------------------------------------------------------------------------------

export interface PlaybookDiff { added?: Record<string, unknown>; changed?: Record<string, { from: unknown; to: unknown }>; removed?: Record<string, unknown> }
export interface TimelineEntry {
  kind: "playbook" | "generation" | string;
  generation: number;
  agent?: string;
  version?: number;
  parent_version?: number | null;
  source?: string;
  day?: number | null;
  rationale?: string;
  diff?: PlaybookDiff;
  episode_id?: string | null;
  score?: Record<string, number | null>;
  status?: string;
  seed?: number;
  demo?: boolean;
}
export interface LineageTimeline { lineage_id: string; status?: string; partial?: boolean; entries: TimelineEntry[] }

/** The lineage the followed episode belongs to: its own generation.started, else its episode row, else the active run's. */
export function lineageIdOf(events: RLEvent[], episode: { id: string; lineage_id?: string | null } | null, active: { episodeId: string | null; lineageId: string | null } | null): string | null {
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i]!;
    if (e.type === "generation.started" && typeof P(e).lineage_id === "string") return P(e).lineage_id;
  }
  if (episode?.lineage_id) return episode.lineage_id;
  if (active?.lineageId && (!active.episodeId || active.episodeId === episode?.id)) return active.lineageId;
  return null;
}

/** This episode's place in its lineage: `generation.started {generation, playbook_versions}`. */
export function generationOf(events: RLEvent[]): { generation: number; versions: Record<string, number> } | null {
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i]!;
    if (e.type === "generation.started") return { generation: Number(P(e).generation) || 0, versions: (P(e).playbook_versions ?? {}) as Record<string, number> };
  }
  return null;
}

/** An agent's playbook versions, newest first. */
export function playbookHistory(tl: LineageTimeline | null, agent: string): TimelineEntry[] {
  if (!tl) return [];
  return tl.entries.filter((e) => e.kind === "playbook" && e.agent === agent).sort((a, b) => (b.version ?? 0) - (a.version ?? 0) || b.generation - a.generation);
}
export function generationEntries(tl: LineageTimeline | null): TimelineEntry[] {
  return tl ? tl.entries.filter((e) => e.kind === "generation").sort((a, b) => a.generation - b.generation) : [];
}

const val = (v: unknown): string => {
  if (Array.isArray(v)) return v.length ? v.map((x) => (typeof x === "object" ? compactJson(x, 60) : String(x))).join(", ") : "[]";
  if (v && typeof v === "object") return Object.entries(v).map(([k, n]) => `${k}=${typeof n === "object" ? compactJson(n, 40) : String(n)}`).join(", ");
  return String(v);
};
/** A playbook diff as lines a reader can scan: `+ favour: ghost_vendor=2`, `~ avoid: [] → duplicate_invoice`, `− near_band: 0.9`. */
export function diffLines(d: PlaybookDiff | undefined): { op: "+" | "~" | "−"; key: string; text: string }[] {
  if (!d) return [];
  const out: { op: "+" | "~" | "−"; key: string; text: string }[] = [];
  for (const [k, v] of Object.entries(d.added ?? {})) out.push({ op: "+", key: k, text: val(scrub(v)) });
  for (const [k, v] of Object.entries(d.changed ?? {})) out.push({ op: "~", key: k, text: `${val(scrub(v?.from))} → ${val(scrub(v?.to))}` });
  for (const [k, v] of Object.entries(d.removed ?? {})) out.push({ op: "−", key: k, text: val(scrub(v)) });
  return out;
}

/** Accepts the timeline read in whatever wrapper it came: `{entries}` or a bare list. */
export function asTimeline(raw: unknown, lineageId: string): LineageTimeline | null {
  if (Array.isArray(raw)) return { lineage_id: lineageId, entries: raw as TimelineEntry[] };
  if (raw && typeof raw === "object" && Array.isArray((raw as any).entries)) {
    const r = raw as any;
    return { lineage_id: str(r.lineage_id) || lineageId, status: r.status, partial: r.partial, entries: r.entries };
  }
  return null;
}
