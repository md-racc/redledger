// GET /api/whoami → {role: "admin" | "viewer"}. The UI hides what a viewer can't do; the proxy enforces it. Owner: Dev R.
import { requestRole } from "@/lib/admin";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(req: Request): Promise<Response> {
  return Response.json({ role: requestRole(req.headers) }, { headers: { "cache-control": "no-store" } });
}
