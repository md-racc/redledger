// WebSocket client with catch-up. Owner: Dev R.
// Auth: before every (re)connect, fetch a fresh 60 s single-use ticket from the Next server
// (`/api/bf/ws-ticket`, which holds OPERATOR_TOKEN). The socket URL comes back with the ticket
// (`ws_url`, read at request time) rather than from NEXT_PUBLIC_WS_URL here, because client-side
// NEXT_PUBLIC_* values are inlined at build and one image must serve every environment.
//
// A socket is not always possible: a venue network or proxy that drops or swallows the upgrade (the handshake then never answers,
// so it gets 8 s), a dev server with no `/api/ws`, a ticket that keeps hitting a rate limit or a 5xx. After two attempts in a row
// that never delivered a frame the client also reads the same events over REST (`GET /events?after_id=`, through the same proxy)
// every 1.5 s, and keeps trying the socket underneath; the first frame a socket delivers ends the polling. The reducer is
// idempotent and polled events are filtered on `id > last`, so the two never double up. A ticket refused for a reason waiting
// won't fix (400/401/403/404: a stale episode, no access) is not worked around: REST would be refused too, so after a few slow
// retries the attempt ends.
import { clientId } from "./sync/client";
import type { RLEvent } from "./types";

interface Ticket {
  ticket: string;
  ws_url: string;
}

/** How events are reaching this window right now, for a console that wants to say so. */
export interface FeedLink {
  via: "connecting" | "socket" | "polling" | "down";
  detail: string;
}

const MIN_BACKOFF_MS = 1000;
const MAX_BACKOFF_MS = 15_000;
/** A ticket refused this many times in a row for a reason waiting won't fix (400/401/403/404) ends the attempt. */
const MAX_REFUSALS = 5;
/** socket attempts in a row without a frame before the REST fallback starts */
const POLL_AFTER_FAILS = 2;
const POLL_MS = 1500;
const POLL_PAGE = 500;
/** how long a socket may take to complete its handshake before it counts as failed */
const HANDSHAKE_MS = 8000;

class TicketError extends Error {
  constructor(readonly status: number) {
    super(`ws-ticket → ${status}`);
  }
}

/** 4xx other than a timeout or a rate limit: asking again sooner won't change the answer. */
const isRefusal = (err: unknown) => err instanceof TicketError && err.status >= 400 && err.status < 500 && err.status !== 408 && err.status !== 429;

const HEADERS = () => ({ "X-RL-Client": clientId() });

async function fetchTicket(episodeId: string): Promise<Ticket> {
  const r = await fetch(`/api/bf/ws-ticket?episode_id=${encodeURIComponent(episodeId)}`, { cache: "no-store", headers: HEADERS() });
  if (!r.ok) throw new TicketError(r.status);
  return r.json();
}

async function fetchEvents(episodeId: string, afterId: number): Promise<RLEvent[]> {
  const r = await fetch(`/api/bf/events?episode_id=${encodeURIComponent(episodeId)}&after_id=${afterId}&limit=${POLL_PAGE}`, { cache: "no-store", headers: HEADERS(), signal: AbortSignal.timeout(8000) });
  if (!r.ok) throw new Error(`events → ${r.status}`);
  const body = await r.json();
  return Array.isArray(body) ? (body as RLEvent[]) : [];
}

