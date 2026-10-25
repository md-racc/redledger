// What the raw consoles print: event lines, the live checks, which lines belong to which team, and which lines the arena's current
// selection points at. Pure, tested. Owner: Dev R.
import type { RLEvent } from "@/lib/types";
import type { SyncMsg, SyncState, TrafficRow } from "@/lib/sync/hub";
import { liveClients } from "@/lib/sync/hub";
import { blueIdForRule } from "@/lib/arena/roster";
import type { FeedLink } from "@/lib/ws";

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

/** `adminOnly`: a check a viewer cannot make (the relay answers admins only): neutral, never a failure. */
export interface Check { ok: boolean | null; label: string; detail: string; adminOnly?: boolean }

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
  /** how events reach this window (live mode): lib/ws.ts's own report of the socket, or of the REST read it falls back to */
  feed?: FeedLink | null;
  /** while "connecting": what the proxy last refused with (403, 401, 429), which is not a network failure, so no recorded loop */
  answer?: string | null;
  /** status of the followed episode, and how many of its events this window holds: an episode that is not running has nothing new to say */
  episodeStatus?: string | null;
  eventsHeld?: number;
  /** this browser is a viewer: the relay and the laptops on it are admins' business, so those checks read "admin only", not FAIL */
  viewer?: boolean;
}

/** "Is the event stream delivering?" A quiet stream is a fault only when something is running, or when no way in works. */
function streamCheck(i: CheckInput, age: (t: number | null) => string): Check {
  const label = "event stream delivering";
  const fresh = i.lastEventAt != null && i.now - i.lastEventAt < 60_000;
  const recent = `last event ${age(i.lastEventAt)}, ${i.eventsInLastMinute} in the last minute`;
  const f = i.mode === "live" ? i.feed : null;
  if (!f) return { ok: fresh, label, detail: recent };
  const via = f.via === "socket" ? " (websocket)" : f.via === "polling" ? " (REST fallback: the websocket would not open)" : "";
  if (f.via === "down") return { ok: false, label, detail: `no way in: ${f.detail}` };
  if (fresh) return { ok: true, label, detail: `${recent}${via}` };
  if (f.via === "connecting") return { ok: null, label, detail: `connecting: ${f.detail}` };
  const held = i.eventsHeld ?? 0;
  if (i.episodeStatus && i.episodeStatus !== "running") {
    return held > 0
      ? { ok: true, label, detail: `idle: episode ${i.episodeStatus}, ${held} events delivered, nothing new to send${via}` }
      : { ok: null, label, detail: `idle: episode ${i.episodeStatus}, nothing to deliver yet${via}` };
  }
  return { ok: false, label, detail: `${recent}${via}` };
}

/** The "is it really working" list: each line is a thing we can measure right now. ok === null means "not applicable yet". */
export function liveChecks(i: CheckInput): Check[] {
  const live = i.mode === "live";
  const clients = liveClients(i.sync.state, i.now);
  const arena = clients.find((c) => c.role === "arena");
  const age = (t: number | null) => (t == null ? "never" : `${Math.max(0, Math.round((i.now - t) / 1000))}s ago`);
  const agentList = i.agents ? Object.entries(i.agents) : [];
  // the relay answers admins only (app/api/sync): for a viewer, what it would tell is not a fault, just not theirs to see
  const adminOnly = i.viewer || i.sync.link === "admins";
  const hidden = (label: string): Check => ({ ok: null, label, detail: "admin only", adminOnly: true });
  return [
    { ok: live ? true : i.replaying ? null : false, label: "battlefield reachable through the /api/bf proxy", detail: live ? `GET /health 200 in ${i.healthMs ?? "?"}ms` : i.mode === "connecting" ? (i.answer ? `refused, not unreachable: ${i.answer}` : "connecting") : i.replaying ? "not asked: replaying the recorded live-red run" : "no answer: showing the recorded loop" },
    { ok: live ? agentList.length > 0 && agentList.every(([, a]) => a?.ok !== false) : null, label: "agents answer /health", detail: agentList.map(([k, a]) => `${k}:${a?.ok === false ? "down" : "up"}`).join(" ") || "-" },
    streamCheck(i, age),
    { ok: i.verdicts > 0 ? true : null, label: "the gate is issuing verdicts", detail: `${i.verdicts} gate.verdict events` },
    adminOnly ? hidden("relay to the other laptops") : { ok: i.sync.link === "stream" ? true : i.sync.link === "polling" ? null : false, label: "relay to the other laptops", detail: `${i.sync.link}, last item ${Math.max(0, Math.round(i.sync.quietMs / 1000))}s ago` },
    adminOnly ? hidden("arena laptop connected") : { ok: arena ? true : false, label: "arena laptop connected", detail: arena ? `${arena.id}, spoke ${Math.max(0, Math.round((i.now - new Date(arena.last).getTime()) / 1000))}s ago` : "not seen in the last 30 s: open the arena on the first laptop and sign in at /admin (a viewer's arena shows but does not report)" },
    { ok: i.trafficCount > 0 ? true : null, label: "API calls passing through the proxy", detail: `${i.trafficCount} calls logged` },
  ];
}
