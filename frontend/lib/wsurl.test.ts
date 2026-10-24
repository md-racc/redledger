import { describe, expect, it } from "vitest";
import { DEFAULT_WS_URL, wsBaseUrl } from "./wsurl";

const h = (o: Record<string, string>) => new Headers(o);

describe("wsBaseUrl", () => {
  it("uses a real configured socket as it is", () => {
    expect(wsBaseUrl("wss://app.example.com/", h({ host: "app.example.com" }), "https://app.example.com/api/bf/ws-ticket")).toBe("wss://app.example.com");
  });
  it("on a developer's machine the default stays the local battlefield", () => {
    expect(wsBaseUrl(undefined, h({ host: "localhost:3000" }), "http://localhost:3000/x")).toBe(DEFAULT_WS_URL);
    expect(wsBaseUrl("ws://localhost:8000", h({ host: "localhost:3000" }), "http://localhost:3000/x")).toBe("ws://localhost:8000");
  });
  it("on the deployed domain, no setting means the page's own host over wss", () => {
    expect(wsBaseUrl(undefined, h({ "x-forwarded-host": "app.example.com", "x-forwarded-proto": "https" }), "http://frontend:3000/api/bf/ws-ticket")).toBe("wss://app.example.com");
  });
  it("and the compose default (localhost) is not dialled by a laptop on the domain", () => {
    expect(wsBaseUrl("ws://localhost:8000", h({ host: "app.example.com", "x-forwarded-proto": "https" }), "https://app.example.com/x")).toBe("wss://app.example.com");
    expect(wsBaseUrl("", h({ host: "192.168.1.20:3000" }), "http://192.168.1.20:3000/x")).toBe("ws://192.168.1.20:3000");
  });
});
