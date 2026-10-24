// POST /api/sync        publish what a visitor did (the arena) or announce a laptop (hello); GET /api/sync?after=<seq> read it back.
// The relay between the four laptops: see lib/sync/hub.ts. Owner: Dev R.
import { isCrossSiteMutation } from "@/lib/proxy";
import { hub } from "@/lib/sync/hub";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const noStore = { "cache-control": "no-store" };

export async function POST(req: Request): Promise<Response> {
  if (isCrossSiteMutation("POST", req.headers)) return Response.json({ error: "cross-site request refused" }, { status: 403, headers: noStore });
  const text = await req.text();
  if (text.length > 4000) return Response.json({ error: "too large" }, { status: 413, headers: noStore });
  let body: unknown;
  try { body = JSON.parse(text); } catch { return Response.json({ error: "bad json" }, { status: 400, headers: noStore }); }
  const m = hub().publish(body);
  return m ? Response.json({ ok: true, seq: m.seq }, { status: 202, headers: noStore }) : Response.json({ error: "rejected" }, { status: 422, headers: noStore });
}

export async function GET(req: Request): Promise<Response> {
  const after = Number(new URL(req.url).searchParams.get("after") ?? 0);
  return Response.json(hub().snapshot(Number.isFinite(after) ? after : 0), { headers: noStore });
}
