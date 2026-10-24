"use client";
// The browser end of the relay (lib/sync/hub.ts). Owner: Dev R.
//
//   publish(kind, data)   tell the other laptops what happened here (fire and forget, never throws)
//   useSync(role)         read the relay back: shared state, what was said, the API traffic, and who is connected; also announces
//                         this laptop (`hello`) every few seconds so the others can see it is there
//
// Server-Sent Events when the network lets them through, one-second polling when it does not.
import { useEffect, useRef, useState } from "react";
import { emptyState, reduceState, type SyncKind, type SyncMsg, type SyncState, type TrafficRow } from "./hub";

const CAP = 300;
let role = "arena";
let id: string | null = null;

export function setClientRole(r: string) {
  const clean = r.replace(/[^a-zA-Z0-9]/g, "") || "client";
  if (clean !== role) { role = clean; id = null; }
}

/** Stable for this tab, different on every laptop. */
export function clientId(): string {
  if (id) return id;
  try {
    const key = `rl-client-${role}`;
    id = sessionStorage.getItem(key);
    if (!id) { id = `${role}-${Math.random().toString(36).slice(2, 6)}`; sessionStorage.setItem(key, id); }
  } catch {
    id = `${role}-${Math.random().toString(36).slice(2, 6)}`;
  }
  return id;
}

let lastSent = "";
let lastAt = 0;

export function publish(kind: SyncKind, data: Record<string, string | number | boolean | null> = {}): void {
  if (typeof window === "undefined") return;
  const body = JSON.stringify({ client: clientId(), kind, data: { ...data, role } });
  const now = Date.now();
  if (kind !== "hello" && body === lastSent && now - lastAt < 250) return; // a double-fired effect is one message
  lastSent = body;
  lastAt = now;
  void fetch("/api/sync", { method: "POST", headers: { "content-type": "application/json" }, body, keepalive: true }).catch(() => {});
}

export type Link = "connecting" | "stream" | "polling";

export interface SyncView {
  state: SyncState;
  msgs: SyncMsg[];
  traffic: TrafficRow[];
  link: Link;
  /** ms since anything arrived from the relay */
  quietMs: number;
  now: number;
}

export function useSync(r: string): SyncView {
  const [state, setState] = useState<SyncState>(emptyState());
  const [msgs, setMsgs] = useState<SyncMsg[]>([]);
  const [traffic, setTraffic] = useState<TrafficRow[]>([]);
  const [link, setLink] = useState<Link>("connecting");
  const [now, setNow] = useState(() => Date.now());
  const heard = useRef(Date.now());
  const seq = useRef(0);

  useEffect(() => {
    setClientRole(r);
    publish("hello", {});
    const hb = setInterval(() => publish("hello", {}), 8000);
    const tick = setInterval(() => setNow(Date.now()), 1000);
    let es: EventSource | null = null;
    let poll: ReturnType<typeof setInterval> | undefined;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let dead = false;

    const takeMsg = (m: SyncMsg) => {
      if (m.seq <= seq.current && seq.current - m.seq < 1e9 && msgsSeen.has(m.seq)) return;
      msgsSeen.add(m.seq);
      seq.current = Math.max(seq.current, m.seq);
      heard.current = Date.now();
      setState((s) => reduceState(s, m));
      setMsgs((l) => [...l, m].slice(-CAP));
    };
    const takeTraffic = (t: TrafficRow) => {
      if (msgsSeen.has(t.seq)) return;
      msgsSeen.add(t.seq);
      seq.current = Math.max(seq.current, t.seq);
      heard.current = Date.now();
      setTraffic((l) => [...l, t].slice(-CAP));
    };
    const msgsSeen = new Set<number>();
    const apply = (snap: { seq: number; state: SyncState; msgs: SyncMsg[]; traffic: TrafficRow[] }, replace: boolean) => {
      if (replace) { setState(snap.state); msgsSeen.clear(); setMsgs([]); setTraffic([]); }
      snap.msgs.forEach((m) => { msgsSeen.add(m.seq); });
      snap.traffic.forEach((t) => { msgsSeen.add(t.seq); });
      if (replace) { setMsgs(snap.msgs.slice(-CAP)); setTraffic(snap.traffic.slice(-CAP)); }
      else { snap.msgs.forEach((m) => setState((s) => reduceState(s, m))); setMsgs((l) => [...l, ...snap.msgs].slice(-CAP)); setTraffic((l) => [...l, ...snap.traffic].slice(-CAP)); }
      seq.current = Math.max(seq.current, snap.seq);
      heard.current = Date.now();
    };

    const startPolling = () => {
      if (poll || dead) return;
      setLink("polling");
      const run = async () => {
        try {
          const res = await fetch(`/api/sync?after=${seq.current}`, { cache: "no-store" });
          if (res.ok) apply(await res.json(), seq.current === 0);
        } catch { /* next tick */ }
      };
      void run();
      poll = setInterval(run, 1000);
      retry = setTimeout(openStream, 10_000);
    };

    const openStream = () => {
      if (dead) return;
      try {
        es?.close();
        es = new EventSource("/api/sync/stream");
      } catch { startPolling(); return; }
      es.addEventListener("snapshot", (e) => {
        if (poll) { clearInterval(poll); poll = undefined; }
        setLink("stream");
        apply(JSON.parse((e as MessageEvent).data), true);
      });
      es.addEventListener("msg", (e) => takeMsg(JSON.parse((e as MessageEvent).data)));
      es.addEventListener("traffic", (e) => takeTraffic(JSON.parse((e as MessageEvent).data)));
      es.onerror = () => { es?.close(); es = null; startPolling(); };
    };
    openStream();

    return () => { dead = true; clearInterval(hb); clearInterval(tick); clearInterval(poll); clearTimeout(retry); es?.close(); };
  }, [r]);

  return { state, msgs, traffic, link, quietMs: now - heard.current, now };
}
