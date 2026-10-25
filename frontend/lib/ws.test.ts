// lib/ws.ts: malformed frames are dropped, a refused ticket is retried slowly and then given up, a flaky one keeps retrying.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { connect } from "./ws";

class FakeSocket {
  static last: FakeSocket | null = null;
  onmessage: ((m: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  constructor(readonly url: string) { FakeSocket.last = this; }
  close() { this.onclose?.(); }
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.useFakeTimers();
  FakeSocket.last = null;
  vi.stubGlobal("WebSocket", FakeSocket);
  vi.stubGlobal("sessionStorage", { getItem: () => null, setItem: () => {} });
  vi.spyOn(console, "warn").mockImplementation(() => {});
  fetchMock = vi.fn(async () => Response.json({ ticket: "t1", ws_url: "ws://x" }));
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("connect", () => {
  it("drops a malformed frame and keeps delivering the next ones", async () => {
    const got: unknown[] = [];
    const stop = connect("ep_1", (e) => got.push(e));
    await vi.waitFor(() => expect(FakeSocket.last).not.toBeNull());
    const sock = FakeSocket.last!;
    expect(() => sock.onmessage!({ data: "{not json" })).not.toThrow();
    sock.onmessage!({ data: JSON.stringify({ type: "ping" }) });
    sock.onmessage!({ data: JSON.stringify({ id: 7, type: "day.started" }) });
    expect(got).toEqual([{ id: 7, type: "day.started" }]);
    stop();
  });

  it("gives up after five refused tickets instead of asking forever", async () => {
    fetchMock.mockImplementation(async () => new Response("{}", { status: 404 }));
    const stop = connect("ep_gone", () => {});
    for (let i = 0; i < 10; i++) await vi.advanceTimersByTimeAsync(20_000);
    expect(fetchMock).toHaveBeenCalledTimes(5);
    expect(FakeSocket.last).toBeNull();
    stop();
  });

  it("keeps retrying a ticket that fails for a reason waiting can fix (rate limit, 5xx)", async () => {
    fetchMock.mockImplementation(async () => new Response("{}", { status: 429 }));
    const stop = connect("ep_1", () => {});
    for (let i = 0; i < 10; i++) await vi.advanceTimersByTimeAsync(20_000);
    expect(fetchMock.mock.calls.length).toBeGreaterThan(5);
    stop();
  });
});
