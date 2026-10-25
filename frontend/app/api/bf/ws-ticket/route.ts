// GET /api/bf/ws-ticket?episode_id= → { ticket, expires_at, ws_url }. Owner: Dev R.
// Exchanges the server-held OPERATOR_TOKEN for a 60 s, single-use, episode-scoped WS ticket
// (battlefield `POST /api/ws/ticket`). `ws_url` is NEXT_PUBLIC_WS_URL read at request time, so
// one image serves every environment (client code would get it inlined at build instead).
// The stream is read-only, so viewers get tickets too; like the proxy they are rate limited per address (admins are not).
import { clientIp, requestRole } from "@/lib/admin";
import { isTimeout, jsonError, runtimeEnv, upstreamConfig, upstreamUrl } from "@/lib/proxy";
import { limiter, tooMany } from "@/lib/ratelimit";
import { hub } from "@/lib/sync/hub";
import { wsBaseUrl } from "@/lib/wsurl";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(req: Request): Promise<Response> {
  const admin = requestRole(req.headers) === "admin";
  if (!admin) {
    const rl = limiter("viewer").take(clientIp(req.headers));
    if (!rl.ok) return tooMany(rl.retryAfterSec);
  }
  const cfg = upstreamConfig();
  if (!cfg) return jsonError(502, "battlefield proxy is not configured");
  const target = upstreamUrl(cfg.battlefieldUrl, "/api/ws/ticket", "");
  if (!target) return jsonError(502, "battlefield proxy is misconfigured");

  const episodeId = new URL(req.url).searchParams.get("episode_id") || null;
  // a ticket without an episode is good for every episode's stream; only the laptops need that
  if (!admin && !episodeId) return jsonError(400, "episode_id required");

  const t0 = performance.now();
  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: "POST",
      headers: { authorization: `Bearer ${cfg.operatorToken}`, "content-type": "application/json", accept: "application/json" },
      body: JSON.stringify({ episode_id: episodeId }),
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
  } catch (err) {
    return isTimeout(err) ? jsonError(504, "battlefield timed out") : jsonError(502, "battlefield unreachable");
  }
  if (admin) hub().recordTraffic({ method: "POST", path: "/ws/ticket", status: upstream.status, ms: performance.now() - t0, client: req.headers.get("x-rl-client") ?? "" });
  if (!upstream.ok) return jsonError(upstream.status >= 500 ? 502 : upstream.status, `ticket request failed (${upstream.status})`);

  let data: { ticket?: unknown; expires_at?: unknown };
  try {
    data = await upstream.json();
  } catch {
    return jsonError(502, "bad ticket response");
  }
  if (typeof data.ticket !== "string") return jsonError(502, "bad ticket response");

  const wsUrl = wsBaseUrl(runtimeEnv("NEXT_PUBLIC_WS_URL"), req.headers, req.url);
  return Response.json(
    { ticket: data.ticket, expires_at: data.expires_at ?? null, ws_url: wsUrl },
    { headers: { "cache-control": "no-store" } },
  );
}
