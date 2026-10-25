// GET /api/sync/stream: the relay as Server-Sent Events. One `snapshot` event on connect (state plus what is kept), then a `msg` or
// `traffic` event per item as it happens. Owner: Dev R.
// Admins only (the laptops), like GET /api/sync. The number of open streams is still capped (lib/ratelimit.ts MAX_SYNC_STREAMS): beyond it, 503 and the client falls back to
// polling GET /api/sync (lib/sync/client.ts).
import { requestRole } from "@/lib/admin";
import { syncStreamSlots } from "@/lib/ratelimit";
import { hub } from "@/lib/sync/hub";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(req: Request): Promise<Response> {
  if (requestRole(req.headers) !== "admin") return Response.json({ error: "viewer" }, { status: 403, headers: { "cache-control": "no-store" } });
  const release = syncStreamSlots().acquire();
  if (!release) {
    return Response.json({ error: "too many streams" }, { status: 503, headers: { "cache-control": "no-store", "retry-after": "10" } });
  }
  const enc = new TextEncoder();
  let off = () => {};
  let ping: ReturnType<typeof setInterval> | undefined;
  const end = () => { off(); clearInterval(ping); release(); };
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      const send = (event: string, data: unknown) => controller.enqueue(enc.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`));
      const close = () => { end(); try { controller.close(); } catch { /* already closed */ } };
      send("snapshot", hub().snapshot(0));
      off = hub().subscribe((item) => send(item.type, item));
      ping = setInterval(() => { try { controller.enqueue(enc.encode(": ping\n\n")); } catch { close(); } }, 15_000);
      if (req.signal.aborted) close();
      else req.signal.addEventListener("abort", close);
    },
    cancel() { end(); },
  });
  return new Response(stream, {
    headers: {
      "content-type": "text/event-stream; charset=utf-8",
      "cache-control": "no-store, no-transform",
      // an event stream must not be compressed or buffered by anything between here and the browser (Caddy, Cloudflare)
      "content-encoding": "identity",
      "x-accel-buffering": "no",
    },
  });
}
