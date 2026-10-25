// Route-level role enforcement: the /api/bf proxy, the WS ticket, the sync relay, login/logout and whoami, called as Next calls them.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as proxyRoute from "@/app/api/bf/[...path]/route";
import * as ticketRoute from "@/app/api/bf/ws-ticket/route";
import * as syncRoute from "@/app/api/sync/route";
import * as loginRoute from "@/app/api/admin/login/route";
import * as logoutRoute from "@/app/api/admin/logout/route";
import * as whoamiRoute from "@/app/api/whoami/route";
import { ADMIN_COOKIE, signAdminToken } from "./admin";
import { LOGIN_FAILURES_PER_WINDOW, MAX_SYNC_STREAMS, VIEWER_BURST, syncStreamSlots } from "./ratelimit";
import * as streamRoute from "@/app/api/sync/stream/route";

const KEY = "test-admin-key-0123456789abcdef-0123456789";
const BASE = "http://app.test";
const adminCookie = () => `${ADMIN_COOKIE}=${signAdminToken(KEY)}`;
let ipSeq = 0;
const freshIp = () => `10.9.${Math.floor(++ipSeq / 250)}.${ipSeq % 250}`;

function req(method: string, path: string, opts: { admin?: boolean; body?: unknown; ip?: string; headers?: Record<string, string> } = {}): Request {
  const headers: Record<string, string> = { "cf-connecting-ip": opts.ip ?? freshIp(), ...(opts.headers ?? {}) };
  if (opts.admin) headers.cookie = adminCookie();
  if (opts.body !== undefined) headers["content-type"] = "application/json";
  return new Request(`${BASE}${path}`, { method, headers, body: opts.body === undefined ? undefined : JSON.stringify(opts.body) });
}

let upstream: ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.stubEnv("ADMIN_KEY", KEY);
  delete (globalThis as { __rlLoginFailures?: unknown }).__rlLoginFailures; // each test starts a fresh global failure window
  vi.stubEnv("BATTLEFIELD_URL", "http://battlefield:8000");
  vi.stubEnv("OPERATOR_TOKEN", "optoken");
  upstream = vi.fn(async (url: string | URL | Request) => {
    const u = String(url);
    if (u.endsWith("/api/ws/ticket")) return Response.json({ ticket: "t1", expires_at: null });
    return Response.json({ ok: true, url: u });
  });
  vi.stubGlobal("fetch", upstream);
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("the /api/bf proxy", () => {
  it("refuses a viewer's write with 403 {error: viewer} without contacting battlefield", async () => {
    for (const m of ["POST", "PUT", "PATCH", "DELETE"] as const) {
      const res = await proxyRoute[m](req(m, "/api/bf/episodes", { body: { controller_mode: "enforce" } }));
      expect(res.status, m).toBe(403);
      expect(await res.json()).toEqual({ error: "viewer" });
    }
    expect(upstream).not.toHaveBeenCalled();
  });

  it("forwards a viewer's read", async () => {
    const res = await proxyRoute.GET(req("GET", "/api/bf/episodes"));
    expect(res.status).toBe(200);
    expect(upstream).toHaveBeenCalledTimes(1);
    const [url, init] = upstream.mock.calls[0]!;
    expect(String(url)).toBe("http://battlefield:8000/api/episodes");
    expect((init as RequestInit).method).toBe("GET");
  });

  it("forwards an admin's write with the operator token", async () => {
    const res = await proxyRoute.POST(req("POST", "/api/bf/episodes/ep_1/attack", { admin: true, body: { scheme_id: "ghost_vendor" } }));
    expect(res.status).toBe(200);
    expect(upstream).toHaveBeenCalledTimes(1);
    const [url, init] = upstream.mock.calls[0]!;
    expect(String(url)).toBe("http://battlefield:8000/api/episodes/ep_1/attack");
    expect((init as RequestInit).method).toBe("POST");
    expect(new Headers((init as RequestInit).headers).get("authorization")).toBe("Bearer optoken");
  });

  it("treats a forged or stale cookie as a viewer", async () => {
    const forged = `${ADMIN_COOKIE}=${signAdminToken("not-the-key")}`;
    const res = await proxyRoute.POST(req("POST", "/api/bf/episodes", { body: {}, headers: { cookie: forged } }));
    expect(res.status).toBe(403);
    expect(upstream).not.toHaveBeenCalled();
  });

  it("keeps refusing cross-site mutations, admins included", async () => {
    const res = await proxyRoute.POST(req("POST", "/api/bf/episodes", { admin: true, body: {}, headers: { "sec-fetch-site": "cross-site" } }));
    expect(res.status).toBe(403);
    expect(upstream).not.toHaveBeenCalled();
  });

  it("rate limits a viewer per address, never an admin", async () => {
    const ip = freshIp();
    let limited: Response | null = null;
    for (let i = 0; i < VIEWER_BURST + 5 && !limited; i++) {
      const res = await proxyRoute.GET(req("GET", "/api/bf/health", { ip }));
      if (res.status === 429) limited = res;
    }
    expect(limited?.status).toBe(429);
    expect(Number(limited?.headers.get("retry-after"))).toBeGreaterThanOrEqual(1);
    expect(upstream.mock.calls.length).toBeLessThanOrEqual(VIEWER_BURST + 1);
    expect((await proxyRoute.GET(req("GET", "/api/bf/health", { ip, admin: true }))).status).toBe(200);
    expect((await proxyRoute.GET(req("GET", "/api/bf/health"))).status).toBe(200); // another address is unaffected
  });

  it("nobody is admin in production without ADMIN_KEY", async () => {
    vi.stubEnv("ADMIN_KEY", "");
    vi.stubEnv("NODE_ENV", "production");
    const res = await proxyRoute.POST(req("POST", "/api/bf/episodes", { admin: true, body: {} }));
    expect(res.status).toBe(403);
    expect(upstream).not.toHaveBeenCalled();
  });

  it("everyone is admin in development without ADMIN_KEY (local dev unchanged)", async () => {
    vi.stubEnv("ADMIN_KEY", "");
    vi.stubEnv("NODE_ENV", "development");
    const res = await proxyRoute.POST(req("POST", "/api/bf/episodes", { body: {} }));
    expect(res.status).toBe(200);
    expect(upstream).toHaveBeenCalledTimes(1);
  });
});

