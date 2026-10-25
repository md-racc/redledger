// Who may see behind a door. Owner: Dev R.
//
// On red.<site> / blue.<site> only an admin (lib/admin.ts) sees the console; everyone else gets the page a mistyped address gets: a 404, never a
// 403 and never a login prompt, so the door's existence is not confirmed. On the plain /backstage/... paths nothing changes. Server-only.
import { requestRole } from "../admin";
import type { Env } from "../proxy";
import { doorTeam } from "./alias";

export type Gate = "open" | "hidden";

export function backstageGate(headers: Headers, env: Env = process.env): Gate {
  if (!doorTeam(headers.get("host"))) return "open";
  return requestRole(headers, env) === "admin" ? "open" : "hidden";
}
