// POST /api/admin/login {key} → sets the admin cookie when `key` equals ADMIN_KEY (constant-time). Owner: Dev R. See lib/admin.ts.
// 200 {role:"admin"} | 401 {error:"bad key"} | 503 {error:"admin disabled"} (ADMIN_KEY unset or < 32 chars in production)
// | 429 (too many tries from this address, or too many failures from all addresses this minute).
// No key configured outside production (dev, mock): everyone is admin already, so this answers 200 without a cookie.
import { adminCookie, adminSettings, clientIp, keyMatches, signAdminToken } from "@/lib/admin";
import { isCrossSiteMutation } from "@/lib/proxy";
import { limiter, loginFailures, tooMany } from "@/lib/ratelimit";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const noStore = { "cache-control": "no-store" };

export async function POST(req: Request): Promise<Response> {
  if (isCrossSiteMutation("POST", req.headers)) return Response.json({ error: "cross-site request refused" }, { status: 403, headers: noStore });
  const s = adminSettings();
  if (s.mode === "open") return Response.json({ role: "admin" }, { headers: noStore });
  if (s.mode === "closed") return Response.json({ error: "admin disabled" }, { status: 503, headers: noStore });

  // too many failures from everywhere this minute: refuse every login until the window ends (rotating addresses can't help)
  const failures = loginFailures();
  if (failures.blocked()) return tooMany(failures.retryAfterSec());
  const rl = limiter("login").take(clientIp(req.headers));
  if (!rl.ok) return tooMany(rl.retryAfterSec);

  const text = await req.text();
  if (text.length > 2048) return Response.json({ error: "too large" }, { status: 413, headers: noStore });
  let key: unknown;
  try { key = (JSON.parse(text) as { key?: unknown } | null)?.key; } catch { return Response.json({ error: "bad json" }, { status: 400, headers: noStore }); }
  if (!keyMatches(key, s.key)) {
    failures.record();
    return Response.json({ error: "bad key" }, { status: 401, headers: noStore });
  }

  return Response.json({ role: "admin" }, { headers: { ...noStore, "set-cookie": adminCookie(signAdminToken(s.key)) } });
}
