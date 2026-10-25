// Server side of "speak a fraud scheme": audio in, text and the language it was spoken in out, by ElevenLabs speech-to-text. Owner: Dev R.
//
// Runs only in the Next route handler (app/api/voice/transcribe/route.ts). The key is a server-only env var, never NEXT_PUBLIC_*,
// never sent to the browser, never logged. Everything that can go wrong is turned into a short code the UI can say in words.
//
//   ELEVENLABS_API_KEY      the key. Unset: the route answers 503 voice_not_configured and the UI offers typing instead
//   ELEVENLABS_STT_MODEL    optional, default "scribe_v2" (the model id in ElevenLabs' current docs)
//   ELEVENLABS_API_BASE     optional, default https://api.elevenlabs.io (regional endpoints; also lets a test point at a stub)
import { runtimeEnv, type Env } from "../proxy";

/** about 90 s of 16 kHz mono 16-bit audio: far more than anyone says in one go, and a ceiling on what one request can cost */
export const MAX_AUDIO_BYTES = 3_000_000;
/** about 100 ms: ElevenLabs refuses anything shorter */
export const MIN_AUDIO_BYTES = 3_200;
export const TRANSCRIBE_TIMEOUT_MS = 25_000;

export interface VoiceConfig { apiKey: string; base: string; model: string }

export function voiceConfig(env: Env = process.env): VoiceConfig | null {
  const apiKey = runtimeEnv("ELEVENLABS_API_KEY", env);
  if (!apiKey) return null;
  const base = (runtimeEnv("ELEVENLABS_API_BASE", env) ?? "https://api.elevenlabs.io").replace(/\/+$/, "");
  return { apiKey, base, model: runtimeEnv("ELEVENLABS_STT_MODEL", env) ?? "scribe_v2" };
}

export type VoiceErrorCode =
  | "voice_not_configured"
  | "audio_missing"
  | "audio_too_small"
  | "audio_too_large"
  | "no_speech"
  | "key_rejected"
  | "out_of_credits"
  | "rate_limited"
  | "audio_rejected"
  | "upstream_error"
  | "upstream_unreachable"
  | "upstream_timeout";

export type Transcription =
  | { ok: true; text: string; language: string | null; probability: number | null }
  | { ok: false; status: number; error: VoiceErrorCode };

const fail = (status: number, error: VoiceErrorCode): Transcription => ({ ok: false, status, error });

/** What ElevenLabs's status codes mean for us. */
export function errorForStatus(status: number): VoiceErrorCode {
  if (status === 401 || status === 403) return "key_rejected";
  if (status === 402) return "out_of_credits";
  if (status === 429) return "rate_limited";
  if (status === 400 || status === 413 || status === 415 || status === 422) return "audio_rejected";
  return "upstream_error";
}

export async function transcribeAudio(
  audio: Blob,
  cfg: VoiceConfig,
  opts: { language?: string; fetchImpl?: typeof fetch; timeoutMs?: number } = {},
): Promise<Transcription> {
  if (audio.size < MIN_AUDIO_BYTES) return fail(422, "audio_too_small");
  if (audio.size > MAX_AUDIO_BYTES) return fail(413, "audio_too_large");

  const form = new FormData();
  form.set("model_id", cfg.model);
  form.set("file", audio, "speech.wav");
  form.set("tag_audio_events", "false");
  form.set("diarize", "false");
  // no language_code: the model listens and says which language it heard, so the judge can speak any of them
  if (opts.language && /^[a-z]{2,3}$/i.test(opts.language)) form.set("language_code", opts.language.toLowerCase());

  let res: Response;
  try {
    res = await (opts.fetchImpl ?? fetch)(`${cfg.base}/v1/speech-to-text`, {
      method: "POST",
      headers: { "xi-api-key": cfg.apiKey, Accept: "application/json" },
      body: form,
      signal: AbortSignal.timeout(opts.timeoutMs ?? TRANSCRIBE_TIMEOUT_MS),
      cache: "no-store",
    });
  } catch (e) {
    const timedOut = e instanceof Error && (e.name === "TimeoutError" || e.name === "AbortError");
    return fail(timedOut ? 504 : 502, timedOut ? "upstream_timeout" : "upstream_unreachable");
  }
  if (!res.ok) {
    const code = errorForStatus(res.status);
    // an upstream 401 is the speech service refusing our key, not the visitor being refused: report it as a bad gateway
    return fail(code === "audio_rejected" ? 422 : code === "rate_limited" ? 429 : 502, code);
  }

  let body: { text?: unknown; language_code?: unknown; language_probability?: unknown };
  try { body = await res.json(); } catch { return fail(502, "upstream_error"); }
  const text = typeof body.text === "string" ? body.text.replace(/\s+/g, " ").trim() : "";
  if (!text) return fail(422, "no_speech");
  return {
    ok: true,
    text: text.slice(0, 1000),
    language: typeof body.language_code === "string" ? body.language_code : null,
    probability: typeof body.language_probability === "number" ? body.language_probability : null,
  };
}

/** What the UI says for each code. Short, and what to do about it. */
export const VOICE_MESSAGES: Record<VoiceErrorCode, string> = {
  voice_not_configured: "Voice is not set up on this server (no ELEVENLABS_API_KEY). Type the scheme instead.",
  audio_missing: "No audio arrived. Try again.",
  audio_too_small: "That was too short to hear. Hold on a little longer and say the whole scheme.",
  audio_too_large: "That was too long. Keep it under a minute.",
  no_speech: "I could not hear any words. Check the microphone and try again.",
  key_rejected: "The speech service refused the key. Check ELEVENLABS_API_KEY.",
  out_of_credits: "The speech service is out of credits.",
  rate_limited: "The speech service is busy. Try again in a moment.",
  audio_rejected: "The speech service could not read that recording. Try again.",
  upstream_error: "The speech service had a problem. Try again, or type the scheme.",
  upstream_unreachable: "Could not reach the speech service. Type the scheme instead.",
  upstream_timeout: "The speech service took too long. Try again, or type the scheme.",
};
