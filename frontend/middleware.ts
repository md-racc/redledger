// Origin-side Cloudflare Access check for every page and every /api/bf/* call. Owner: Dev R.
// See lib/access.ts for why (a foreign Cloudflare zone pointed at our origin IP skips Access).
// CF_ACCESS_TEAM_DOMAIN + CF_ACCESS_AUD set → a valid Access JWT is required; unset → bypass.
// Then, for requests that pass: `/` on a red.* / blue.* host is rewritten to that team's dashboard (components/backstage/host.ts).
import { NextResponse, type NextRequest } from "next/server";
import { checkAccess, isJwksFailure } from "@/lib/access";
import { dashboardFor } from "@/components/backstage/host";

let warnedDisabled = false;
let lastJwksWarn = 0;

function forbidden(req: NextRequest): Response {
  const headers = { "cache-control": "no-store" };
  if (req.nextUrl.pathname.startsWith("/api/")) {
    return Response.json({ error: "forbidden" }, { status: 403, headers });
  }
  return new Response("forbidden", { status: 403, headers: { ...headers, "content-type": "text/plain" } });
}

export async function middleware(req: NextRequest): Promise<Response> {
  const result = await checkAccess(req.headers);
  if (result.ok) {
    if ("bypass" in result && !warnedDisabled && process.env["NODE_ENV"] === "production") {
      warnedDisabled = true;
      console.warn(
        result.partial
          ? "access: only one of CF_ACCESS_TEAM_DOMAIN / CF_ACCESS_AUD is set; Cloudflare Access JWT check is DISABLED"
          : "access: CF_ACCESS_TEAM_DOMAIN / CF_ACCESS_AUD unset; Cloudflare Access JWT check is DISABLED",
      );
    }
    // red.<domain> / blue.<domain> at `/` → that team's dashboard (the side laptops on stage); every other path is untouched.
    // Only after the Access check above: the rewrite never skips it.
    const target = dashboardFor(req.headers.get("host"), req.nextUrl.pathname) ?? dashboardFor(req.headers.get("x-forwarded-host"), req.nextUrl.pathname);
    if (target) {
      const url = req.nextUrl.clone();
      url.pathname = target;
      return NextResponse.rewrite(url);
    }
    return NextResponse.next();
  }
  // Never log the token or its claims; the reason is a fixed code.
  if (result.reason === "misconfigured" || isJwksFailure(result.reason)) {
    const now = Date.now();
    if (now - lastJwksWarn > 60_000) {
      lastJwksWarn = now;
      console.error(`access: rejecting requests, cannot verify Access JWTs (${result.reason})`);
    }
  }
  return forbidden(req);
}

export const config = {
  // Everything except Next's build assets and the favicon. /mocks/* is protected too.
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
