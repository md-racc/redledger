import { describe, expect, it } from "vitest";
import {
  DEFAULT_TIMEOUT_MS,
  STEP_TIMEOUT_MS,
  downstreamResponseHeaders,
  isCrossSiteMutation,
  runtimeEnv,
  timeoutFor,
  upstreamConfig,
  upstreamPath,
  upstreamRequestHeaders,
  upstreamUrl,
} from "./proxy";

describe("upstreamPath", () => {
  it("maps /api/bf/<path> to /api/<path>", () => {
    expect(upstreamPath("/api/bf/episodes")).toBe("/api/episodes");
    expect(upstreamPath("/api/bf/fe/episodes/ep_1/snapshot")).toBe("/api/fe/episodes/ep_1/snapshot");
    expect(upstreamPath("/api/bf/x/fe/crowd/join")).toBe("/api/x/fe/crowd/join");
    expect(upstreamPath("/api/bf/fe/episodes/ep%201/search")).toBe("/api/fe/episodes/ep%201/search");
  });

  it("rejects traversal, encoded separators and host changes", () => {
    for (const p of [
      "/api/bf/",
      "/api/bf",
      "/api/other/episodes",
      "/api/bf/../health",
      "/api/bf/episodes/../../admin",
      "/api/bf/%2e%2e/admin",
      "/api/bf/%2E%2E/admin",
      "/api/bf/./episodes",
      "/api/bf/episodes%2F..%2Fadmin",
      "/api/bf/episodes%5C..",
      "/api/bf/episodes\\..",
      "/api/bf//evil.example/x",
      "/api/bf/http:/evil.example",
      "/api/bf/episodes/%00",
      "/api/bf/episodes/%E0%A4%A",
    ]) {
      expect(upstreamPath(p), p).toBeNull();
    }
  });
});

describe("upstreamUrl", () => {
  it("joins base, path and query on the battlefield origin", () => {
    expect(upstreamUrl("http://battlefield:8000", "/api/events", "?episode_id=e&after_id=3")).toBe(
      "http://battlefield:8000/api/events?episode_id=e&after_id=3",
    );
    expect(upstreamUrl("https://host/prefix/", "/api/episodes", "")).toBe("https://host/prefix/api/episodes");
  });

  it("refuses a bad base", () => {
    expect(upstreamUrl("not a url", "/api/episodes", "")).toBeNull();
  });
});

describe("upstreamConfig / runtimeEnv", () => {
  it("needs both server vars", () => {
    expect(upstreamConfig({})).toBeNull();
    expect(upstreamConfig({ BATTLEFIELD_URL: "http://bf:8000" })).toBeNull();
    expect(upstreamConfig({ OPERATOR_TOKEN: "t" })).toBeNull();
    expect(upstreamConfig({ BATTLEFIELD_URL: "http://bf:8000/", OPERATOR_TOKEN: " " })).toBeNull();
    expect(upstreamConfig({ BATTLEFIELD_URL: "http://bf:8000/", OPERATOR_TOKEN: "t" })).toEqual({
      battlefieldUrl: "http://bf:8000",
      operatorToken: "t",
    });
  });

  it("treats blank as unset", () => {
    expect(runtimeEnv("X", { X: "" })).toBeUndefined();
    expect(runtimeEnv("X", { X: " ws://a " })).toBe("ws://a");
  });
});

describe("headers", () => {
  it("replaces browser auth with the operator bearer and drops everything else", () => {
    const h = upstreamRequestHeaders(
      new Headers({
        authorization: "Bearer from-browser",
        cookie: "CF_Authorization=abc",
        "x-agent": "red",
        "x-episode": "ep",
        connection: "keep-alive",
        "transfer-encoding": "chunked",
        "x-forwarded-for": "1.2.3.4",
        "content-type": "application/json",
        accept: "application/json",
      }),
      "OPTOKEN",
    );
    expect(h.get("authorization")).toBe("Bearer OPTOKEN");
    expect(h.get("content-type")).toBe("application/json");
    expect(h.get("accept")).toBe("application/json");
    for (const n of ["cookie", "x-agent", "x-episode", "connection", "transfer-encoding", "x-forwarded-for"]) {
      expect(h.get(n), n).toBeNull();
    }
  });

  it("copies only safe response headers back", () => {
    const h = downstreamResponseHeaders(
      new Headers({
        "content-type": "text/markdown; charset=utf-8",
        "set-cookie": "s=1",
        "www-authenticate": "Bearer",
        connection: "close",
        "transfer-encoding": "chunked",
        "content-encoding": "gzip",
        "content-length": "10",
      }),
    );
    expect(h.get("content-type")).toBe("text/markdown; charset=utf-8");
    for (const n of ["set-cookie", "www-authenticate", "connection", "transfer-encoding", "content-encoding", "content-length"]) {
      expect(h.get(n), n).toBeNull();
    }
  });
});

describe("policy", () => {
  it("gives step the long timeout", () => {
    expect(timeoutFor("POST", "/api/episodes/ep_1/step")).toBe(STEP_TIMEOUT_MS);
    expect(timeoutFor("GET", "/api/episodes/ep_1/step")).toBe(DEFAULT_TIMEOUT_MS);
    expect(timeoutFor("POST", "/api/escalations/e/resolve")).toBe(DEFAULT_TIMEOUT_MS);
  });

  it("refuses cross-site mutations only", () => {
    const cross = new Headers({ "sec-fetch-site": "cross-site" });
    expect(isCrossSiteMutation("POST", cross)).toBe(true);
    expect(isCrossSiteMutation("GET", cross)).toBe(false);
    expect(isCrossSiteMutation("POST", new Headers({ "sec-fetch-site": "same-origin" }))).toBe(false);
    expect(isCrossSiteMutation("POST", new Headers())).toBe(false);
  });
});