export function connect(episodeId: string, onEvent: (e: RLEvent) => void, afterId = 0, onLink?: (l: FeedLink) => void): () => void {
  let ws: WebSocket | null = null;
  let closed = false;
  let last = afterId;
  let attempt = 0;
  let refusals = 0;
  let fails = 0;
  let why = "no socket yet";
  let timer: ReturnType<typeof setTimeout> | undefined;
  let pollTimer: ReturnType<typeof setTimeout> | undefined;
  let guard: ReturnType<typeof setTimeout> | undefined;
  let polling = false;
  let shown = "";

  const tell = (l: FeedLink) => {
    const key = `${l.via}|${l.detail}`;
    if (key === shown) return;
    shown = key;
    onLink?.(l);
  };

  const poll = async () => {
    if (closed || !polling) return;
    let more = false;
    try {
      const page = await fetchEvents(episodeId, last);
      if (closed || !polling) return;
      const fresh = page.filter((e) => typeof e.id === "number" && e.id > last).sort((a, b) => (a.id as number) - (b.id as number));
      for (const e of fresh) {
        last = Math.max(last, e.id as number);
        onEvent(e);
      }
      more = page.length >= POLL_PAGE && fresh.length > 0;
      tell({ via: "polling", detail: `the socket does not connect (${why}); reading /events over REST every ${POLL_MS / 1000}s` });
    } catch (err) {
      tell({ via: "down", detail: `the socket does not connect (${why}) and ${err instanceof Error ? err.message : "the REST read failed"}` });
    }
    if (!closed && polling) pollTimer = setTimeout(poll, more ? 0 : POLL_MS);
  };

  const failed = (reason: string) => {
    fails += 1;
    why = reason;
    if (fails >= POLL_AFTER_FAILS && !polling && !closed) {
      polling = true;
      void poll();
    }
  };

  const retry = (refused = false) => {
    if (closed) return;
    const delay = (refused ? MAX_BACKOFF_MS : Math.min(MAX_BACKOFF_MS, MIN_BACKOFF_MS * 2 ** attempt)) * (0.75 + Math.random() * 0.5);
    attempt += 1;
    timer = setTimeout(open, delay);
  };

  const open = async () => {
    if (closed) return;
    let t: Ticket;
    try {
      t = await fetchTicket(episodeId);
    } catch (err) {
      const reason = err instanceof Error ? err.message : "ws-ticket failed";
      if (!isRefusal(err)) { refusals = 0; failed(reason); return retry(); }
      // a stale or unknown episode, or no access: REST would be refused too. Try a few more times slowly, then stop instead of
      // polling the ticket route forever
      refusals += 1;
      if (refusals >= MAX_REFUSALS) {
        console.warn(`ws: ticket for ${episodeId} refused ${refusals} times; giving up`);
        tell({ via: "down", detail: `${reason}, ${refusals} times in a row: gave up` });
        return;
      }
      tell({ via: "down", detail: `${reason}: asking again slowly` });
      return retry(true);
    }
    refusals = 0;
    if (closed) return;
    const q = `episode_id=${encodeURIComponent(episodeId)}&ticket=${encodeURIComponent(t.ticket)}&after_id=${last}`;
    const sock = new WebSocket(`${t.ws_url}/api/ws?${q}`);
    ws = sock;
    let framed = false;
    // a handshake nobody answers (a network that swallows the upgrade) never fires onclose: give up on it ourselves
    guard = setTimeout(() => {
      if (ws !== sock || closed) return;
      sock.onclose = null;
      sock.onopen = null;
      ws = null;
      try { sock.close(); } catch { /* already gone */ }
      failed(`no answer to the websocket handshake in ${HANDSHAKE_MS / 1000}s`);
      retry();
    }, HANDSHAKE_MS);
    sock.onopen = () => {
      clearTimeout(guard);
      tell({ via: "socket", detail: "websocket open" });
    };
    sock.onmessage = (m) => {
      clearTimeout(guard);
      attempt = 0; // a frame arrived, so the ticket was accepted; reset backoff
      if (!framed) {
        framed = true;
        fails = 0;
        polling = false; // the socket works: stop reading over REST
        clearTimeout(pollTimer);
        tell({ via: "socket", detail: "websocket open" });
      }
      let e: RLEvent & { type: string };
      try {
        e = JSON.parse(m.data);
      } catch {
        return; // a malformed frame is dropped; the next good one carries on (and after_id catch-up fills any gap on reconnect)
      }
      if (!e || typeof e !== "object" || e.type === "ping") return;
      last = Math.max(last, e.id ?? last);
      onEvent(e);
    };
    // Any close we didn't ask for (incl. 4401 bad/expired ticket) → new ticket, reconnect with backoff.
    // `after_id=last` on the next socket replays whatever we missed.
    sock.onclose = (ev?: { code?: number }) => {
      clearTimeout(guard);
      if (ws === sock) ws = null;
      if (!framed) failed(`socket closed before any frame, code ${ev?.code ?? "?"}`);
      retry();
    };
  };

  tell({ via: "connecting", detail: "asking for a ticket" });
  void open();
  return () => {
    closed = true;
    polling = false;
    clearTimeout(timer);
    clearTimeout(pollTimer);
    clearTimeout(guard);
    ws?.close();
  };
}
