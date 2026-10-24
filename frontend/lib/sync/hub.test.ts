import { describe, expect, it } from "vitest";
import { clean, Hub, hub, liveClients } from "./hub";

describe("sync hub", () => {
  it("keeps what the arena selected and did, in order, and tells subscribers as it happens", () => {
    const h = new Hub();
    const seen: string[] = [];
    h.subscribe((i) => seen.push(`${i.type}:${i.seq}`));
    h.publish({ client: "arena-1", kind: "select", data: { id: "red:ghost_vendor", name: "Ghost Vendor", team: "red" } });
    h.publish({ client: "arena-1", kind: "controller", data: { mode: "enforce" } });
    h.publish({ client: "arena-1", kind: "show", data: { status: "playing", beat: "on" } });
    h.publish({ client: "arena-1", kind: "panel", data: { panel: "compare" } });
    expect(h.state.selected).toEqual({ id: "red:ghost_vendor", name: "Ghost Vendor", team: "red" });
    expect(h.state.controller).toBe("enforce");
    expect(h.state.show).toEqual({ status: "playing", beat: "on" });
    expect(h.state.panel).toBe("compare");
    expect(seen).toEqual(["msg:1", "msg:2", "msg:3", "msg:4"]);
    h.publish({ client: "arena-1", kind: "select", data: { id: null } });
    expect(h.state.selected).toBeNull();
  });

  it("hands a late reader only what is newer than it has, messages and API calls interleaved on one counter", () => {
    const h = new Hub();
    h.publish({ client: "a", kind: "hello", data: { role: "arena" } });
    h.recordTraffic({ method: "POST", path: "/episodes", status: 201, ms: 143.6, client: "a" });
    h.publish({ client: "a", kind: "launch", data: { scheme: "ghost_vendor" } });
    const snap = h.snapshot(1);
    expect(snap.seq).toBe(3);
    expect(snap.msgs.map((m) => m.kind)).toEqual(["launch"]);
    expect(snap.traffic).toEqual([expect.objectContaining({ method: "POST", path: "/episodes", status: 201, ms: 144, seq: 2 })]);
    expect(h.snapshot(0).msgs).toHaveLength(2);
  });

  it("drops what it does not understand and bounds what it keeps", () => {
    expect(clean(null)).toBeNull();
    expect(clean({ client: "a", kind: "explode", data: {} })).toBeNull();
    expect(clean({ kind: "select", data: {} })).toBeNull();
    const c = clean({ client: "ar<script>ena", kind: "select", data: { id: "x".repeat(1000), nested: { a: 1 }, n: 3, ok: true, bad: Infinity } })!;
    expect(c.client).toBe("arscriptena");
    expect((c.data.id as string).length).toBeLessThanOrEqual(160);
    expect(c.data).not.toHaveProperty("nested");
    expect(c.data).not.toHaveProperty("bad");
    expect(c.data.n).toBe(3);
    const h = new Hub();
    for (let i = 0; i < 400; i++) h.publish({ client: "a", kind: "select", data: { id: `r${i}` } });
    expect(h.msgs).toHaveLength(300);
    expect(h.msgs[0].seq).toBe(101);
  });

  it("knows who is on the stage: clients that spoke recently", () => {
    const h = new Hub();
    const t0 = new Date("2026-10-24T12:00:00Z");
    h.publish({ client: "arena-1", kind: "hello", data: { role: "arena" } }, t0);
    h.publish({ client: "red-1", kind: "hello", data: { role: "backstage:red" } }, new Date(t0.getTime() + 20_000));
    const live = liveClients(h.state, t0.getTime() + 40_000);
    expect(live.map((c) => c.id)).toEqual(["red-1"]); // the arena has been quiet for 40 s
    expect(liveClients(h.state, t0.getTime() + 25_000).map((c) => c.role).sort()).toEqual(["arena", "backstage:red"]);
  });

  it("is one hub per process however it is reached", () => {
    expect(hub()).toBe(hub());
  });
});
