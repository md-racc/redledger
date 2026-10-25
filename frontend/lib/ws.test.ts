// lib/ws.ts: malformed frames are dropped; a ticket refused for a reason waiting won't fix is retried slowly and then given up; a
// socket that will not open (refused upgrade, silent handshake, flaky ticket) is worked around by reading /events over REST.
// Fake socket, fake fetch, fake clock.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { connect, type FeedLink } from "./ws";
import type { RLEvent } from "./types";

class FakeSocket {
  static all: FakeSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((m: { data: string }) => void) | null = null;
  onclose: ((e: { code: number }) => void) | null = null;
  closed = false;
  constructor(readonly url: string) { FakeSocket.all.push(this); }
  send(frame: object) { this.onmessage?.({ data: JSON.stringify(frame) }); }
  drop(code = 1006) { this.onclose?.({ code }); }
  close() { this.closed = true; }
}

const ev = (id: number): RLEvent => ({ id, type: "day.started", episode_id: "ep_1", ts: "2026-10-25T00:00:00Z" } as unknown as RLEvent);
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

let eventsCalls: string[];
let ticketCalls: number;
let eventsReply: () => Response;
let ticketReply: () => Response;

beforeEach(() => {
  vi.useFakeTimers();
  vi.spyOn(Math, "random").mockReturnValue(0.5); // backoff factor 1.0
  vi.spyOn(console, "warn").mockImplementation(() => {});
  FakeSocket.all = [];
  eventsCalls = [];
  ticketCalls = 0;
  eventsReply = () => json([]);
  ticketReply = () => json({ ticket: "t", ws_url: "ws://example.test" });
  vi.stubGlobal("WebSocket", FakeSocket);
  vi.stubGlobal("sessionStorage", { getItem: () => null, setItem: () => {} });
  vi.stubGlobal("fetch", async (url: string) => {
    if (url.startsWith("/api/bf/ws-ticket")) { ticketCalls++; return ticketReply(); }
    if (url.startsWith("/api/bf/events")) { eventsCalls.push(url); return eventsReply(); }
    throw new Error(`unexpected ${url}`);
  });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const settle = () => vi.advanceTimersByTimeAsync(0);
const run = (ms: number) => vi.advanceTimersByTimeAsync(ms);

function start() {
  const got: RLEvent[] = [];
  const links: FeedLink[] = [];
  const stop = connect("ep_1", (e) => got.push(e), 0, (l) => links.push(l));
  return { got, links, stop };
}

describe("connect", () => {
  it("uses the socket when it opens and never reads over REST", async () => {
    const { got, links, stop } = start();
    await settle();
    expect(FakeSocket.all[0]!.url).toBe("ws://example.test/api/ws?episode_id=ep_1&ticket=t&after_id=0");
    FakeSocket.all[0]!.send(ev(1));
    FakeSocket.all[0]!.send({ type: "ping" });
    await run(10_000);
    expect(got.map((e) => e.id)).toEqual([1]);
    expect(links.at(-1)!.via).toBe("socket");
    expect(eventsCalls).toHaveLength(0);
    stop();
  });

  it("drops a malformed frame and keeps delivering the next ones", async () => {
    const { got, stop } = start();
    await settle();
    const sock = FakeSocket.all[0]!;
    expect(() => sock.onmessage!({ data: "{not json" })).not.toThrow();
    sock.send({ type: "ping" });
    sock.send({ id: 7, type: "day.started" });
    expect(got).toEqual([{ id: 7, type: "day.started" }]);
    stop();
  });

  it("reads the events over REST after two sockets in a row that never delivered, and says why", async () => {
    eventsReply = () => json([ev(1), ev(2), ev(3)]);
    const { got, links, stop } = start();
    await settle();
    FakeSocket.all[0]!.drop(1006);
    expect(eventsCalls).toHaveLength(0); // one failure is not enough
    await run(1000);
    FakeSocket.all[1]!.drop(1006);
    await settle();
    expect(eventsCalls[0]).toBe("/api/bf/events?episode_id=ep_1&after_id=0&limit=500");
    expect(got.map((e) => e.id)).toEqual([1, 2, 3]);
    const l = links.at(-1)!;
    expect(l.via).toBe("polling");
    expect(l.detail).toMatch(/socket closed before any frame, code 1006/);
    stop();
  });

  it("asks only for what is new, and never hands the same event twice", async () => {
    let calls = 0;
    eventsReply = () => json(++calls === 1 ? [ev(1), ev(2)] : [ev(2), ev(3)]);
    const { got, stop } = start();
    await settle();
    FakeSocket.all[0]!.drop();
    await run(1000);
    FakeSocket.all[1]!.drop();
    await settle();
    await run(1500);
    expect(eventsCalls[1]).toContain("after_id=2");
    expect(got.map((e) => e.id)).toEqual([1, 2, 3]);
    stop();
  });

  it("gives up on a handshake nobody answers, and reads over REST after the second", async () => {
    eventsReply = () => json([ev(1), ev(2)]);
    const { got, links, stop } = start();
    await settle(); // socket 1 is created and never opens or closes
    expect(FakeSocket.all).toHaveLength(1);
    await run(7999);
    expect(eventsCalls).toHaveLength(0);
    await run(1); // 8 s: socket 1 is abandoned
    expect(FakeSocket.all[0]!.closed).toBe(true);
    await run(1000); // backoff, then socket 2 (also silent)
    expect(FakeSocket.all).toHaveLength(2);
    await run(8000);
    expect(got.map((e) => e.id)).toEqual([1, 2]);
    expect(links.at(-1)!.via).toBe("polling");
    expect(links.at(-1)!.detail).toMatch(/no answer to the websocket handshake in 8s/);
    stop();
  });

  it("does not give up on a socket that opened, even when the episode has nothing to say", async () => {
    const { links, stop } = start();
    await settle();
    FakeSocket.all[0]!.onopen?.();
    await run(60_000);
    expect(FakeSocket.all).toHaveLength(1);
    expect(FakeSocket.all[0]!.closed).toBe(false);
    expect(links.at(-1)!.via).toBe("socket");
    expect(eventsCalls).toHaveLength(0);
    stop();
  });

  it("falls back when the ticket route is rate limited", async () => {
    ticketReply = () => json({ error: "rate limited" }, 429);
    eventsReply = () => json([ev(1)]);
    const { got, links, stop } = start();
    await settle();
    await run(1000);
    expect(FakeSocket.all).toHaveLength(0);
    expect(got.map((e) => e.id)).toEqual([1]);
    expect(links.at(-1)!.detail).toMatch(/ws-ticket → 429/);
    stop();
  });

  it("keeps retrying a ticket that fails for a reason waiting can fix (rate limit, 5xx)", async () => {
    ticketReply = () => json({}, 429);
    const { stop } = start();
    for (let i = 0; i < 10; i++) await run(20_000);
    expect(ticketCalls).toBeGreaterThan(5);
    stop();
  });

  it("gives up after five refused tickets instead of asking forever, and does not read over REST either", async () => {
    ticketReply = () => json({}, 404);
    const { links, stop } = start();
    for (let i = 0; i < 10; i++) await run(20_000);
    expect(ticketCalls).toBe(5);
    expect(FakeSocket.all).toHaveLength(0);
    expect(eventsCalls).toHaveLength(0); // REST would be refused for the same reason
    expect(links.at(-1)!.via).toBe("down");
    expect(links.at(-1)!.detail).toMatch(/ws-ticket → 404, 5 times in a row: gave up/);
    stop();
  });

  it("stops reading over REST the moment a socket delivers", async () => {
    eventsReply = () => json([ev(1)]);
    const { got, links, stop } = start();
    await settle();
    FakeSocket.all[0]!.drop();
    await run(1000);
    FakeSocket.all[1]!.drop();
    await settle();
    const before = eventsCalls.length;
    await run(2000); // third socket attempt opens
    FakeSocket.all[2]!.send(ev(2));
    expect(links.at(-1)!.via).toBe("socket");
    await run(10_000);
    expect(eventsCalls.length).toBe(before + 1); // at most the one poll already in flight
    expect(got.map((e) => e.id)).toEqual([1, 2]);
    stop();
  });

  it("says it has no way in when neither the socket nor the REST read works", async () => {
    ticketReply = () => json({ error: "nope" }, 502);
    eventsReply = () => json({ error: "nope" }, 502);
    const { got, links, stop } = start();
    await settle();
    await run(1000);
    expect(got).toHaveLength(0);
    expect(links.at(-1)!.via).toBe("down");
    expect(links.at(-1)!.detail).toMatch(/events → 502/);
    stop();
  });

  it("stops everything when closed", async () => {
    eventsReply = () => json([ev(1)]);
    const { stop } = start();
    await settle();
    FakeSocket.all[0]!.drop();
    await run(1000);
    FakeSocket.all[1]!.drop();
    await settle();
    stop();
    const n = eventsCalls.length;
    await run(30_000);
    expect(eventsCalls.length).toBe(n);
  });
});
