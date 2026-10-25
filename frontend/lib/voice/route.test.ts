// The speech-to-text route, called as Next calls it: only admins may spend the speech credits.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as voiceRoute from "@/app/api/voice/transcribe/route";
import { ADMIN_COOKIE, signAdminToken } from "../admin";

const KEY = "test-admin-key-0123456789abcdef-0123456789";
const BASE = "http://app.test";

function post(opts: { admin?: boolean; audio?: boolean } = {}): Request {
  const form = new FormData();
  if (opts.audio !== false) form.set("audio", new Blob([new Uint8Array(4000)], { type: "audio/wav" }), "speech.wav");
  const headers: Record<string, string> = {};
  if (opts.admin) headers.cookie = `${ADMIN_COOKIE}=${signAdminToken(KEY)}`;
  return new Request(`${BASE}/api/voice/transcribe`, { method: "POST", headers, body: form });
}

let upstream: ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.stubEnv("ADMIN_KEY", KEY);
  vi.stubEnv("ELEVENLABS_API_KEY", "xi-test");
  vi.stubEnv("ELEVENLABS_API_BASE", "http://speech.test");
  upstream = vi.fn(async () => Response.json({ language_code: "spa", language_probability: 0.97, text: "Cambia la cuenta bancaria" }));
  vi.stubGlobal("fetch", upstream);
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("POST /api/voice/transcribe", () => {
  it("refuses a viewer with 403 {error: viewer} and never contacts the speech service", async () => {
    const res = await voiceRoute.POST(post());
    expect(res.status).toBe(403);
    expect(await res.json()).toEqual({ error: "viewer" });
    expect(upstream).not.toHaveBeenCalled();
  });

  it("refuses everyone in production when no admin key is set (nobody is admin)", async () => {
    vi.stubEnv("ADMIN_KEY", "");
    vi.stubEnv("NODE_ENV", "production");
    const res = await voiceRoute.POST(post({ admin: true }));
    expect(res.status).toBe(403);
    expect(upstream).not.toHaveBeenCalled();
  });

  it("transcribes for an admin, with the key sent to the speech service and never back to the browser", async () => {
    const res = await voiceRoute.POST(post({ admin: true }));
    expect(res.status).toBe(200);
    const body = (await res.json()) as Record<string, unknown>;
    expect(body).toEqual({ text: "Cambia la cuenta bancaria", language: "spa", probability: 0.97 });
    expect(JSON.stringify(body)).not.toContain("xi-test");
    expect(upstream).toHaveBeenCalledTimes(1);
    const [url, init] = upstream.mock.calls[0]! as unknown as [string, RequestInit];
    expect(String(url)).toBe("http://speech.test/v1/speech-to-text");
    expect((init.headers as Record<string, string>)["xi-api-key"]).toBe("xi-test");
  });

  it("says voice is not set up when there is no key, even for an admin", async () => {
    vi.stubEnv("ELEVENLABS_API_KEY", "");
    const res = await voiceRoute.POST(post({ admin: true }));
    expect(res.status).toBe(503);
    expect(((await res.json()) as { error: string }).error).toBe("voice_not_configured");
    expect(upstream).not.toHaveBeenCalled();
  });

  it("asks for audio when none is sent", async () => {
    const res = await voiceRoute.POST(post({ admin: true, audio: false }));
    expect(res.status).toBe(400);
    expect(upstream).not.toHaveBeenCalled();
  });
});

describe("GET /api/voice/transcribe", () => {
  it("only says whether voice is set up (a boolean, nothing else), to anyone", async () => {
    const res = await voiceRoute.GET();
    expect(await res.json()).toEqual({ configured: true });
    vi.stubEnv("ELEVENLABS_API_KEY", "");
    expect(await (await voiceRoute.GET()).json()).toEqual({ configured: false });
  });
});
