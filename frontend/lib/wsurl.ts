// Where the browser should open its event socket. Owner: Dev R.
//
// The deploy serves the app and the socket on one host (Caddy: /api/ws goes to battlefield, everything else to the frontend), so
// the socket is `wss://<the page's own host>/api/ws`. `NEXT_PUBLIC_WS_URL` still wins when it is set to something real, but the
// compose default (`ws://localhost:8000`) is only right on a developer's own machine: when the page was loaded from any other host,
// that value (or no value) is replaced by the page's own origin, so four laptops on the same domain never try to dial localhost.
export const DEFAULT_WS_URL = "ws://localhost:8000";

const isLocalHost = (host: string) => /^(localhost|127\.0\.0\.1|\[::1\])$/.test(host.split(":")[0]);

export function wsBaseUrl(env: string | undefined, headers: Headers, requestUrl: string): string {
  const configured = (env ?? "").trim().replace(/\/+$/, "");
  const u = new URL(requestUrl);
  const host = headers.get("x-forwarded-host")?.split(",")[0].trim() || headers.get("host") || u.host;
  const pageIsLocal = isLocalHost(host);
  const configuredIsLocal = /^wss?:\/\/(localhost|127\.0\.0\.1|\[::1\])(:|\/|$)/.test(configured);
  if (configured && !(configuredIsLocal && !pageIsLocal)) return configured;
  if (!configured && pageIsLocal) return DEFAULT_WS_URL;
  const proto = (headers.get("x-forwarded-proto")?.split(",")[0].trim() || u.protocol.replace(":", "")) === "https" ? "wss" : "ws";
  return `${proto}://${host}`;
}
