// The hidden doors: red.<site> and blue.<site> show the console to an admin and a plain 404 to everyone else.
import React from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import nextConfig from "../../next.config";
import { ADMIN_COOKIE, signAdminToken } from "../admin";
import { backstageGate } from "./gate";

const KEY = "test-admin-key-0123456789abcdef-0123456789";
const admin = `${ADMIN_COOKIE}=${signAdminToken(KEY)}`;
const hdrs = (host: string, cookie?: string) => new Headers({ host, ...(cookie ? { cookie } : {}) });

let current = new Headers();
vi.mock("next/headers", () => ({ headers: async () => current }));

// vitest compiles the page's JSX with the classic runtime: give it React
beforeAll(() => { (globalThis as { React?: typeof React }).React = React; });
beforeEach(() => { vi.stubEnv("ADMIN_KEY", KEY); });
afterEach(() => { vi.unstubAllEnvs(); });

describe("who sees what behind a door", () => {
  it("leaves the plain site and the plain /backstage paths alone", () => {
    expect(backstageGate(hdrs("app.redledger.us"))).toBe("open");
    expect(backstageGate(hdrs("localhost:3104"))).toBe("open");
  });

  it("hides a door from a viewer, whichever door", () => {
    expect(backstageGate(hdrs("red.redledger.us"))).toBe("hidden");
    expect(backstageGate(hdrs("blue.redledger.us"))).toBe("hidden");
    expect(backstageGate(hdrs("red.redledger.us", "rl_admin=garbage"))).toBe("hidden");
    expect(backstageGate(hdrs("blue.redledger.us", `${ADMIN_COOKIE}=${signAdminToken("a-different-key-0123456789abcdef-0123")}`))).toBe("hidden");
  });

  it("opens a door for an admin", () => {
    expect(backstageGate(hdrs("red.redledger.us", admin))).toBe("open");
    expect(backstageGate(hdrs("blue.redledger.us", admin))).toBe("open");
  });

  it("is closed to everyone in production when no admin key is set", () => {
    vi.stubEnv("ADMIN_KEY", "");
    vi.stubEnv("NODE_ENV", "production");
    expect(backstageGate(hdrs("red.redledger.us", admin))).toBe("hidden");
  });

  it("is open to everyone under `next dev` with no admin key", () => {
    vi.stubEnv("ADMIN_KEY", "");
    vi.stubEnv("NODE_ENV", "development");
    expect(backstageGate(hdrs("red.localhost:3104"))).toBe("open");
  });
});

describe("the console pages", () => {
  const render = async (team: string) => {
    const page = (await import("../../app/backstage/[team]/page")).default;
    return page({ params: Promise.resolve({ team }) });
  };
  const hub = async () => (await import("../../app/backstage/page")).default();
  const is404 = { digest: expect.stringMatching(/404|NOT_FOUND/) };

  it("answers a viewer on a door with the same 404 a missing page gives", async () => {
    current = hdrs("red.redledger.us");
    await expect(render("red")).rejects.toMatchObject(is404);
    await expect(hub()).rejects.toMatchObject(is404);
    current = hdrs("blue.redledger.us", "rl_admin=nope");
    await expect(render("blue")).rejects.toMatchObject(is404);
    // a door is a door for every console: red.<site> does not show green's console to a stranger either
    current = hdrs("red.redledger.us");
    await expect(render("green")).rejects.toMatchObject(is404);
  });

  it("shows the console to an admin on a door, and to anyone on the plain path", async () => {
    current = hdrs("red.redledger.us", admin);
    expect(await render("red")).toBeTruthy();
    current = hdrs("app.redledger.us");
    expect(await render("blue")).toBeTruthy();
  });

  it("still 404s a team that does not exist", async () => {
    current = hdrs("red.redledger.us", admin);
    await expect(render("purple")).rejects.toMatchObject(is404);
  });
});

describe("the rewrite that makes `/` a door", () => {
  it("applies only to red.* and blue.* hosts, and only to `/`", async () => {
    const rw = (await nextConfig.rewrites!()) as { beforeFiles: { source: string; destination: string; has: { type: string; value: string }[] }[] };
    expect(rw.beforeFiles).toHaveLength(1);
    const r = rw.beforeFiles[0]!;
    expect(r.source).toBe("/");
    expect(r.destination).toBe("/backstage/:team");
    const re = new RegExp(`^${r.has[0]!.value}$`);
    for (const h of ["red.redledger.us", "blue.localhost", "red.app.example.com"]) expect(re.test(h), h).toBe(true);
    expect(re.exec("blue.redledger.us")?.groups?.["team"]).toBe("blue");
    for (const h of ["app.redledger.us", "redledger.us", "green.redledger.us", "redhat.com", "red", "notred.example.com"]) expect(re.test(h), h).toBe(false);
  });
});
