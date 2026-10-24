// WebSocket client with catch-up. Owner: Dev R.
// Auth: before every (re)connect, fetch a fresh 60 s single-use ticket from the Next server
// (`/api/bf/ws-ticket`, which holds OPERATOR_TOKEN). The socket URL comes back with the ticket
// (`ws_url`, read at request time) rather than from NEXT_PUBLIC_WS_URL here, because client-side
// NEXT_PUBLIC_* values are inlined at build and one image must serve every environment.
import type { RLEvent } from "./types";

interface Ticket {
  ticket: string;
  ws_url: string;
}

const MIN_BACKOFF_MS = 1000;
const MAX_BACKOFF_MS = 15_000;

async function fetchTicket(episodeId: string): Promise<Ticket> {
  const r = await fetch(`/api/bf/ws-ticket?episode_id=${encodeURIComponent(episodeId)}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`ws-ticket → ${r.status}`);
  return r.json();
}

export function connect(episodeId: string, onEvent: (e: RLEvent) => void, afterId = 0): () => void {
  let ws: WebSocket | null = null;
  let closed = false;
  let last = afterId;
  let attempt = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const retry = () => {
    if (closed) return;
    const delay = Math.min(MAX_BACKOFF_MS, MIN_BACKOFF_MS * 2 ** attempt) * (0.75 + Math.random() * 0.5);
    attempt += 1;
    timer = setTimeout(open, delay);
  };

  const open = async () => {
    if (closed) return;
    let t: Ticket;
    try {
      t = await fetchTicket(episodeId);
    } catch {
      return retry();
    }
    if (closed) return;
    const q = `episode_id=${encodeURIComponent(episodeId)}&ticket=${encodeURIComponent(t.ticket)}&after_id=${last}`;
    const sock = new WebSocket(`${t.ws_url}/api/ws?${q}`);
    ws = sock;
    sock.onmessage = (m) => {
      attempt = 0; // a frame arrived, so the ticket was accepted; reset backoff
      const e = JSON.parse(m.data);
      if (e.type === "ping") return;
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
