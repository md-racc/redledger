// GET /api/sync/stream: the relay as Server-Sent Events. One `snapshot` event on connect (state plus what is kept), then a `msg` or
// `traffic` event per item as it happens. Owner: Dev R.
import { hub } from "@/lib/sync/hub";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(req: Request): Promise<Response> {
  const enc = new TextEncoder();
  let off = () => {};
  let ping: ReturnType<typeof setInterval> | undefined;
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      const send = (event: string, data: unknown) => controller.enqueue(enc.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`));
      const close = () => { off(); clearInterval(ping); try { controller.close(); } catch { /* already closed */ } };
      send("snapshot", hub().snapshot(0));
      off = hub().subscribe((item) => send(item.type, item));
      ping = setInterval(() => { try { controller.enqueue(enc.encode(": ping\n\n")); } catch { close(); } }, 15_000);
      req.signal.addEventListener("abort", close);
    },
    cancel() { off(); clearInterval(ping); },
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
