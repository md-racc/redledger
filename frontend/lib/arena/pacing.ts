// Scroll pacing. The page scrolls linearly, but the camera should not: it lingers at each chapter so the caption can be
// read, and hurries through the stretches between chapters where there is nothing to read.
//
// The rail parameter `u` (0..1 along the camera rail, where the chapters sit at CHAPTERS[i].at) is mapped from the
// scroll fraction `s` through a speed profile: slow (SLOW) inside a reading zone of ±DWELL_HALF around each chapter,
// fast (FAST) everywhere else. s(u) is the integral of 1/speed, normalised, and railOf() inverts it from a lookup table.
import { CHAPTERS } from "./timeline";

/** half-width, in rail space, of a reading zone around a chapter */
export const DWELL_HALF = 0.05;
/** camera speed (rail units per unit of scroll, relative) inside a reading zone and between zones */
export const SLOW = 0.22;
export const FAST = 2.6;

const N = 2048;
let table: Float64Array | null = null;

/** 1 at the heart of a reading zone, easing to 0 at its edge. */
function bump(u: number): number {
  let b = 0;
  for (const c of CHAPTERS) {
    const d = Math.abs(u - c.at) / DWELL_HALF;
    if (d >= 1) continue;
    const t = d <= 0.35 ? 0 : (d - 0.35) / 0.65; // flat core, smooth shoulder
    b = Math.max(b, 1 - t * t * (3 - 2 * t));
  }
  return b;
}

export const railSpeed = (u: number): number => FAST + (SLOW - FAST) * bump(u);

function build(): Float64Array {
  if (table) return table;
  const t = new Float64Array(N + 1);
  let acc = 0;
  for (let i = 1; i <= N; i++) {
    acc += 1 / railSpeed(((i - 0.5) / N)) / N;
    t[i] = acc;
  }
  for (let i = 1; i <= N; i++) t[i] /= acc;
  table = t;
  return t;
}

const clamp01 = (x: number) => Math.min(1, Math.max(0, x));

/** scroll fraction at which the camera reaches rail position `u` */
export function scrollOf(u: number): number {
  const t = build();
  const x = clamp01(u) * N;
  const i = Math.min(N - 1, Math.floor(x));
  return t[i] + (t[i + 1] - t[i]) * (x - i);
}

/** rail position of the camera for scroll fraction `s` */
export function railOf(s: number): number {
  const t = build();
  const v = clamp01(s);
  let lo = 0, hi = N;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (t[mid] <= v) lo = mid; else hi = mid;
  }
  const span = t[hi] - t[lo] || 1;
  return (lo + (v - t[lo]) / span) / N;
}
