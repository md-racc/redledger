// Who may change the sim: admins (our four laptops) vs everyone else (viewers). Server-only. Owner: Dev R.
//
// The site is public: anyone with the URL can watch. Only a browser holding the admin cookie may make the /api/bf proxy (which
// attaches OPERATOR_TOKEN) do anything but read, or publish to the laptop relay (/api/sync). The cookie is minted by
// POST /api/admin/login after a constant-time compare against the server env ADMIN_KEY (never NEXT_PUBLIC_):
//
//   rl_admin=v1.<issued-at s>.<expires-at s>.<base64url HMAC-SHA256(ADMIN_KEY, "v1.<iat>.<exp>")>
//
// HttpOnly, SameSite=Strict, Secure in production, 7 days. Rotating ADMIN_KEY invalidates every cookie (the HMAC no longer
// verifies). ADMIN_KEY unset: in production nobody is admin (fail closed, one warning); outside production (`next dev`, tests)
// everyone is, so local dev and `NEXT_PUBLIC_MOCK=true npm run dev` stay as they were. NODE_ENV=production is never
// everyone-admin, whatever else is set: in particular a runtime NEXT_PUBLIC_MOCK is never trusted here (compose passes it into the
// prod container). In production an ADMIN_KEY shorter than 32 characters counts as unset. Never log the key or the cookie.
import { createHash, createHmac, timingSafeEqual } from "node:crypto";
import { runtimeEnv, type Env } from "./proxy";

export type Role = "admin" | "viewer";

export const ADMIN_COOKIE = "rl_admin";
export const ADMIN_TTL_SEC = 7 * 24 * 3600;
/** Seconds of leeway for an issued-at slightly in the future (clock steps on the VM). */
const IAT_SKEW_SEC = 60;
const TOKEN_VERSION = "v1";
/** Real tokens are ~70 chars; refuse to parse anything absurd. */
const MAX_TOKEN_LENGTH = 256;

/** Production refuses a shorter ADMIN_KEY (deploy's render-env enforces the same floor). */
export const MIN_ADMIN_KEY_LENGTH = 32;

export type AdminSettings =
  | { mode: "key"; key: string } // ADMIN_KEY set: admin = valid cookie
  | { mode: "open" } // outside production without a key: everyone is admin
  | { mode: "closed"; reason: "unset" | "short" }; // production without a usable key: nobody is admin

export function adminSettings(env: Env = process.env): AdminSettings {
  const production = env["NODE_ENV"] === "production";
  const key = runtimeEnv("ADMIN_KEY", env);
  if (key && (!production || key.length >= MIN_ADMIN_KEY_LENGTH)) return { mode: "key", key };
  if (production) return { mode: "closed", reason: key ? "short" : "unset" };
  return { mode: "open" };
}

const warned = { unset: false, short: false };
function warnIfClosed(s: AdminSettings): void {
  if (s.mode !== "closed" || warned[s.reason]) return;
  warned[s.reason] = true;
  console.warn(
    s.reason === "short"
      ? `admin: ADMIN_KEY is shorter than ${MIN_ADMIN_KEY_LENGTH} characters; ignored in production, nobody is admin, the site is read-only`
      : "admin: ADMIN_KEY is unset in production; nobody is admin, the site is read-only",
  );
}

const b64url = (buf: Buffer): string => buf.toString("base64url");
const sign = (key: string, payload: string): string => b64url(createHmac("sha256", key).update(payload).digest());

/** A fresh admin token, issued now (seconds since the epoch). */
export function signAdminToken(key: string, nowSec = Math.floor(Date.now() / 1000), ttlSec = ADMIN_TTL_SEC): string {
  const payload = `${TOKEN_VERSION}.${nowSec}.${nowSec + ttlSec}`;
  return `${payload}.${sign(key, payload)}`;
}

/** Valid = our version, a well-formed issued-at/expiry, not expired, not issued in the future, and the HMAC matches this key. */
export function verifyAdminToken(token: string | null | undefined, key: string, nowSec = Math.floor(Date.now() / 1000)): boolean {
  if (!token || token.length > MAX_TOKEN_LENGTH) return false;
  const parts = token.split(".");
  if (parts.length !== 4 || parts[0] !== TOKEN_VERSION) return false;
  const [, iatS, expS, sig] = parts as [string, string, string, string];
  if (!/^\d{1,12}$/.test(iatS) || !/^\d{1,12}$/.test(expS)) return false;
  const iat = Number(iatS);
  const exp = Number(expS);
  if (exp <= iat || exp - iat > ADMIN_TTL_SEC || nowSec >= exp || iat > nowSec + IAT_SKEW_SEC) return false;
  const want = Buffer.from(sign(key, `${TOKEN_VERSION}.${iatS}.${expS}`));
  const got = Buffer.from(sig);
  return got.length === want.length && timingSafeEqual(got, want);
}

/** Constant-time compare of a submitted key against ADMIN_KEY (hashing first makes the lengths equal). */
export function keyMatches(submitted: unknown, key: string): boolean {
  if (typeof submitted !== "string" || submitted.length === 0 || submitted.length > 1024) return false;
  const a = createHash("sha256").update(submitted).digest();
  const b = createHash("sha256").update(key).digest();
  return timingSafeEqual(a, b);
}

export function readCookie(headers: Headers, name: string): string | null {
  const cookie = headers.get("cookie");
  if (!cookie) return null;
  for (const part of cookie.split(";")) {
    const eq = part.indexOf("=");
    if (eq === -1) continue;
    if (part.slice(0, eq).trim() === name) return part.slice(eq + 1).trim() || null;
  }
  return null;
}

/** The caller's role, decided from the cookie and the server env only. */
export function requestRole(headers: Headers, env: Env = process.env, nowSec?: number): Role {
  const s = adminSettings(env);
  warnIfClosed(s);
  if (s.mode === "open") return "admin";
  if (s.mode === "closed") return "viewer";
  return verifyAdminToken(readCookie(headers, ADMIN_COOKIE), s.key, nowSec) ? "admin" : "viewer";
}

const secure = (env: Env): string => (env["NODE_ENV"] === "production" ? "; Secure" : "");

export function adminCookie(token: string, env: Env = process.env): string {
  return `${ADMIN_COOKIE}=${token}; Path=/; Max-Age=${ADMIN_TTL_SEC}; HttpOnly; SameSite=Strict${secure(env)}`;
}

export function clearedAdminCookie(env: Env = process.env): string {
  return `${ADMIN_COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict${secure(env)}`;
}

/** The client address for rate limiting: Cloudflare's header, then the proxy's, then the first X-Forwarded-For hop. */
export function clientIp(headers: Headers): string {
  const cf = headers.get("cf-connecting-ip")?.trim();
  if (cf) return cf;
  const real = headers.get("x-real-ip")?.trim();
  if (real) return real;
  const xff = headers.get("x-forwarded-for")?.split(",")[0]?.trim();
  return xff || "unknown";
}