describe("the WS ticket", () => {
  it("is available to viewers (the stream is read-only)", async () => {
    const res = await ticketRoute.GET(req("GET", "/api/bf/ws-ticket?episode_id=ep_1"));
    expect(res.status).toBe(200);
    expect((await res.json()).ticket).toBe("t1");
  });

  it("is rate limited for viewers", async () => {
    const ip = freshIp();
    const codes: number[] = [];
    for (let i = 0; i < VIEWER_BURST + 3; i++) codes.push((await ticketRoute.GET(req("GET", "/api/bf/ws-ticket?episode_id=e", { ip }))).status);
    expect(codes).toContain(429);
  });
});

describe("the sync relay", () => {
  const msg = { client: "arena-1", kind: "select", data: { id: "red:ghost_vendor" } };

  it("takes a publish only from an admin", async () => {
    const viewer = await syncRoute.POST(req("POST", "/api/sync", { body: msg }));
    expect(viewer.status).toBe(403);
    expect(await viewer.json()).toEqual({ error: "viewer" });
    const admin = await syncRoute.POST(req("POST", "/api/sync", { admin: true, body: msg }));
    expect(admin.status).toBe(202);
  });

  it("reads back to anyone", async () => {
    const res = await syncRoute.GET(req("GET", "/api/sync?after=0"));
    expect(res.status).toBe(200);
  });
});

describe("login, logout, whoami", () => {
  const role = async (cookie?: string) => (await (await whoamiRoute.GET(new Request(`${BASE}/api/whoami`, { headers: cookie ? { cookie } : {} }))).json()).role;

  it("logs in with the key and sets the signed cookie", async () => {
    const bad = await loginRoute.POST(req("POST", "/api/admin/login", { body: { key: "nope" } }));
    expect(bad.status).toBe(401);
    expect(bad.headers.get("set-cookie")).toBeNull();

    const ok = await loginRoute.POST(req("POST", "/api/admin/login", { body: { key: KEY } }));
    expect(ok.status).toBe(200);
    const setCookie = ok.headers.get("set-cookie")!;
    expect(setCookie).toMatch(new RegExp(`^${ADMIN_COOKIE}=v1\\.`));
    expect(setCookie).toContain("HttpOnly");
    expect(setCookie).toContain("SameSite=Strict");
    expect(await role(setCookie.split(";")[0])).toBe("admin");
    expect(await role()).toBe("viewer");
  });

  it("rotating ADMIN_KEY makes the old cookie a viewer", async () => {
    const cookie = adminCookie();
    expect(await role(cookie)).toBe("admin");
    vi.stubEnv("ADMIN_KEY", `${KEY}-next`);
    expect(await role(cookie)).toBe("viewer");
  });

  it("slows down guessing", async () => {
    const ip = freshIp();
    const codes: number[] = [];
    for (let i = 0; i < 8; i++) codes.push((await loginRoute.POST(req("POST", "/api/admin/login", { ip, body: { key: "guess" } }))).status);
    expect(codes).toContain(429);
  });

  it("answers 503 in production without a key, and logs out by clearing the cookie", async () => {
    vi.stubEnv("ADMIN_KEY", "");
    vi.stubEnv("NODE_ENV", "production");
    expect((await loginRoute.POST(req("POST", "/api/admin/login", { body: { key: "x" } }))).status).toBe(503);
    const out = await logoutRoute.POST(req("POST", "/api/admin/logout"));
    expect(out.status).toBe(200);
    expect(out.headers.get("set-cookie")).toContain("Max-Age=0");
  });
});

