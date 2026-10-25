"use client";
// The microphone, in the browser: record, then hand back a 16 kHz mono WAV (lib/voice/wav.ts for why). Owner: Dev R.
import { encodeWav, floatToPcm16, mixToMono, peak, WAV_RATE, wavSeconds } from "./wav";

export type MicProblem = "unsupported" | "insecure" | "blocked" | "no_mic" | "decode_failed";

export class MicError extends Error {
  constructor(readonly problem: MicProblem, message: string) { super(message); }
}

export const MIC_MESSAGES: Record<MicProblem, string> = {
  unsupported: "This browser cannot record audio. Type the scheme instead.",
  insecure: "The microphone only works on https (or localhost). Type the scheme instead.",
  blocked: "The microphone is blocked. Allow it for this site in the browser, then try again.",
  no_mic: "No microphone found. Plug one in, or type the scheme instead.",
  decode_failed: "Could not read that recording. Try again.",
};

export interface Recording {
  /** stop listening and return what was said as a WAV */
  stop(): Promise<{ wav: Blob; seconds: number }>;
  /** throw it away */
  cancel(): void;
}

interface AudioWindow { AudioContext?: typeof AudioContext; webkitAudioContext?: typeof AudioContext; OfflineAudioContext?: typeof OfflineAudioContext; webkitOfflineAudioContext?: typeof OfflineAudioContext }

/** Decode whatever the recorder produced and bring it to 16 kHz mono with the browser's own resampler (it filters properly). */
async function toWav(blob: Blob): Promise<{ wav: Blob; seconds: number; level: number }> {
  const w = window as unknown as AudioWindow;
  const Ctx = w.AudioContext ?? w.webkitAudioContext;
  const Offline = w.OfflineAudioContext ?? w.webkitOfflineAudioContext;
  if (!Ctx || !Offline) throw new MicError("unsupported", MIC_MESSAGES.unsupported);
  const ctx = new Ctx();
  try {
    const decoded = await ctx.decodeAudioData(await blob.arrayBuffer());
    const frames = Math.max(1, Math.ceil(decoded.duration * WAV_RATE));
    const off = new Offline(1, frames, WAV_RATE);
    const src = off.createBufferSource();
    src.buffer = decoded;
    src.connect(off.destination);
    src.start();
    const rendered = await off.startRendering();
    const mono = mixToMono(Array.from({ length: rendered.numberOfChannels }, (_, c) => rendered.getChannelData(c)));
    const wav = encodeWav(floatToPcm16(mono), WAV_RATE);
    return { wav: new Blob([wav as BlobPart], { type: "audio/wav" }), seconds: wavSeconds(wav), level: peak(mono) };
  } catch (e) {
    if (e instanceof MicError) throw e;
    throw new MicError("decode_failed", MIC_MESSAGES.decode_failed);
  } finally {
    void ctx.close().catch(() => {});
  }
}

export async function startRecording(onLevel?: (level: number) => void): Promise<Recording> {
  if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
    throw new MicError(window.isSecureContext === false ? "insecure" : "unsupported", MIC_MESSAGES[window.isSecureContext === false ? "insecure" : "unsupported"]);
  }
  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
  } catch (e) {
    const name = e instanceof DOMException ? e.name : "";
    if (name === "NotFoundError" || name === "OverconstrainedError") throw new MicError("no_mic", MIC_MESSAGES.no_mic);
    throw new MicError("blocked", MIC_MESSAGES.blocked);
  }

  const chunks: Blob[] = [];
  const recorder = new MediaRecorder(stream);
  recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
  recorder.start(250);

  // a level meter, so the judge can see they are being heard
  const w = window as unknown as AudioWindow;
  const Ctx = w.AudioContext ?? w.webkitAudioContext;
  let meter: ReturnType<typeof setInterval> | null = null;
  let meterCtx: AudioContext | null = null;
  if (onLevel && Ctx) {
    meterCtx = new Ctx();
    const analyser = meterCtx.createAnalyser();
    analyser.fftSize = 512;
    meterCtx.createMediaStreamSource(stream).connect(analyser);
    const buf = new Float32Array(analyser.fftSize);
    meter = setInterval(() => { analyser.getFloatTimeDomainData(buf); onLevel(peak(buf)); }, 90);
  }

  const release = () => {
    if (meter) clearInterval(meter);
    void meterCtx?.close().catch(() => {});
    stream.getTracks().forEach((t) => t.stop());
  };

  return {
    stop: () =>
      new Promise((resolve, reject) => {
        recorder.onstop = () => {
          release();
          toWav(new Blob(chunks, { type: recorder.mimeType || "audio/webm" })).then(({ wav, seconds }) => resolve({ wav, seconds }), reject);
        };
        if (recorder.state === "inactive") recorder.onstop(new Event("stop"));
        else recorder.stop();
      }),
    cancel: () => {
      recorder.onstop = null;
      if (recorder.state !== "inactive") recorder.stop();
      release();
    },
  };
}
