// What the raw consoles print: event lines, the live checks, which lines belong to which team, and which lines the arena's current
// selection points at. Pure, tested. Owner: Dev R.
import type { RLEvent } from "@/lib/types";
import type { SyncMsg, SyncState, TrafficRow } from "@/lib/sync/hub";
import { liveClients } from "@/lib/sync/hub";
import { blueIdForRule } from "@/lib/arena/roster";

export type TeamKey = "red" | "green" | "blue" | "battlefield";
export const TEAM_KEYS: TeamKey[] = ["red", "green", "blue", "battlefield"];

export const hhmmss = (ts: string | number | undefined): string => {
  if (ts === undefined) return "--:--:--";
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? "--:--:--" : d.toLocaleTimeString("en-GB", { hour12: false });
};

const compact = (v: unknown, n: number): string => {
  const s = JSON.stringify(v);
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
};

/** One event on one line: time, id, day, agent, type, payload. */
export function eventLine(e: RLEvent, width = 220): string {
  return `${hhmmss(e.ts)} #${String(e.id).padEnd(5)} d${e.day} ${String(e.agent ?? "-").padEnd(11)} ${e.type.padEnd(19)} ${compact(e.payload, width)}`;
}

export function trafficLine(t: TrafficRow): string {
  return `${hhmmss(t.ts)} ${t.method.padEnd(6)} ${t.path.padEnd(46)} ${String(t.status).padStart(3)} ${String(t.ms).padStart(5)}ms  ${t.client || "-"}`;
}

export function msgLine(m: SyncMsg): string {
  const { role: _role, ...rest } = m.data;
  return `${hhmmss(m.ts)} ${m.client.padEnd(14)} ${m.kind.padEnd(10)} ${Object.entries(rest).filter(([, v]) => v !== null && v !== "").map(([k, v]) => `${k}=${v}`).join(" ")}`;
}

const p = (e: RLEvent) => e.payload as Record<string, any>;

/** Which events a team's console lists. The battlefield sees everything. */
export function teamEvents(team: TeamKey, events: RLEvent[]): RLEvent[] {
  switch (team) {
    case "red":
      return events.filter((e) => e.agent === "red" || e.type.startsWith("attack.") || (e.type === "ledger.mutation" && p(e).agent === "red"));
    case "green":
      return events.filter((e) => e.agent === "green" || (e.type === "ledger.mutation" && p(e).agent === "green") || (e.type === "gate.verdict" && p(e).agent === "green") || e.type.startsWith("escalation."));
    case "blue":
      return events.filter((e) => e.agent === "blue" || ["gate.verdict", "flag.raised", "vendor.frozen", "vendor.unfrozen", "report.posted"].includes(e.type) || e.type.startsWith("escalation."));
    default:
      return events;
  }
}

/** Does this event concern the agent the arena has selected? (`red:<scheme>`, `blue:<rule>`; green clients are bound by hash, so no.) */
export function concerns(e: RLEvent, selectedId: string | null | undefined): boolean {
  if (!selectedId) return false;
  const [team, key] = selectedId.split(":");
  if (team === "red") return p(e).scheme_id === key || e.agent === "red" && JSON.stringify(e.payload).includes(key);
  if (team === "blue") return (Array.isArray(p(e).rules_fired) && p(e).rules_fired.some((r: string) => (blueIdForRule(r) ?? `blue:${r}`) === selectedId)) || JSON.stringify(e.payload).includes(`"${key}"`);
  return false;
}

export interface Check { ok: boolean | null; label: string; detail: string }

export interface CheckInput {
  mode: "connecting" | "live" | "recorded";
  healthMs: number | null;
  agents: Record<string, { ok?: boolean }> | null;
  eventsInLastMinute: number;
  lastEventAt: number | null;
  verdicts: number;
  now: number;
  sync: { link: string; quietMs: number; state: SyncState };
  trafficCount: number;
  /** the recorded live-red run being replayed on purpose (`?replay=1`) or for want of a backend: reachability is not a failure then */
  replaying?: string | null;
}

/** The "is it really working" list: each line is a thing we can measure right now. ok === null means "not applicable yet". */
export function liveChecks(i: CheckInput): Check[] {
  const live = i.mode === "live";
  const clients = liveClients(i.sync.state, i.now);
  const arena = clients.find((c) => c.role === "arena");
  const age = (t: number | null) => (t == null ? "never" : `${Math.max(0, Math.round((i.now - t) / 1000))}s ago`);
  const agentList = i.agents ? Object.entries(i.agents) : [];
  return [
    { ok: live ? true : i.replaying ? null : false, label: "battlefield reachable through the /api/bf proxy", detail: live ? `GET /health 200 in ${i.healthMs ?? "?"}ms` : i.mode === "connecting" ? "connecting" : i.replaying ? "not asked: replaying the recorded live-red run" : "no answer: showing the recorded loop" },
    { ok: live ? agentList.length > 0 && agentList.every(([, a]) => a?.ok !== false) : null, label: "agents answer /health", detail: agentList.map(([k, a]) => `${k}:${a?.ok === false ? "down" : "up"}`).join(" ") || "-" },
    { ok: i.lastEventAt != null && i.now - i.lastEventAt < 60_000, label: "event stream delivering", detail: `last event ${age(i.lastEventAt)}, ${i.eventsInLastMinute} in the last minute` },
    { ok: i.verdicts > 0 ? true : null, label: "the gate is issuing verdicts", detail: `${i.verdicts} gate.verdict events` },
    { ok: i.sync.link === "stream" ? true : i.sync.link === "polling" ? null : false, label: "relay to the other laptops", detail: i.sync.link === "admins" ? "admins only (sign in at /admin)" : `${i.sync.link}, last item ${Math.max(0, Math.round(i.sync.quietMs / 1000))}s ago` },
    { ok: arena ? true : false, label: "arena laptop connected", detail: arena ? `${arena.id}, spoke ${Math.max(0, Math.round((i.now - new Date(arena.last).getTime()) / 1000))}s ago` : "not seen in the last 30 s" },
    { ok: i.trafficCount > 0 ? true : null, label: "API calls passing through the proxy", detail: `${i.trafficCount} calls logged` },
  ];
}