describe("production hardening", () => {
  const prod = () => vi.stubEnv("NODE_ENV", "production");
  const whoami = async (cookie?: string) => (await (await whoamiRoute.GET(new Request(`${BASE}/api/whoami`, { headers: cookie ? { cookie } : {} }))).json()).role;

  it("a runtime NEXT_PUBLIC_MOCK=true never makes visitors admin in production", async () => {
    prod();
    vi.stubEnv("NEXT_PUBLIC_MOCK", "true");
    vi.stubEnv("ADMIN_KEY", "");
    expect(await whoami()).toBe("viewer");
    const res = await proxyRoute.POST(req("POST", "/api/bf/episodes", { body: { controller_mode: "enforce" } }));
    expect(res.status).toBe(403);
    expect(await res.json()).toEqual({ error: "viewer" });
    expect((await syncRoute.POST(req("POST", "/api/sync", { body: { client: "a", kind: "hello", data: {} } }))).status).toBe(403);
    expect(upstream).not.toHaveBeenCalled();
  });

  it("an ADMIN_KEY under 32 characters disables admin in production", async () => {
    prod();
    const short = "only-twenty-chars-xx";
    vi.stubEnv("ADMIN_KEY", short);
    const login = await loginRoute.POST(req("POST", "/api/admin/login", { body: { key: short } }));
    expect(login.status).toBe(503);
    expect(login.headers.get("set-cookie")).toBeNull();
    const cookie = `${ADMIN_COOKIE}=${signAdminToken(short)}`;
    expect(await whoami(cookie)).toBe("viewer");
    expect((await proxyRoute.POST(req("POST", "/api/bf/episodes", { body: {}, headers: { cookie } }))).status).toBe(403);
    expect(upstream).not.toHaveBeenCalled();
  });

  it("caps failed logins across all addresses, then refuses every login for the rest of the window", async () => {
    for (let i = 0; i < LOGIN_FAILURES_PER_WINDOW; i++) {
      // a new address each time: the per-address bucket never trips
      expect((await loginRoute.POST(req("POST", "/api/admin/login", { body: { key: `guess-${i}` } }))).status, `guess ${i}`).toBe(401);
    }
    const blocked = await loginRoute.POST(req("POST", "/api/admin/login", { body: { key: "another" } }));
    expect(blocked.status).toBe(429);
    expect(Number(blocked.headers.get("retry-after"))).toBeGreaterThanOrEqual(1);
    const right = await loginRoute.POST(req("POST", "/api/admin/login", { body: { key: KEY } }));
    expect(right.status).toBe(429); // even the right key, until the window ends
    expect(right.headers.get("set-cookie")).toBeNull();
    vi.useFakeTimers({ now: Date.now() + 61_000 }); // the window ends: logins work again
    try {
      expect((await loginRoute.POST(req("POST", "/api/admin/login", { body: { key: KEY } }))).status).toBe(200);
    } finally {
      vi.useRealTimers();
    }
  });

  it("caps concurrent /api/sync/stream connections", async () => {
    const slots = syncStreamSlots();
    const held: (() => void)[] = [];
    try {
      while (slots.used < MAX_SYNC_STREAMS) held.push(slots.acquire()!);
      const full = await streamRoute.GET(new Request(`${BASE}/api/sync/stream`));
      expect(full.status).toBe(503);
      held.pop()!();
      const ctl = new AbortController();
      const ok = await streamRoute.GET(new Request(`${BASE}/api/sync/stream`, { signal: ctl.signal }));
      expect(ok.status).toBe(200);
      expect(slots.used).toBe(MAX_SYNC_STREAMS);
      ctl.abort(); // the client goes away: its slot is free again
      await ok.body?.cancel().catch(() => {});
      expect(slots.used).toBe(MAX_SYNC_STREAMS - 1);
    } finally {
      held.forEach((r) => r());
    }
    expect(slots.used).toBe(0);
  });
});
