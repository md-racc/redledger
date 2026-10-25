"use client";
// "Speak a scheme": the state of the microphone button in the attack console. Owner: Dev R.
//
//   idle → listening (click again, or 45 s) → transcribing → ready (the words, editable)
//
// The audio goes to POST /api/voice/transcribe (the server holds the speech-to-text key); what comes back is the text and the
// language it was spoken in. Typing in the same box works too, which is also what happens when voice is not set up.
import { useCallback, useEffect, useRef, useState } from "react";
import { MicError, startRecording, type Recording } from "@/lib/voice/recorder";

export type VoicePhase = "idle" | "listening" | "transcribing" | "ready" | "error";

export const MAX_LISTEN_SECONDS = 45;

/** "spa" or "es" → "Spanish" (falls back to the code) */
export function languageName(code: string | null): string {
  if (!code) return "";
  try { return new Intl.DisplayNames(["en"], { type: "language" }).of(code) ?? code; } catch { return code; }
}

export function useVoice() {
  const [phase, setPhase] = useState<VoicePhase>("idle");
  const [text, setText] = useState("");
  const [language, setLanguage] = useState<string | null>(null);
  const [probability, setProbability] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [seconds, setSeconds] = useState(0);
  const [level, setLevel] = useState(0);
  /** null until the server has said whether it has a speech-to-text key */
  const [configured, setConfigured] = useState<boolean | null>(null);
  const rec = useRef<Recording | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const started = useRef(0);

  useEffect(() => {
    let live = true;
    fetch("/api/voice/transcribe", { cache: "no-store" })
      .then((r) => r.json())
      .then((j: { configured?: boolean }) => { if (live) setConfigured(!!j.configured); })
      .catch(() => { if (live) setConfigured(false); });
    return () => { live = false; };
  }, []);

  const clearTimer = () => { if (timer.current) { clearInterval(timer.current); timer.current = null; } };

  const stop = useCallback(async () => {
    const r = rec.current;
    if (!r) return;
    rec.current = null;
    clearTimer();
    setLevel(0);
    setPhase("transcribing");
    try {
      const { wav } = await r.stop();
      const form = new FormData();
      form.set("audio", wav, "speech.wav");
      const res = await fetch("/api/voice/transcribe", { method: "POST", body: form });
      const j = (await res.json().catch(() => ({}))) as { text?: string; language?: string | null; probability?: number | null; message?: string };
      if (!res.ok || !j.text) throw new Error(j.message ?? "The speech service did not answer. Type the scheme instead.");
      setText(j.text);
      setLanguage(j.language ?? null);
      setProbability(j.probability ?? null);
      setPhase("ready");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong with the recording.");
      setPhase("error");
    }
  }, []);

  const start = useCallback(async () => {
    setError(null);
    try {
      rec.current = await startRecording((v) => setLevel(v));
    } catch (e) {
      setError(e instanceof MicError ? e.message : "Could not start the microphone.");
      setPhase("error");
      return;
    }
    started.current = Date.now();
    setSeconds(0);
    setPhase("listening");
    timer.current = setInterval(() => {
      const s = Math.floor((Date.now() - started.current) / 1000);
      setSeconds(s);
      if (s >= MAX_LISTEN_SECONDS) void stop();
    }, 250);
  }, [stop]);

  /** typing counts: the words are the words, wherever they came from */
  const type = useCallback((value: string) => {
    setText(value);
    setPhase(value.trim() ? "ready" : "idle");
    setLanguage(null);
    setProbability(null);
    setError(null);
  }, []);

  const reset = useCallback(() => {
    rec.current?.cancel();
    rec.current = null;
    clearTimer();
    setPhase("idle");
    setText("");
    setLanguage(null);
    setProbability(null);
    setError(null);
    setLevel(0);
  }, []);

  useEffect(() => () => { rec.current?.cancel(); clearTimer(); }, []);

  return { phase, text, language, probability, error, seconds, level, configured, start, stop, type, reset };
}
