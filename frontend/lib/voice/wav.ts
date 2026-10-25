// Audio for speech-to-text. Owner: Dev R.
//
// The browser records whatever codec it likes (webm/opus on Chrome, mp4 on Safari). Speech-to-text takes "all major formats", but a
// format that is only probably accepted is a risk on stage, so the recording is decoded, brought to 16 kHz mono and sent as a plain
// 16-bit PCM WAV: a format every recogniser accepts, small (32 kB per second), and the same bytes everywhere. These are the pure
// parts (tested); the decoding and resampling use the browser's own audio engine (lib/voice/recorder.ts).

export const WAV_RATE = 16_000;

/** Average the channels of a decoded buffer into one. */
export function mixToMono(channels: Float32Array[]): Float32Array {
  if (channels.length === 0) return new Float32Array(0);
  if (channels.length === 1) return channels[0];
  const out = new Float32Array(channels[0].length);
  for (const ch of channels) for (let i = 0; i < out.length; i++) out[i] += ch[i] / channels.length;
  return out;
}

/** Float samples in [-1, 1] to 16-bit signed PCM, clipped. */
export function floatToPcm16(samples: Float32Array): Int16Array {
  const out = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    out[i] = s < 0 ? Math.round(s * 0x8000) : Math.round(s * 0x7fff);
  }
  return out;
}

/** A canonical 44-byte-header WAV (RIFF, PCM, mono, 16-bit) around the samples. */
export function encodeWav(pcm: Int16Array, sampleRate = WAV_RATE): Uint8Array {
  const bytes = pcm.length * 2;
  const buf = new ArrayBuffer(44 + bytes);
  const v = new DataView(buf);
  const str = (o: number, s: string) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  str(0, "RIFF");
  v.setUint32(4, 36 + bytes, true);
  str(8, "WAVE");
  str(12, "fmt ");
  v.setUint32(16, 16, true); // fmt chunk size
  v.setUint16(20, 1, true); // PCM
  v.setUint16(22, 1, true); // mono
  v.setUint32(24, sampleRate, true);
  v.setUint32(28, sampleRate * 2, true); // byte rate
  v.setUint16(32, 2, true); // block align
  v.setUint16(34, 16, true); // bits per sample
  str(36, "data");
  v.setUint32(40, bytes, true);
  new Int16Array(buf, 44, pcm.length).set(pcm);
  return new Uint8Array(buf);
}

/** Seconds of audio in a WAV made by `encodeWav`. */
export function wavSeconds(wav: Uint8Array): number {
  if (wav.length < 44) return 0;
  const v = new DataView(wav.buffer, wav.byteOffset, wav.byteLength);
  const rate = v.getUint32(24, true) || WAV_RATE;
  return v.getUint32(40, true) / 2 / rate;
}

/** Peak level of the samples, 0..1 (for the "are you being heard" meter). */
export function peak(samples: Float32Array): number {
  let p = 0;
  for (let i = 0; i < samples.length; i++) p = Math.max(p, Math.abs(samples[i]));
  return p;
}
