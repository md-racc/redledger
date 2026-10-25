// The two hidden doors: red.<site> and blue.<site>. Owner: Dev R.
//
// Two addresses nobody links to. Opening `red.redledger.us` (or `blue.…`) shows red's (blue's) raw backend console, the same page as
// /backstage/red. next.config.ts rewrites `/` on those hosts; the page itself 404s for anyone who is not an admin, so a stranger who
// guesses the address sees exactly what a mistyped one shows (lib/backstage/gate.ts). The arena shows an admin a faint pair of dots that
// open them (components/arena/overlays/Doors.tsx); nobody else sees anything.
export type DoorTeam = "red" | "blue";

export const DOOR_TEAMS: readonly DoorTeam[] = ["red", "blue"];

/** The hostname without its port, lower case. */
const hostname = (host: string): string => host.trim().toLowerCase().replace(/:\d+$/, "");

/** Which door a host is, if any: `red.anything.tld` and `blue.anything` (two labels at least, so a machine called "red" is not a door). */
export function doorTeam(host: string | null | undefined): DoorTeam | null {
  if (!host) return null;
  const labels = hostname(host).split(".");
  if (labels.length < 2) return null;
  const first = labels[0];
  return first === "red" || first === "blue" ? first : null;
}

/** An IPv4 or IPv6 literal cannot take a subdomain. */
const isIpLiteral = (h: string): boolean => /^\d{1,3}(\.\d{1,3}){3}$/.test(h) || h.includes(":") || h.startsWith("[");

/**
 * Where an admin goes to open a door from the site they are on: `app.redledger.us` → `red.redledger.us`, `localhost:3000` →
 * `red.localhost:3000` (browsers resolve *.localhost). A host that cannot take a subdomain (an address, a one-word name) falls back to the
 * plain path of the same console.
 */
export function doorUrl(where: { protocol: string; host: string }, team: DoorTeam): string {
  const port = /:\d+$/.exec(where.host)?.[0] ?? "";
  const name = hostname(where.host);
  if (isIpLiteral(name)) return `/backstage/${team}`;
  let labels = name.split(".");
  if (doorTeam(name)) labels = labels.slice(1); // already a door: go to the other one
  if (labels.length >= 2 && (labels[0] === "app" || labels[0] === "www")) labels = labels.slice(1);
  if (labels.length < 1 || (labels.length === 1 && labels[0] !== "localhost")) return `/backstage/${team}`;
  return `${where.protocol}//${team}.${labels.join(".")}${port}/`;
}
