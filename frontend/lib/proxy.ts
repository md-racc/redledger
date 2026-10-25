// Server-only helpers for the battlefield proxy (app/api/bf/**). Owner: Dev R.
// Pure functions so the path/header rewrite is unit-testable without Next or a backend.
// The browser never sees OPERATOR_TOKEN: route handlers add it here, server-side, per request.

/** Prefix the browser calls; `/api/bf/<path>` is forwarded to `${BATTLEFIELD_URL}/api/<path>`. */
export const PROXY_PREFIX = "/api/bf/";

/** Default upstream timeout. Control-plane and read calls are quick. */
export const DEFAULT_TIMEOUT_MS = 30_000;
/** `POST /episodes/{id}/step` runs a whole day with live agents; that can take minutes. */
export const STEP_TIMEOUT_MS = 300_000;

// RFC 9110 §7.6.1 hop-by-hop headers plus ones fetch/undici must compute itself.
export const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "proxy-connection",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
  "host",
  "content-length",
]);

// Allowlists, not denylists: anything not named here (Authorization, Cookie, X-Agent, X-Episode,
// X-Forwarded-*, ...) never reaches battlefield or the browser.
const REQUEST_HEADERS = ["content-type", "accept"];
// content-encoding is deliberately absent: undici decompresses upstream bodies.
const RESPONSE_HEADERS = ["content-type", "content-disposition", "cache-control", "retry-after"];

export type Env = Record<string, string | undefined>;

/**
 * Read an env var at request time. The computed key keeps Next's build-time inlining of
 * `process.env.NEXT_PUBLIC_*` literals from baking a value into the server bundle.
 */
export function runtimeEnv(name: string, env: Env = process.env): string | undefined {
  const v = env[name];
  return v === undefined || v.trim() === "" ? undefined : v.trim();
}

export interface UpstreamConfig {
  battlefieldUrl: string;
  operatorToken: string;
}

/** Null when either server var is missing. Callers answer 502 without naming the values. */
export function upstreamConfig(env: Env = process.env): UpstreamConfig | null {
  const battlefieldUrl = runtimeEnv("BATTLEFIELD_URL", env);
  const operatorToken = runtimeEnv("OPERATOR_TOKEN", env);
  if (!battlefieldUrl || !operatorToken) return null;
  return { battlefieldUrl: battlefieldUrl.replace(/\/+$/, ""), operatorToken };
}

/**
 * Turn the raw (still percent-encoded) request pathname under `/api/bf/` into the battlefield
 * path under `/api/`. Returns null for anything that could escape `/api/` or change host:
 * `..`/`.` segments (raw or encoded), encoded slashes or backslashes, empty segments
 * (`//evil.example`), schemes (`http:`), control characters.
 */
export function upstreamPath(pathname: string): string | null {
  if (!pathname.startsWith(PROXY_PREFIX)) return null;
  const rest = pathname.slice(PROXY_PREFIX.length);
  if (rest === "") return null;
  const segments = rest.split("/");
  for (const raw of segments) {
    if (raw === "") return null;
    let seg: string;
    try {
      seg = decodeURIComponent(raw);
    } catch {
      return null;
    }
    if (seg === "." || seg === "..") return null;
    if (/[/\\?#]/.test(seg) || /[\u0000-\u001f\u007f]/.test(seg)) return null;
    if (raw.includes("\\")) return null;
  }
  if (/^[a-z][a-z0-9+.-]*:/i.test(segments[0]!)) return null;
  return `/api/${rest}`;
}

/**
 * Battlefield routes that carry ground truth ("Operator only") and that no viewer screen needs: admins only, even for GET.
 * Matched on the decoded, lower-cased upstream path segments, so `%65xport`, `EXPORT` or a trailing slash can't slip past.
 * They say which rows are red's (attacks and their invoices, red's tool-call args, agent memory) or score blue against origin.
 */
const OPERATOR_ONLY: RegExp[] = [
  /^\/api\/lineages\/[^/]+\/export$/,
  /^\/api\/attacks(\/.*)?$/,
  /^\/api\/audit_log$/,
  /^\/api\/state(\/.*)?$/,
  /^\/api\/fe\/compare$/,
  /^\/api\/fe\/episodes\/[^/]+\/attacks$/,
  /^\/api\/fe\/episodes\/[^/]+\/entities\/.*$/,
  /^\/api\/fe\/episodes\/[^/]+\/state\/.*$/,
  /^\/api\/fe\/episodes\/[^/]+\/verdicts\/(rules|confusion)$/,
];

/** Ground-truth keys battlefield includes for the operator. Removed from every JSON answer a viewer gets. */
const GROUND_TRUTH_KEYS = new Set(["origin", "entity_origin", "origin_of_source"]);

/** A copy of a parsed JSON body with every ground-truth key removed, at any depth. */
export function stripGroundTruth(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stripGroundTruth);
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value)) if (!GROUND_TRUTH_KEYS.has(k)) out[k] = stripGroundTruth(v);
    return out;
  }
  return value;
}

