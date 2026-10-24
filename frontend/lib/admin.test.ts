import { describe, expect, it } from "vitest";
import {
  ADMIN_COOKIE,
  ADMIN_TTL_SEC,
  adminCookie,
  adminSettings,
  clearedAdminCookie,
  clientIp,
  keyMatches,
  readCookie,
  requestRole,
  signAdminToken,
  verifyAdminToken,
} from "./admin";

const KEY = "k".repeat(40);
const T0 = 1_800_000_000;

describe("admin token", () => {
  it("verifies a token it signed, for seven days", () => {
    const t = signAdminToken(KEY, T0);
    expect(t).toMatch(/^v1\.\d+\.\d+\.[A-Za-z0-9_-]+$/);
    expect(verifyAdminToken(t, KEY, T0)).toBe(true);
    expect(verifyAdminToken(t, KEY, T0 + ADMIN_TTL_SEC - 1)).toBe(true);
  });

  it("refuses a tampered token", () => {
    const t = signAdminToken(KEY, T0);
    const [v, iat, exp, sig] = t.split(".");
    expect(verifyAdminToken(`${v}.${iat}.${Number(exp) + 3600}.${sig}`, KEY, T0)).toBe(false); // stretched expiry
    expect(verifyAdminToken(`${v}.${iat}.${exp}.${sig!.slice(0, -1)}${sig!.endsWith("A") ? "B" : "A"}`, KEY, T0)).toBe(false);
    expect(verifyAdminToken(`v2.${iat}.${exp}.${sig}`, KEY, T0)).toBe(false);
    for (const bad of ["", "v1", "v1.1.2", "a.b.c.d", `${t}.x`, "x".repeat(300), null, undefined]) expect(verifyAdminToken(bad, KEY, T0)).toBe(false);
  });

  it("refuses an expired token, and one issued in the future", () => {
    const t = signAdminToken(KEY, T0);
    expect(verifyAdminToken(t, KEY, T0 + ADMIN_TTL_SEC)).toBe(false);
    expect(verifyAdminToken(t, KEY, T0 - 3600)).toBe(false);
    expect(verifyAdminToken(signAdminToken(KEY, T0, ADMIN_TTL_SEC * 2), KEY, T0)).toBe(false); // a lifetime we never mint
  });

  it("is void once ADMIN_KEY rotates", () => {
    const t = signAdminToken(KEY, T0);
    expect(verifyAdminToken(t, `${KEY}-rotated`, T0)).toBe(false);
  });

  it("compares the submitted key in constant time, whatever its length", () => {
    expect(keyMatches(KEY, KEY)).toBe(true);
    expect(keyMatches(`${KEY}x`, KEY)).toBe(false);
    expect(keyMatches("short", KEY)).toBe(false);
    expect(keyMatches("", KEY)).toBe(false);
    expect(keyMatches(undefined, KEY)).toBe(false);
    expect(keyMatches({ key: KEY }, KEY)).toBe(false);
  });
});

describe("who is admin", () => {
  const withCookie = (token: string) => new Headers({ cookie: `CF_Authorization=abc; ${ADMIN_COOKIE}=${token}; other=1` });

  it("with ADMIN_KEY: only a valid cookie", () => {
    const env = { ADMIN_KEY: KEY, NODE_ENV: "production" };
    expect(requestRole(withCookie(signAdminToken(KEY)), env)).toBe("admin");
    expect(requestRole(withCookie(signAdminToken("other")), env)).toBe("viewer");
    expect(requestRole(new Headers(), env)).toBe("viewer");
    expect(requestRole(withCookie(signAdminToken(KEY, T0)), env, T0 + ADMIN_TTL_SEC + 1)).toBe("viewer");
  });

  it("fails closed in production without a key, open in development and mock mode", () => {
    expect(adminSettings({ NODE_ENV: "production" })).toEqual({ mode: "closed" });
    expect(requestRole(withCookie(signAdminToken(KEY)), { NODE_ENV: "production" })).toBe("viewer");
    expect(adminSettings({ NODE_ENV: "development" })).toEqual({ mode: "open" });
    expect(adminSettings({ NODE_ENV: "production", NEXT_PUBLIC_MOCK: "true" })).toEqual({ mode: "open" });
    expect(requestRole(new Headers(), { NODE_ENV: "development" })).toBe("admin");
    expect(adminSettings({ NODE_ENV: "production", ADMIN_KEY: "  " })).toEqual({ mode: "closed" }); // blank is unset
  });

  it("sets an HttpOnly, SameSite=Strict cookie, Secure in production", () => {
    const prod = adminCookie("tok", { NODE_ENV: "production" });
    expect(prod).toContain(`${ADMIN_COOKIE}=tok`);
    for (const attr of ["HttpOnly", "SameSite=Strict", "Secure", "Path=/", `Max-Age=${ADMIN_TTL_SEC}`]) expect(prod).toContain(attr);
    expect(adminCookie("tok", { NODE_ENV: "development" })).not.toContain("Secure");
    expect(clearedAdminCookie({ NODE_ENV: "production" })).toContain("Max-Age=0");
  });

  it("reads cookies and the client address", () => {
    expect(readCookie(new Headers({ cookie: "a=1; rl_admin=xyz" }), "rl_admin")).toBe("xyz");
    expect(readCookie(new Headers({ cookie: "rl_admin=" }), "rl_admin")).toBeNull();
    expect(clientIp(new Headers({ "cf-connecting-ip": "1.1.1.1", "x-forwarded-for": "2.2.2.2" }))).toBe("1.1.1.1");
    expect(clientIp(new Headers({ "x-forwarded-for": "3.3.3.3, 10.0.0.1" }))).toBe("3.3.3.3");
    expect(clientIp(new Headers())).toBe("unknown");
  });
});
