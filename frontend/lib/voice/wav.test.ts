import { describe, expect, it } from "vitest";
import { encodeWav, floatToPcm16, mixToMono, peak, wavSeconds, WAV_RATE } from "./wav";

describe("WAV for speech-to-text", () => {
  it("writes a canonical mono 16-bit PCM header", () => {
    const wav = encodeWav(new Int16Array([0, 1000, -1000, 32767]), 16_000);
    const text = (o: number, n: number) => String.fromCharCode(...wav.slice(o, o + n));
    expect(text(0, 4)).toBe("RIFF");
    expect(text(8, 4)).toBe("WAVE");
    expect(text(12, 4)).toBe("fmt ");
    expect(text(36, 4)).toBe("data");
    const v = new DataView(wav.buffer);
    expect(v.getUint32(4, true)).toBe(36 + 8);
    expect(v.getUint16(20, true)).toBe(1); // PCM
    expect(v.getUint16(22, true)).toBe(1); // mono
    expect(v.getUint32(24, true)).toBe(16_000);
    expect(v.getUint32(28, true)).toBe(32_000);
    expect(v.getUint16(34, true)).toBe(16);
    expect(v.getUint32(40, true)).toBe(8);
    expect(wav.length).toBe(44 + 8);
    expect(v.getInt16(46, true)).toBe(1000);
    expect(v.getInt16(48, true)).toBe(-1000);
  });

  it("knows how long it is", () => {
    expect(wavSeconds(encodeWav(new Int16Array(WAV_RATE * 3)))).toBeCloseTo(3, 5);
    expect(wavSeconds(new Uint8Array(10))).toBe(0);
  });

  it("converts and clips float samples", () => {
    expect(Array.from(floatToPcm16(new Float32Array([0, 1, -1, 2, -2, 0.5])))).toEqual([0, 32767, -32768, 32767, -32768, 16384]);
  });

  it("mixes channels down to one", () => {
    const m = mixToMono([new Float32Array([1, 0, -1]), new Float32Array([0, 1, -1])]);
    expect(Array.from(m)).toEqual([0.5, 0.5, -1]);
    expect(mixToMono([]).length).toBe(0);
    const one = new Float32Array([0.25]);
    expect(mixToMono([one])).toBe(one);
  });

  it("measures the peak", () => {
    expect(peak(new Float32Array([0.1, -0.7, 0.3]))).toBeCloseTo(0.7);
    expect(peak(new Float32Array(0))).toBe(0);
  });
});
