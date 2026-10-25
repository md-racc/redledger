import { describe, expect, it } from "vitest";
import type { RLEvent } from "@/lib/types";
import { emptyState, Hub } from "@/lib/sync/hub";
import { concerns, eventLine, liveChecks, msgLine, teamEvents, trafficLine } from "./raw";

const ev = (id: number, type: string, agent: RLEvent["agent"], payload: Record<string, unknown> = {}): RLEvent => ({ id, ts: "2026-10-24T14:32:09.000Z", episode_id: "e", day: 2, type, agent, payload });

describe("raw console lines", () => {
  it("one event is one line with the raw payload on it", () => {
    const l = eventLine(ev(41, "attack.launched", "battlefield", { scheme_id: "ghost_vendor", target_amount: 4920 }));
    expect(l).toContain("#41");
    expect(l).toContain("attack.launched");
    expect(l).toContain('"scheme_id":"ghost_vendor"');
    expect(eventLine(ev(1, "x", null, { big: "y".repeat(500) }), 80).length).toBeLessThan(200);
  });

  it("traffic and relay lines carry method, path, status, time and which laptop", () => {
    const h = new Hub();
    const t = h.recordTraffic({ method: "POST", path: "/episodes/ep_1/attack", status: 202, ms: 41, client: "arena-1f3a" });
    expect(trafficLine(t)).toMatch(/POST\s+\/episodes\/ep_1\/attack\s+202\s+41ms\s+arena-1f3a/);
    const m = h.publish({ client: "arena-1f3a", kind: "select", data: { id: "red:ghost_vendor", name: "Ghost Vendor", team: "red", role: "arena" } })!;
    expect(msgLine(m)).toMatch(/select\s+id=red:ghost_vendor name=Ghost Vendor team=red/);
    expect(msgLine(m)).not.toContain("role=");
  });

  it("each team lists its own events, the battlefield lists all", () => {
    const events = [
      ev(1, "attack.launched", "battlefield", { scheme_id: "ghost_vendor" }),
      ev(2, "agent.thinking", "red", { text: "hm" }),
      ev(3, "ledger.mutation", "battlefield", { agent: "green", action: "invoices.pay" }),
      ev(4, "gate.verdict", "blue", { agent: "green", verdict: "block", rules_fired: ["near_threshold"] }),
      ev(5, "flag.raised", "battlefield", {}),
      ev(6, "day.started", "battlefield", {}),
    ];
    expect(teamEvents("red", events).map((e) => e.id)).toEqual([1, 2]);
    expect(teamEvents("green", events).map((e) => e.id)).toEqual([3, 4]);
    expect(teamEvents("blue", events).map((e) => e.id)).toEqual([4, 5]);
    expect(teamEvents("battlefield", events)).toHaveLength(6);
  });

  it("the arena's selection points at the matching lines", () => {
    expect(concerns(ev(1, "attack.launched", "battlefield", { scheme_id: "ghost_vendor" }), "red:ghost_vendor")).toBe(true);
    expect(concerns(ev(1, "attack.launched", "battlefield", { scheme_id: "bank_swap" }), "red:ghost_vendor")).toBe(false);
    expect(concerns(ev(2, "gate.verdict", "blue", { rules_fired: ["near_threshold", "vendor_age_lt_7d"] }), "blue:near_threshold")).toBe(true);
    expect(concerns(ev(2, "gate.verdict", "blue", { rules_fired: ["duplicate_amount_match"] }), "blue:near_threshold")).toBe(false);
    expect(concerns(ev(3, "x", null), null)).toBe(false);
    expect(concerns(ev(3, "x", null), "green:client_05")).toBe(false);
  });
});

