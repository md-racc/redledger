// POST /api/admin/logout → clears the admin cookie. Owner: Dev R. See lib/admin.ts.
import { clearedAdminCookie } from "@/lib/admin";
import { isCrossSiteMutation } from "@/lib/proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(req: Request): Promise<Response> {
  const noStore = { "cache-control": "no-store" };
  if (isCrossSiteMutation("POST", req.headers)) return Response.json({ error: "cross-site request refused" }, { status: 403, headers: noStore });
  return Response.json({ ok: true }, { headers: { ...noStore, "set-cookie": clearedAdminCookie() } });
}
