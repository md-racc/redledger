import { describe, expect, it } from "vitest";
import { RateLimiter, limiter, VIEWER_BURST, VIEWER_RATE_PER_SEC } from "./ratelimit";

describe("rate limiter", () => {
  it("lets a burst through, then refills at the rate", () => {
    const rl = new RateLimiter(20, 40);
    const t = 1_000_000;
    for (let i = 0; i < 40; i++) expect(rl.take("1.2.3.4", t).ok).toBe(true);
    const refused = rl.take("1.2.3.4", t);
    expect(refused).toEqual({ ok: false, retryAfterSec: 1 });
    expect(rl.take("1.2.3.4", t + 50).ok).toBe(true); // 50 ms at 20/s = one token
    expect(rl.take("1.2.3.4", t + 50).ok).toBe(false);
  });

  it("keeps a bucket per address", () => {
    const rl = new RateLimiter(1, 2);
    expect(rl.take("a", 0).ok).toBe(true);
    expect(rl.take("a", 0).ok).toBe(true);
    expect(rl.take("a", 0).ok).toBe(false);
    expect(rl.take("b", 0).ok).toBe(true);
  });

  it("forgets quiet addresses", () => {
    const rl = new RateLimiter(1, 2);
    rl.take("a", 0);
    rl.take("b", 0);
    expect(rl.size).toBe(2);
    rl.take("c", 10 * 60_000);
    expect(rl.size).toBe(1);
  });

  it("is generous for viewers and shared by every route in the process", () => {
    expect(VIEWER_RATE_PER_SEC).toBeGreaterThanOrEqual(10);
    expect(VIEWER_BURST).toBeGreaterThanOrEqual(VIEWER_RATE_PER_SEC);
    expect(limiter("viewer")).toBe(limiter("viewer"));
    expect(limiter("login")).not.toBe(limiter("viewer"));
  });
});
