// WebSocket client with catch-up. Owner: Dev R.
import type { RLEvent } from "./types";

const WS = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000";
const TOKEN = process.env.NEXT_PUBLIC_INTERNAL_TOKEN ?? "change-me";

export function connect(episodeId: string, onEvent: (e: RLEvent) => void, afterId = 0): () => void {
  let ws: WebSocket | null = null;
  let closed = false;
  let last = afterId;
  const open = () => {
    ws = new WebSocket(`${WS}/api/ws?episode_id=${encodeURIComponent(episodeId)}&token=${encodeURIComponent(TOKEN)}&after_id=${last}`);
    ws.onmessage = (m) => {
      const e = JSON.parse(m.data);
      if (e.type === "ping") return;
      last = Math.max(last, e.id ?? last);
      onEvent(e);
    };
    ws.onclose = () => { if (!closed) setTimeout(open, 1000); };
  };
  open();
  return () => { closed = true; ws?.close(); };
}
