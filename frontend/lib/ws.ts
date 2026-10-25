// WebSocket client with catch-up. Owner: Dev R.
// Auth: before every (re)connect, fetch a fresh 60 s single-use ticket from the Next server
// (`/api/bf/ws-ticket`, which holds OPERATOR_TOKEN). The socket URL comes back with the ticket
// (`ws_url`, read at request time) rather than from NEXT_PUBLIC_WS_URL here, because client-side
// NEXT_PUBLIC_* values are inlined at build and one image must serve every environment.
import { clientId } from "./sync/client";
import type { RLEvent } from "./types";

interface Ticket {
  ticket: string;
  ws_url: string;
}

const MIN_BACKOFF_MS = 1000;
const MAX_BACKOFF_MS = 15_000;
/** A ticket refused this many times in a row for a reason waiting won't fix (400/401/403/404) ends the attempt. */
const MAX_REFUSALS = 5;

class TicketError extends Error {
  constructor(readonly status: number) {
    super(`ws-ticket → ${status}`);
  }
}

/** 4xx other than a timeout or a rate limit: asking again sooner won't change the answer. */
const isRefusal = (err: unknown) => err instanceof TicketError && err.status >= 400 && err.status < 500 && err.status !== 408 && err.status !== 429;

async function fetchTicket(episodeId: string): Promise<Ticket> {
  const r = await fetch(`/api/bf/ws-ticket?episode_id=${encodeURIComponent(episodeId)}`, { cache: "no-store", headers: { "X-RL-Client": clientId() } });
  if (!r.ok) throw new TicketError(r.status);
  return r.json();
}

export function connect(episodeId: string, onEvent: (e: RLEvent) => void, afterId = 0): () => void {
  let ws: WebSocket | null = null;
  let closed = false;
  let last = afterId;
  let attempt = 0;
  let refusals = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;

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
      if (!isRefusal(err)) { refusals = 0; return retry(); }
      // a stale or unknown episode: try a few more times slowly, then stop instead of polling the ticket route forever
      refusals += 1;
      if (refusals >= MAX_REFUSALS) { console.warn(`ws: ticket for ${episodeId} refused ${refusals} times; giving up`); return; }
      return retry(true);
    }
    refusals = 0;
    if (closed) return;
    const q = `episode_id=${encodeURIComponent(episodeId)}&ticket=${encodeURIComponent(t.ticket)}&after_id=${last}`;
    const sock = new WebSocket(`${t.ws_url}/api/ws?${q}`);
    ws = sock;
    sock.onmessage = (m) => {
      attempt = 0; // a frame arrived, so the ticket was accepted; reset backoff
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
    sock.onclose = () => {
      if (ws === sock) ws = null;
      retry();
    };
  };

  void open();
  return () => {
    closed = true;
    clearTimeout(timer);
    ws?.close();
  };
}
