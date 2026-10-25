// POST /api/voice/transcribe   multipart `audio` (a WAV from the browser) → { text, language, probability }; admins only (403 {error: viewer})
// GET  /api/voice/transcribe   → { configured } so the UI can say "type it" instead of letting someone record into nothing
//
// "Speak a fraud scheme" (the attack console's microphone): the speech-to-text key lives here, server-side, and nowhere else.
// See lib/voice/transcribe.ts. Owner: Dev R.
import { requestRole } from "@/lib/admin";
import { isCrossSiteMutation } from "@/lib/proxy";
import { MAX_AUDIO_BYTES, transcribeAudio, VOICE_MESSAGES, voiceConfig, type VoiceErrorCode } from "@/lib/voice/transcribe";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const noStore = { "cache-control": "no-store" };

/** every request spends the owner's speech credits: a modest ceiling per minute, per server process */
const WINDOW_MS = 60_000;
const MAX_PER_WINDOW = 20;
const recent: number[] = [];
function overLimit(now = Date.now()): boolean {
  while (recent.length && now - recent[0] > WINDOW_MS) recent.shift();
  if (recent.length >= MAX_PER_WINDOW) return true;
  recent.push(now);
  return false;
}

const err = (status: number, error: VoiceErrorCode) => Response.json({ error, message: VOICE_MESSAGES[error] }, { status, headers: noStore });

export async function GET(): Promise<Response> {
  return Response.json({ configured: voiceConfig() !== null }, { headers: noStore });
}

export async function POST(req: Request): Promise<Response> {
  if (isCrossSiteMutation("POST", req.headers)) return Response.json({ error: "cross-site request refused" }, { status: 403, headers: noStore });
  // the site is public (lib/admin.ts) and this call spends the owner's speech credits: only the admin laptops may make it
  if (requestRole(req.headers) !== "admin") return Response.json({ error: "viewer" }, { status: 403, headers: noStore });
  const cfg = voiceConfig();
  if (!cfg) return err(503, "voice_not_configured");
  const declared = Number(req.headers.get("content-length") ?? 0);
  if (declared > MAX_AUDIO_BYTES + 4096) return err(413, "audio_too_large");
  if (overLimit()) return err(429, "rate_limited");

  let form: FormData;
  try { form = await req.formData(); } catch { return err(400, "audio_missing"); }
  const audio = form.get("audio");
  if (!(audio instanceof Blob)) return err(400, "audio_missing");
  const language = form.get("language");

  const r = await transcribeAudio(audio, cfg, { language: typeof language === "string" ? language : undefined });
  if (!r.ok) return err(r.status, r.error);
  return Response.json({ text: r.text, language: r.language, probability: r.probability }, { headers: noStore });
}
