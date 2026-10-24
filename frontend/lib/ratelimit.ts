// In-memory per-key token bucket, so a public page can't hammer battlefield through the proxy. Server-only. Owner: Dev R.
// One Node process, nothing persisted (like lib/sync/hub.ts); a restart empties it. Admins are never limited (callers skip it).

/** Viewer requests through /api/bf/* and /api/bf/ws-ticket: a sustained rate and a burst on top (page loads fire a handful at once). */
export const VIEWER_RATE_PER_SEC = 20;
export const VIEWER_BURST = 40;
/** Admin login attempts per address: a few tries, then one every 6 s. */
export const LOGIN_RATE_PER_SEC = 1 / 6;
export const LOGIN_BURST = 5;
/** Forget an address that has been quiet this long (and cap the table so it can't grow without bound). */
const IDLE_MS = 120_000;
const MAX_KEYS = 20_000;

interface Bucket { tokens: number; at: number }

export class RateLimiter {
  private buckets = new Map<string, Bucket>();
  private lastSweep = 0;

  constructor(readonly ratePerSec: number, readonly burst: number) {}

  /** Take one token for `key`. `retryAfterSec` is how long until the next one, when refused. */
  take(key: string, now = Date.now()): { ok: true } | { ok: false; retryAfterSec: number } {
    this.sweep(now);
    const b = this.buckets.get(key) ?? { tokens: this.burst, at: now };
    b.tokens = Math.min(this.burst, b.tokens + ((now - b.at) / 1000) * this.ratePerSec);
    b.at = now;
    this.buckets.delete(key); // re-insert: the map stays in least-recently-used order for the cap below
    this.buckets.set(key, b);
    if (b.tokens >= 1) {
      b.tokens -= 1;
      return { ok: true };
    }
    return { ok: false, retryAfterSec: Math.max(1, Math.ceil((1 - b.tokens) / this.ratePerSec)) };
  }

  get size(): number {
    return this.buckets.size;
  }

  private sweep(now: number): void {
    if (now - this.lastSweep >= IDLE_MS) {
      this.lastSweep = now;
      for (const [k, b] of this.buckets) if (now - b.at > IDLE_MS) this.buckets.delete(k);
    }
    while (this.buckets.size >= MAX_KEYS) {
      const oldest = this.buckets.keys().next().value;
      if (oldest === undefined) break;
      this.buckets.delete(oldest);
    }
  }
}

/** One limiter per purpose per process, whichever route module asks for it. */
export function limiter(name: "viewer" | "login"): RateLimiter {
  const g = globalThis as unknown as { __rlLimits?: Record<string, RateLimiter> };
  g.__rlLimits ??= {};
  return (g.__rlLimits[name] ??= name === "viewer" ? new RateLimiter(VIEWER_RATE_PER_SEC, VIEWER_BURST) : new RateLimiter(LOGIN_RATE_PER_SEC, LOGIN_BURST));
}

export function tooMany(retryAfterSec: number): Response {
  return new Response(JSON.stringify({ error: "rate limited" }), {
    status: 429,
    headers: { "content-type": "application/json", "cache-control": "no-store", "retry-after": String(retryAfterSec) },
  });
}
