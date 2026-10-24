// Same-origin proxy: /api/bf/<path>?<query> → ${BATTLEFIELD_URL}/api/<path>?<query>. Owner: Dev R.
// Adds `Authorization: Bearer ${OPERATOR_TOKEN}` server-side; the browser never holds a token.
// Both vars are server env (no NEXT_PUBLIC_), read per request, never at build time.
import {
  downstreamResponseHeaders,
  hasBody,
  isCrossSiteMutation,
  isNullBodyStatus,
  isTimeout,
  jsonError,
  timeoutFor,
  upstreamConfig,
  upstreamPath,
  upstreamRequestHeaders,
  upstreamUrl,
} from "@/lib/proxy";
import { hub } from "@/lib/sync/hub";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

async function forwardInner(req: Request): Promise<Response> {
  const method = req.method.toUpperCase();
  if (isCrossSiteMutation(method, req.headers)) return jsonError(403, "cross-site request refused");

  const cfg = upstreamConfig();
  if (!cfg) return jsonError(502, "battlefield proxy is not configured");

  // Raw pathname keeps percent-encoding, so encoded `/` or `..` can be rejected, not decoded.
  const url = new URL(req.url);
  const path = upstreamPath(url.pathname);
  if (!path) return jsonError(400, "invalid path");
  const target = upstreamUrl(cfg.battlefieldUrl, path, url.search);
  if (!target) return jsonError(502, "battlefield proxy is misconfigured");

  // Request bodies here are small JSON; buffering avoids undici's `duplex: "half"` streaming quirks.
  const body = hasBody(method) ? await req.arrayBuffer() : undefined;

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method,
      headers: upstreamRequestHeaders(req.headers, cfg.operatorToken),
      body: body && body.byteLength > 0 ? body : undefined,
      cache: "no-store",
      // The timeout also bounds reading the streamed response body.
      signal: AbortSignal.timeout(timeoutFor(method, path)),
    });
  } catch (err) {
    return isTimeout(err) ? jsonError(504, "battlefield timed out") : jsonError(502, "battlefield unreachable");
  }

  const headers = downstreamResponseHeaders(upstream.headers);
  headers.set("cache-control", headers.get("cache-control") ?? "no-store");
  // Stream the upstream body straight through (large /events pages, report markdown, ...).
  const out = isNullBodyStatus(upstream.status) || method === "HEAD" ? null : upstream.body;
  return new Response(out, { status: upstream.status, statusText: upstream.statusText, headers });
}

/** Every call is noted (method, path, status, time, which laptop) for the backstage traffic log; see lib/sync/hub.ts. */
async function forward(req: Request): Promise<Response> {
  const t0 = performance.now();
  const res = await forwardInner(req);
  try {
    const u = new URL(req.url);
    hub().recordTraffic({ method: req.method.toUpperCase(), path: `${upstreamPath(u.pathname) ?? u.pathname}${u.search.length > 60 ? "?…" : u.search}`, status: res.status, ms: performance.now() - t0, client: req.headers.get("x-rl-client") ?? "" });
  } catch { /* logging must never break a request */ }
  return res;
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const PATCH = forward;
export const DELETE = forward;
