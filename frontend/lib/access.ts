// Cloudflare Access JWT verification at the origin. Owner: Dev R. Used by `middleware.ts`.
//
// Why: Caddy only serves Cloudflare's edge IPs, but anyone who knows the origin IP can front it
// with their OWN Cloudflare zone/Worker. Those requests come from Cloudflare IPs yet never pass our
// Access application, so the only proof a request went through *our* Access app is the RS256 JWT
// Access signs and attaches (`Cf-Access-Jwt-Assertion` header, `CF_Authorization` cookie).
//
// Config (server env, read per request, never NEXT_PUBLIC_):
//   CF_ACCESS_TEAM_DOMAIN  e.g. mdracc.cloudflareaccess.com (issuer + JWKS host)
//   CF_ACCESS_AUD          the Access application's AUD tag
// Both set → every request needs a valid token. Either unset → check disabled (local dev,
// NEXT_PUBLIC_MOCK=true, CI). Never log tokens or claims.
// Subpath imports keep jose's JWE code (CompressionStream, unsupported on the edge) out of the bundle.
import { createRemoteJWKSet, customFetch } from "jose/jwks/remote";
import { jwtVerify, type JWTVerifyGetKey } from "jose/jwt/verify";
import { runtimeEnv, type Env } from "./proxy";

export const ACCESS_HEADER = "cf-access-jwt-assertion";
export const ACCESS_COOKIE = "CF_Authorization";
/** Seconds of exp/nbf/iat leeway for clock skew between Cloudflare and the VM. */
export const CLOCK_TOLERANCE_SEC = 60;
/** Real Access JWTs are ~1 KB; refuse to parse anything absurd. */
const MAX_TOKEN_LENGTH = 8192;

export interface AccessConfig {
  teamDomain: string;
  audience: string;
  issuer: string;
  certsUrl: string;
}

export type AccessSettings =
  | { mode: "off"; partial: boolean } // partial = exactly one of the two vars is set
  | { mode: "on"; config: AccessConfig }
  | { mode: "invalid" }; // vars set but the team domain is not a hostname: fail closed

/** Read the two vars. Tolerates a pasted `https://` prefix or trailing slash on the domain. */
export function accessSettings(env: Env = process.env): AccessSettings {
  const rawDomain = runtimeEnv("CF_ACCESS_TEAM_DOMAIN", env);
  const audience = runtimeEnv("CF_ACCESS_AUD", env);
  if (!rawDomain || !audience) return { mode: "off", partial: Boolean(rawDomain) !== Boolean(audience) };
  const teamDomain = rawDomain.replace(/^https:\/\//i, "").replace(/\/+$/, "").toLowerCase();
  if (!/^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$/.test(teamDomain)) {
    return { mode: "invalid" };
  }
  const issuer = `https://${teamDomain}`;
  return { mode: "on", config: { teamDomain, audience, issuer, certsUrl: `${issuer}/cdn-cgi/access/certs` } };
}

/** The Access token: the header Access adds to proxied requests, else the `CF_Authorization` cookie. */
export function accessToken(headers: Headers): string | null {
  const header = headers.get(ACCESS_HEADER)?.trim();
  if (header) return header;
  const cookie = headers.get("cookie");
  if (!cookie) return null;
  for (const part of cookie.split(";")) {
    const eq = part.indexOf("=");
    if (eq === -1) continue;
    if (part.slice(0, eq).trim() === ACCESS_COOKIE) {
      const value = part.slice(eq + 1).trim();
      return value || null;
    }
  }
  return null;
}

export type FetchLike = (input: string | URL | Request, init?: RequestInit) => Promise<Response>;

// One JWKS per certs URL for the life of the process. jose caches keys (10 min), refetches on an
// unknown `kid` (Access key rotation) with a 30 s cooldown, and times the fetch out at 5 s.
const jwksCache = new Map<string, JWTVerifyGetKey>();

export function remoteJwks(certsUrl: string, fetchImpl?: FetchLike): JWTVerifyGetKey {
  if (fetchImpl) return createRemoteJWKSet(new URL(certsUrl), { [customFetch]: fetchImpl });
  let jwks = jwksCache.get(certsUrl);
  if (!jwks) {
    jwks = createRemoteJWKSet(new URL(certsUrl));
    jwksCache.set(certsUrl, jwks);
  }
  return jwks;
}

export type AccessResult = { ok: true } | { ok: false; reason: string };

/**
 * Verify an Access JWT: RS256 signature against the team JWKS, `iss` == team URL, `aud` contains
 * the app AUD, `exp` present and not past, `nbf` not in the future (with clock tolerance).
 * `reason` is a jose error code or a fixed string; it never contains token material.
 */
export async function verifyAccessToken(
  token: string | null,
  config: AccessConfig,
  jwks: JWTVerifyGetKey = remoteJwks(config.certsUrl),
): Promise<AccessResult> {
  if (!token) return { ok: false, reason: "missing" };
  if (token.length > MAX_TOKEN_LENGTH) return { ok: false, reason: "oversized" };
  try {
    await jwtVerify(token, jwks, {
      algorithms: ["RS256"],
      issuer: config.issuer,
      audience: config.audience,
      requiredClaims: ["exp"],
      clockTolerance: CLOCK_TOLERANCE_SEC,
    });
    return { ok: true };
  } catch (err) {
    // jose errors carry a code; anything else came from fetching the JWKS (DNS, TLS, reset).
    const code = (err as { code?: unknown } | null)?.code;
    return { ok: false, reason: typeof code === "string" ? code : "jwks_unavailable" };
  }
}

/** Decide one request. `bypass` = check disabled by config; callers let it through. */
export async function checkAccess(
  headers: Headers,
  env: Env = process.env,
  jwks?: JWTVerifyGetKey,
): Promise<AccessResult | { ok: true; bypass: true; partial: boolean }> {
  const settings = accessSettings(env);
  if (settings.mode === "off") return { ok: true, bypass: true, partial: settings.partial };
  if (settings.mode === "invalid") return { ok: false, reason: "misconfigured" };
  return verifyAccessToken(accessToken(headers), settings.config, jwks ?? remoteJwks(settings.config.certsUrl));
}

/**
 * Reasons that mean the JWKS could not be loaded, i.e. every user is locked out: worth an
 * operator-visible log line. Bad/forged tokens (incl. an unknown `kid`) are not logged.
 */
export function isJwksFailure(reason: string): boolean {
  return ["jwks_unavailable", "ERR_JWKS_TIMEOUT", "ERR_JWKS_INVALID", "ERR_JOSE_GENERIC"].includes(reason);
}
