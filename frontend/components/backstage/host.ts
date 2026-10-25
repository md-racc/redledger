// Which dashboard a host name serves at `/`. Owner: Dev R.
//
// The two side laptops on stage open `red.redledger.us` and `blue.redledger.us`. middleware.ts rewrites `/` on those hosts to the
// team's dashboard; every other path (/_next/*, /api/*, /admin, /report/*, /backstage/*) passes through untouched, so the page, its
// assets, the proxy and the socket all work the same on any of the site's host names. Pure, tested.

export type DashboardPath = "/backstage/red" | "/backstage/blue";

const BY_LABEL: Record<string, DashboardPath> = { red: "/backstage/red", blue: "/backstage/blue" };

/** The host's name, lower case, without a port: `Red.Localhost:3110` → `red.localhost`. A forwarded list keeps its first entry. */
export function hostName(host: string | null | undefined): string {
  const first = (host ?? "").split(",")[0]!.trim().toLowerCase();
  if (first.startsWith("[")) return first.replace(/\]:\d+$/, "]"); // an IPv6 literal never names a team
  return first.replace(/:\d+$/, "").replace(/\.$/, "");
}

/**
 * `red.<anything>` or `blue.<anything>` at exactly `/` → that team's dashboard path; anything else → null (no rewrite).
 * `red.localhost:3110` counts, so the mapping can be tried locally; a bare `red` or `red.` does not.
 */
export function dashboardFor(host: string | null | undefined, pathname: string): DashboardPath | null {
  if (pathname !== "/") return null;
  const name = hostName(host);
  const dot = name.indexOf(".");
  if (dot <= 0 || dot === name.length - 1) return null;
  return BY_LABEL[name.slice(0, dot)] ?? null;
}