/** The upstream path decoded and lower-cased per segment; null for an invalid path, "" when it can't be decoded. */
function normalizedPath(pathname: string): string | null {
  const path = upstreamPath(pathname.replace(/\/+$/, ""));
  if (!path) return null; // refused as an invalid path anyway, never forwarded
  try {
    return path.split("/").map((s) => decodeURIComponent(s).toLowerCase()).join("/");
  } catch {
    return "";
  }
}

export function isOperatorOnlyPath(pathname: string): boolean {
  const normalized = normalizedPath(pathname);
  if (normalized === null) return false;
  return normalized === "" || OPERATOR_ONLY.some((re) => re.test(normalized));
}

/**
 * Reads that are made of ground truth but are the point of the public report once a run is over: a viewer gets them only when
 * battlefield's answer says `final: true` (the controls assessment, /report/[ep]). Before that the answer would say, mid-run,
 * which rows are red's. Admins always get them.
 */
const FINAL_ONLY: RegExp[] = [/^\/api\/fe\/episodes\/[^/]+\/controls$/];

export function isFinalOnlyPath(pathname: string): boolean {
  const normalized = normalizedPath(pathname);
  if (normalized === null) return false;
  return normalized === "" || FINAL_ONLY.some((re) => re.test(normalized));
}

/** A final-only answer a viewer may have: a JSON object whose `final` is exactly true. */
export function isFinalAnswer(body: unknown): boolean {
  return !!body && typeof body === "object" && !Array.isArray(body) && (body as { final?: unknown }).final === true;
}

/** What a viewer gets for a final-only read before the run ends. */
export function notFinalYet(): Response {
  return new Response(JSON.stringify({ error: "viewer", detail: "available when the run ends" }), {
    status: 403,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}

/** Full upstream URL, re-checked so it can only land on battlefield's origin under `/api/`. */
export function upstreamUrl(battlefieldUrl: string, path: string, search: string): string | null {
  let base: URL;
  try {
    base = new URL(battlefieldUrl);
  } catch {
    return null;
  }
  const basePath = base.pathname.replace(/\/+$/, "");
  const target = new URL(`${base.origin}${basePath}${path}${search}`);
  if (target.origin !== base.origin || !target.pathname.startsWith(`${basePath}/api/`)) return null;
  return target.toString();
}

/** Headers sent to battlefield: the allowlist from the browser plus the operator bearer. */
export function upstreamRequestHeaders(incoming: Headers, operatorToken: string): Headers {
  const out = new Headers();
  for (const name of REQUEST_HEADERS) {
    const v = incoming.get(name);
    if (v !== null) out.set(name, v);
  }
  out.set("authorization", `Bearer ${operatorToken}`);
  return out;
}

/** Headers returned to the browser: allowlisted, never hop-by-hop, never auth-bearing. */
export function downstreamResponseHeaders(upstream: Headers): Headers {
  const out = new Headers();
  for (const name of RESPONSE_HEADERS) {
    if (HOP_BY_HOP.has(name)) continue;
    const v = upstream.get(name);
    if (v !== null) out.set(name, v);
  }
  return out;
}

export function timeoutFor(method: string, path: string): number {
  return method === "POST" && /^\/api\/episodes\/[^/]+\/step$/.test(path) ? STEP_TIMEOUT_MS : DEFAULT_TIMEOUT_MS;
}

/**
 * Cheap CSRF guard for a relay that holds a write-capable token: browsers stamp
 * `Sec-Fetch-Site`, pages cannot forge it. Same-origin and same-site (app. → api.) pass; curl
 * sends nothing and passes; only a cross-site page trying to mutate is refused.
 */
export function isCrossSiteMutation(method: string, headers: Headers): boolean {
  if (method === "GET" || method === "HEAD") return false;
  return headers.get("sec-fetch-site") === "cross-site";
}

export function hasBody(method: string): boolean {
  return method !== "GET" && method !== "HEAD";
}

/** Status codes whose response must not carry a body (Response() throws otherwise). */
export function isNullBodyStatus(status: number): boolean {
  return status === 101 || status === 204 || status === 205 || status === 304;
}

export function jsonError(status: number, error: string): Response {
  return new Response(JSON.stringify({ error }), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}

export function isTimeout(err: unknown): boolean {
  return err instanceof Error && (err.name === "TimeoutError" || err.name === "AbortError");
}