describe("live checks", () => {
  const base = { mode: "live" as const, healthMs: 38, agents: { red: { ok: true }, green: { ok: true }, blue: { ok: true } }, eventsInLastMinute: 40, lastEventAt: 1_000_000 - 2000, verdicts: 12, now: 1_000_000, trafficCount: 9 };
  const sync = (link: string, withArena: boolean) => {
    const h = new Hub();
    if (withArena) h.publish({ client: "arena-1", kind: "hello", data: { role: "arena" } }, new Date(1_000_000 - 3000));
    return { link, quietMs: 3000, state: h.state };
  };

  it("passes when everything is flowing, and names each thing it measured", () => {
    const c = liveChecks({ ...base, sync: sync("stream", true) });
    expect(c.every((x) => x.ok === true)).toBe(true);
    expect(c[0].detail).toContain("38ms");
    expect(c.find((x) => x.label.includes("arena"))!.detail).toContain("arena-1");
  });

  it("fails what is not working instead of hiding it", () => {
    const c = liveChecks({ ...base, mode: "recorded", healthMs: null, lastEventAt: null, eventsInLastMinute: 0, sync: { link: "connecting", quietMs: 9000, state: emptyState() } });
    expect(c[0].ok).toBe(false);
    expect(c.find((x) => x.label.includes("event stream"))!.ok).toBe(false);
    expect(c.find((x) => x.label.includes("arena"))!.ok).toBe(false);
    expect(c.find((x) => x.label.includes("relay"))!.ok).toBe(false);
  });

  describe("the event stream", () => {
    const stream = (over: object) => liveChecks({ ...base, sync: sync("stream", true), ...over }).find((x) => x.label.includes("event stream"))!;
    const idle = { lastEventAt: 1_000_000 - 90_000, eventsInLastMinute: 0 };

    it("is not a fault when the episode is over and its history arrived", () => {
      const c = stream({ ...idle, feed: { via: "socket", detail: "websocket open" }, episodeStatus: "finished", eventsHeld: 260 });
      expect(c.ok).toBe(true);
      expect(c.detail).toMatch(/idle: episode finished, 260 events delivered/);
    });

    it("is a fault when something is running and nothing arrives", () => {
      expect(stream({ ...idle, feed: { via: "socket", detail: "websocket open" }, episodeStatus: "running", eventsHeld: 260 }).ok).toBe(false);
    });

    it("has nothing to say yet before an episode has delivered anything", () => {
      expect(stream({ lastEventAt: null, eventsInLastMinute: 0, feed: { via: "socket", detail: "websocket open" }, episodeStatus: "pending", eventsHeld: 0 }).ok).toBeNull();
      expect(stream({ lastEventAt: null, eventsInLastMinute: 0, feed: { via: "connecting", detail: "asking for a ticket" }, episodeStatus: "running", eventsHeld: 0 }).ok).toBeNull();
    });

    it("names the REST fallback when the socket will not open, and still passes while events arrive", () => {
      const c = stream({ feed: { via: "polling", detail: "x" }, episodeStatus: "running", eventsHeld: 30 });
      expect(c.ok).toBe(true);
      expect(c.detail).toMatch(/REST fallback/);
    });

    it("fails with the reason when there is no way in", () => {
      const c = stream({ ...idle, feed: { via: "down", detail: "the socket does not connect (ws-ticket → 403) and events → 403" }, episodeStatus: "finished", eventsHeld: 260 });
      expect(c.ok).toBe(false);
      expect(c.detail).toMatch(/ws-ticket → 403/);
    });
  });

  it("says what the proxy refused with instead of sitting on 'connecting'", () => {
    const c = liveChecks({ ...base, mode: "connecting", healthMs: null, lastEventAt: null, eventsInLastMinute: 0, answer: "403 forbidden", sync: sync("stream", true) });
    expect(c[0]!.ok).toBe(false);
    expect(c[0]!.detail).toMatch(/refused, not unreachable: 403 forbidden/);
    expect(liveChecks({ ...base, mode: "connecting", healthMs: null, lastEventAt: null, eventsInLastMinute: 0, sync: sync("stream", true) })[0]!.detail).toBe("connecting");
  });

  it("tells the operator how to bring the arena laptop in", () => {
    const c = liveChecks({ ...base, sync: { link: "stream", quietMs: 3000, state: emptyState() } }).find((x) => x.label.includes("arena"))!;
    expect(c.ok).toBe(false);
    expect(c.detail).toMatch(/sign in at \/admin/);
  });

  it("does not call a replay of the recorded live-red run a failure to reach the backend", () => {
    const c = liveChecks({ ...base, mode: "recorded", healthMs: null, replaying: "demo-enforce-live", sync: sync("stream", true) });
    expect(c[0]!.ok).toBeNull();
    expect(c[0]!.detail).toMatch(/replaying the recorded live-red run/);
    // while a recording with nothing named still reads as "no answer"
    const none = liveChecks({ ...base, mode: "recorded", healthMs: null, sync: sync("stream", true) });
    expect(none[0]!.ok).toBe(false);
  });

  it("shows a viewer the relay and arena checks as neutral 'admin only' lines, never FAIL", () => {
    for (const input of [{ ...base, sync: sync("admins", false) }, { ...base, viewer: true, sync: sync("connecting", false) }]) {
      const c = liveChecks(input);
      for (const label of ["relay to the other laptops", "arena laptop connected"]) {
        const x = c.find((y) => y.label === label)!;
        expect(x.ok).toBeNull();
        expect(x.adminOnly).toBe(true);
        expect(x.detail).toBe("admin only");
      }
      expect(c.some((x) => x.ok === false)).toBe(false);
    }
    // an admin's missing arena laptop is still a failure
    expect(liveChecks({ ...base, viewer: false, sync: sync("stream", false) }).find((x) => x.label === "arena laptop connected")!.ok).toBe(false);
  });
});

describe("demoPlan", () => {
  it("pins every day to a scheme that shows on screen, cycling", async () => {
    const { demoPlan, DEMO_PLAN_CYCLE } = await import("./raw");
    const p = demoPlan(30);
    expect(p).toHaveLength(30);
    expect(p[0]).toEqual({ day: 0, scheme_id: "bank_swap" });
    expect(p[6]!.scheme_id).toBe("bank_swap");
    for (const x of p) expect(DEMO_PLAN_CYCLE).toContain(x.scheme_id as (typeof DEMO_PLAN_CYCLE)[number]);
    expect(p.map((x) => x.scheme_id)).not.toContain("duplicate_invoice");
    expect(demoPlan(0)).toEqual([]);
  });
});
