import { describe, expect, it } from "vitest";
import { errorForStatus, MAX_AUDIO_BYTES, MIN_AUDIO_BYTES, transcribeAudio, voiceConfig } from "./transcribe";

const cfg = { apiKey: "k_test_123", base: "https://stt.example", model: "scribe_v2" };
const wav = (n = 40_000) => new Blob([new Uint8Array(n)], { type: "audio/wav" });
const stub = (status: number, body: unknown, seen?: { url?: string; init?: RequestInit }) =>
  (async (url: string, init: RequestInit) => { if (seen) { seen.url = url; seen.init = init; } return new Response(typeof body === "string" ? body : JSON.stringify(body), { status }); }) as unknown as typeof fetch;

describe("voice config", () => {
  it("is off without a key, and defaults the rest", () => {
    expect(voiceConfig({})).toBeNull();
    expect(voiceConfig({ ELEVENLABS_API_KEY: "  " })).toBeNull();
    expect(voiceConfig({ ELEVENLABS_API_KEY: "k" })).toEqual({ apiKey: "k", base: "https://api.elevenlabs.io", model: "scribe_v2" });
    expect(voiceConfig({ ELEVENLABS_API_KEY: "k", ELEVENLABS_API_BASE: "http://127.0.0.1:9/", ELEVENLABS_STT_MODEL: "scribe_v1" })).toEqual({ apiKey: "k", base: "http://127.0.0.1:9", model: "scribe_v1" });
  });
});

describe("transcribe", () => {
  it("sends the audio with the key in the header, model and no language, and returns what was heard", async () => {
    const seen: { url?: string; init?: RequestInit } = {};
    const r = await transcribeAudio(wav(), cfg, { fetchImpl: stub(200, { text: "  Cambia la cuenta bancaria del proveedor.  ", language_code: "spa", language_probability: 0.98 }, seen) });
    expect(r).toEqual({ ok: true, text: "Cambia la cuenta bancaria del proveedor.", language: "spa", probability: 0.98 });
    expect(seen.url).toBe("https://stt.example/v1/speech-to-text");
    expect((seen.init!.headers as Record<string, string>)["xi-api-key"]).toBe("k_test_123");
    const form = seen.init!.body as FormData;
    expect(form.get("model_id")).toBe("scribe_v2");
    expect(form.get("language_code")).toBeNull();
    expect((form.get("file") as File).name).toBe("speech.wav");
  });

  it("passes a language hint only when it looks like a language code", async () => {
    const seen: { url?: string; init?: RequestInit } = {};
    await transcribeAudio(wav(), cfg, { language: "FR", fetchImpl: stub(200, { text: "x" }, seen) });
    expect((seen.init!.body as FormData).get("language_code")).toBe("fr");
    await transcribeAudio(wav(), cfg, { language: "not a language", fetchImpl: stub(200, { text: "x" }, seen) });
    expect((seen.init!.body as FormData).get("language_code")).toBeNull();
  });

  it("refuses audio that is too short or too long without calling the service", async () => {
    let called = 0;
    const f = (async () => { called++; return new Response("{}"); }) as unknown as typeof fetch;
    expect(await transcribeAudio(wav(MIN_AUDIO_BYTES - 1), cfg, { fetchImpl: f })).toEqual({ ok: false, status: 422, error: "audio_too_small" });
    expect(await transcribeAudio(wav(MAX_AUDIO_BYTES + 1), cfg, { fetchImpl: f })).toEqual({ ok: false, status: 413, error: "audio_too_large" });
    expect(called).toBe(0);
  });

  it("says no_speech when nothing was heard", async () => {
    expect(await transcribeAudio(wav(), cfg, { fetchImpl: stub(200, { text: "   " }) })).toEqual({ ok: false, status: 422, error: "no_speech" });
  });

  it("turns the service's failures into codes, and never reports its refusal of our key as the visitor's", async () => {
    const code = async (status: number) => (await transcribeAudio(wav(), cfg, { fetchImpl: stub(status, { detail: "secret detail" }) }));
    expect(await code(401)).toEqual({ ok: false, status: 502, error: "key_rejected" });
    expect(await code(402)).toEqual({ ok: false, status: 502, error: "out_of_credits" });
    expect(await code(429)).toEqual({ ok: false, status: 429, error: "rate_limited" });
    expect(await code(422)).toEqual({ ok: false, status: 422, error: "audio_rejected" });
    expect(await code(500)).toEqual({ ok: false, status: 502, error: "upstream_error" });
    expect(errorForStatus(403)).toBe("key_rejected");
  });

  it("survives a network failure, a timeout and a body that is not JSON", async () => {
    const boom = (async () => { throw new TypeError("fetch failed"); }) as unknown as typeof fetch;
    expect(await transcribeAudio(wav(), cfg, { fetchImpl: boom })).toEqual({ ok: false, status: 502, error: "upstream_unreachable" });
    const slow = (async () => { const e = new Error("aborted"); e.name = "TimeoutError"; throw e; }) as unknown as typeof fetch;
    expect(await transcribeAudio(wav(), cfg, { fetchImpl: slow })).toEqual({ ok: false, status: 504, error: "upstream_timeout" });
    expect(await transcribeAudio(wav(), cfg, { fetchImpl: stub(200, "<html>") })).toEqual({ ok: false, status: 502, error: "upstream_error" });
  });
});
