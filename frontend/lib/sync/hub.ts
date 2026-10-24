// The relay between laptops. Owner: Dev R.
//
// The demo runs on four laptops on one domain: the arena, and a backstage console each for red, green and blue. They are separate
// browsers, so whatever is selected or done on the arena has to travel through something they all reach. Caddy sends everything
// but /api/ws to the one frontend container, so this module (held on globalThis, shared by every route handler in the process)
// is that something: the arena POSTs what the visitor did, every console reads it back (SSE, or polling as a fallback).
//
// It also keeps a log of the calls the /api/bf proxy made to battlefield, so a console can show the API traffic of all four
// laptops. In memory only, capped, nothing persisted: a restart empties it. One Node process only (a second container would
// have its own hub); fine for the stage, see docs/backstage.md.
export const KINDS = ["hello", "select", "launch", "controller", "decision", "show", "panel", "stage", "run", "act"] as const;
export type SyncKind = (typeof KINDS)[number];
type Prim = string | number | boolean | null;

export interface SyncMsg { type: "msg"; seq: number; ts: string; client: string; kind: SyncKind; data: Record<string, Prim> }
export interface TrafficRow { type: "traffic"; seq: number; ts: string; method: string; path: string; status: number; ms: number; client: string }
export type SyncItem = SyncMsg | TrafficRow;

export interface SyncState {
  selected: { id: string; name: string; team: string } | null;
  panel: string | null;
  stage: string | null;
  show: { status: string; beat: string | null } | null;
  controller: string | null;
  act: { act: string; live: boolean } | null;
  /** who is connected: client id → role and when it last spoke */
  clients: Record<string, { role: string; last: string }>;
}

const CAP = 300;
const MAX_STR = 160;

export function emptyState(): SyncState {
  return { selected: null, panel: null, stage: null, show: null, controller: null, act: null, clients: {} };
}

const str = (v: unknown, n = MAX_STR): string => String(v ?? "").slice(0, n);

/** Anything a client sends is reduced to a small flat object of primitives. */
export function clean(input: unknown): { client: string; kind: SyncKind; data: Record<string, Prim> } | null {
  if (!input || typeof input !== "object") return null;
  const o = input as Record<string, unknown>;
  const kind = o.kind as SyncKind;
  if (!KINDS.includes(kind)) return null;
  const client = str(o.client, 40).replace(/[^a-zA-Z0-9:_-]/g, "");
  if (!client) return null;
  const data: Record<string, Prim> = {};
  const src = o.data && typeof o.data === "object" ? (o.data as Record<string, unknown>) : {};
  for (const [k, v] of Object.entries(src).slice(0, 12)) {
    if (typeof v === "string") data[str(k, 24)] = str(v);
    else if (typeof v === "number" && Number.isFinite(v)) data[str(k, 24)] = v;
    else if (typeof v === "boolean" || v === null) data[str(k, 24)] = v;
  }
  return { client, kind, data };
}

export function reduceState(s: SyncState, m: SyncMsg): SyncState {
  const next: SyncState = { ...s, clients: { ...s.clients, [m.client]: { role: String(m.data.role ?? s.clients[m.client]?.role ?? "?"), last: m.ts } } };
  const d = m.data;
  switch (m.kind) {
    case "select": next.selected = d.id ? { id: String(d.id), name: String(d.name ?? d.id), team: String(d.team ?? "") } : null; break;
    case "panel": next.panel = d.panel ? String(d.panel) : null; break;
    case "stage": next.stage = String(d.stage ?? ""); break;
    case "show": next.show = { status: String(d.status ?? ""), beat: d.beat ? String(d.beat) : null }; break;
    case "controller": next.controller = String(d.mode ?? ""); break;
    case "act": next.act = { act: String(d.act ?? ""), live: d.live === true }; break;
    default: break;
  }
  return next;
}

type Listener = (item: SyncItem) => void;

export class Hub {
  seq = 0;
  state: SyncState = emptyState();
  msgs: SyncMsg[] = [];
  traffic: TrafficRow[] = [];
  private listeners = new Set<Listener>();

  publish(input: unknown, now = new Date()): SyncMsg | null {
    const c = clean(input);
    if (!c) return null;
    const m: SyncMsg = { type: "msg", seq: ++this.seq, ts: now.toISOString(), client: c.client, kind: c.kind, data: c.data };
    this.msgs.push(m);
    if (this.msgs.length > CAP) this.msgs.splice(0, this.msgs.length - CAP);
    this.state = reduceState(this.state, m);
    this.emit(m);
    return m;
  }

  recordTraffic(t: { method: string; path: string; status: number; ms: number; client?: string }, now = new Date()): TrafficRow {
    const row: TrafficRow = { type: "traffic", seq: ++this.seq, ts: now.toISOString(), method: str(t.method, 8), path: str(t.path), status: t.status, ms: Math.round(t.ms), client: str(t.client ?? "", 40).replace(/[^a-zA-Z0-9:_-]/g, "") };
    this.traffic.push(row);
    if (this.traffic.length > CAP) this.traffic.splice(0, this.traffic.length - CAP);
    this.emit(row);
    return row;
  }

  /** everything newer than `after` (0 = all that is kept), plus the current state */
  snapshot(after = 0) {
    return { seq: this.seq, state: this.state, msgs: this.msgs.filter((m) => m.seq > after), traffic: this.traffic.filter((t) => t.seq > after) };
  }

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => { this.listeners.delete(fn); };
  }

  private emit(item: SyncItem) {
    for (const fn of this.listeners) { try { fn(item); } catch { /* a dead stream must not break the others */ } }
  }
}

/** One hub per process, whichever route module asks for it. */
export function hub(): Hub {
  const g = globalThis as unknown as { __rlHub?: Hub };
  return (g.__rlHub ??= new Hub());
}

/** Clients that spoke in the last `withinMs`. */
export function liveClients(state: SyncState, now = Date.now(), withinMs = 30_000) {
  return Object.entries(state.clients).filter(([, c]) => now - new Date(c.last).getTime() <= withinMs).map(([id, c]) => ({ id, role: c.role, last: c.last }));
}
