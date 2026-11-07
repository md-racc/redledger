import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import type { RLEvent } from "../types";
import { buildPitchFallback, canApprove, PITCH_DAYS, PITCH_FALLBACK, PITCH_TOUR, PITCH_TOUR_MS, pitchEpisode, pitchQuery, pitchStatus, planPitch, tourPosition, tourTimeAt, willAutoBlock } from "./pitch";
import { CHAPTERS } from "./timeline";
import { claimIntroLen, INTRO_SECONDS, releaseIntroLen, SHOW_INTRO_SECONDS, timeline } from "./timeline";
import { ScriptRunner } from "./script";

const read = (p: string) => readFileSync(p, "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l) as RLEvent);
const fallback = read(join(__dirname, "../../public/mocks/pitch-fallback.jsonl"));

describe("pitch mode: entry", () => {
  it("starts on ?pitch=1, with seed 42 unless ?seed= says otherwise", () => {
    expect(pitchQuery("?pitch=1")).toEqual({ on: true, seed: 42 });
    expect(pitchQuery("?pitch=1&seed=7")).toEqual({ on: true, seed: 7 });
    expect(pitchQuery("?seed=abc").seed).toBe(42);
    expect(pitchQuery("?seed=-3").seed).toBe(42);
    expect(pitchQuery("").on).toBe(false);
    expect(pitchQuery("?pitch=0").on).toBe(false);
  });
});

describe("pitch mode: the tour", () => {
  const [palace, guards, clients, fraudsters, arena] = PITCH_TOUR;

  it("takes 38.5 s from the Palace to the arena, the length of the first three lines of the live script", () => {
    expect(PITCH_TOUR_MS).toBe(38_500);
    expect(PITCH_TOUR.map((s) => s.at)).toEqual(CHAPTERS.map((c) => c.at));
  });

  it("dwells where the presenter speaks (Palace, guards, fraudsters) and passes the clients", () => {
    expect(palace!.holdMs).toBeGreaterThanOrEqual(8000);
    expect(guards!.holdMs).toBeGreaterThanOrEqual(8000);
    expect(fraudsters!.holdMs).toBeGreaterThanOrEqual(8000);
    expect(clients!.holdMs).toBeLessThanOrEqual(1000);
    expect(clients!.travelMs).toBeLessThanOrEqual(3000);
    expect(arena!.holdMs).toBe(0);
  });

  it("stands still at a stop for the whole hold, and is there when it arrives", () => {
    expect(tourPosition(0)).toBe(0);
    expect(tourPosition(7999)).toBe(0); // still at the Palace
    const arrive = palace!.holdMs + guards!.travelMs;
    expect(tourPosition(arrive)).toBeCloseTo(guards!.at, 6);
    expect(tourPosition(arrive + guards!.holdMs - 1)).toBeCloseTo(guards!.at, 6); // still at the guards, nine seconds on
    expect(tourPosition(PITCH_TOUR_MS)).toBe(1);
    expect(tourPosition(PITCH_TOUR_MS + 99_000)).toBe(1);
  });

  it("only ever moves forward, and eases in and out of each leg", () => {
    let last = -1;
    for (let ms = 0; ms <= PITCH_TOUR_MS; ms += 25) {
      const p = tourPosition(ms);
      expect(p).toBeGreaterThanOrEqual(last);
      last = p;
    }
    // the first quarter of a leg covers less than a quarter of it
    const t0 = palace!.holdMs;
    const quarter = (tourPosition(t0 + guards!.travelMs / 4) - palace!.at) / (guards!.at - palace!.at);
    expect(quarter).toBeLessThan(0.25);
  });

  it("starts partway when pitch mode begins partway down the page", () => {
    expect(tourTimeAt(0)).toBe(0);
    expect(tourTimeAt(guards!.at)).toBeGreaterThanOrEqual(palace!.holdMs + 2900);
    expect(tourTimeAt(guards!.at)).toBeLessThanOrEqual(palace!.holdMs + guards!.travelMs + 50);
    expect(tourTimeAt(1)).toBeGreaterThan(PITCH_TOUR_MS - 200);
  });
});

describe("pitch mode: what to run", () => {
  const run = { episodeId: "ep_1", lineageId: null };
  it("joins the run that is going, admin or viewer", () => {
    expect(planPitch({ mockOnly: false, admin: true, reach: "live", active: run })).toBe("join");
    expect(planPitch({ mockOnly: false, admin: false, reach: "live", active: run })).toBe("join");
  });
  it("lets an admin start one, and makes a viewer wait for the operator (a viewer never creates an episode)", () => {
    expect(planPitch({ mockOnly: false, admin: true, reach: "live", active: null })).toBe("create");
    expect(planPitch({ mockOnly: false, admin: false, reach: "live", active: null })).toBe("wait");
  });
  it("plays the recording only in mock mode or when the backend is unreachable", () => {
    expect(planPitch({ mockOnly: true, admin: true, reach: "live", active: null })).toBe("fallback");
    expect(planPitch({ mockOnly: false, admin: true, reach: "offline", active: null })).toBe("fallback");
    expect(planPitch({ mockOnly: false, admin: false, reach: "offline", active: null })).toBe("fallback");
  });
  it("creates an enforce episode of 4 days with no attack plan, so red picks its own schemes", () => {
    const b = pitchEpisode(42);
    expect(b).toEqual({ controller_mode: "enforce", seed: 42, days: PITCH_DAYS });
    expect("attack_plan" in b).toBe(false);
  });
  it("says what it is showing", () => {
    const ctx = { source: "live" as const, mockOnly: false, seed: 42, note: "could not start the live run · the backend said 403" };
    expect(pitchStatus("live", ctx)).toMatch(/seed 42 .* red picks its own schemes/);
    expect(pitchStatus("waiting", { ...ctx, source: "idle" })).toMatch(/Waiting for the operator/);
    expect(pitchStatus("waiting", ctx)).toMatch(/Joined/);
    expect(pitchStatus("recorded", { ...ctx, source: "mock", mockOnly: true })).toMatch(/^Mock mode: .*real run recorded on prod/);
    expect(pitchStatus("refused", ctx)).toBe(ctx.note);
    expect(pitchStatus(null, ctx)).toBeNull();
  });
});

describe("pitch mode: the recorded fallback", () => {
  it("is the real prod run, not the mock sample", () => {
    expect(fallback[0].episode_id).toBe(PITCH_FALLBACK.episodeId);
    expect(fallback[0].ts.startsWith(PITCH_FALLBACK.date)).toBe(true);
    expect(fallback.some((e) => (e.payload as { summary?: string }).summary?.startsWith("[mock]"))).toBe(false);
    expect(JSON.stringify(fallback)).not.toMatch(/"(entity_)?origin"/);
  });

  const play = (decide?: (id: string) => "approve" | "block") => {
    const out: RLEvent[] = [];
    const pending: string[] = [];
    const items = buildPitchFallback(fallback, 10_000, 5_000);
    const r: ScriptRunner = new ScriptRunner(items, (e) => {
      out.push(e);
      // a human (or the auto-block) answers the card a moment after it opens
      if (decide && e.type === "escalation.opened") {
        const id = (e.payload as { escalation_id: string }).escalation_id;
        pending.push(id);
      }
    });
    let held = 0;
    for (let i = 0; i < 20_000 && !r.done; i++) {
      r.advance(50);
      if (r.holding) held += 50;
      if (decide && pending.length) {
        const id = pending.shift()!;
        r.ctx.decisions[id] = decide(id);
        out.push({ id: -1, ts: "", episode_id: PITCH_FALLBACK.episodeId, day: 0, type: "escalation.resolved", agent: "human", payload: { escalation_id: id, decision: r.ctx.decisions[id], by: "judge" } });
      }
    }
    return { out, held, done: r.done };
  };

  it("plays every recorded event in order, ending with the recorded final score", () => {
    const { out, done } = play(() => "block");
    expect(done).toBe(true);
    const recorded = out.filter((e) => e.id > 0);
    expect(recorded.map((e) => e.id)).toEqual(fallback.filter((e) => e.type !== "escalation.resolved").map((e) => e.id));
    expect((out[out.length - 1].payload as { final_score: unknown }).final_score).toEqual((fallback[fallback.length - 1].payload as { final_score: unknown }).final_score);
  });

  it("holds each escalation for a human with a fresh countdown, then drops the recording's 90 s timeout", () => {
    const before = Date.now();
    const { out } = play(() => "approve");
    const opened = out.filter((e) => e.type === "escalation.opened");
    expect(opened).toHaveLength(2);
    for (const o of opened) expect(new Date((o.payload as { expires_at: string }).expires_at).getTime()).toBeGreaterThan(before);
    const resolved = out.filter((e) => e.type === "escalation.resolved");
    expect(resolved).toHaveLength(2);
    expect(resolved.every((e) => (e.payload as { decision: string }).decision === "approve")).toBe(true);
  });

  it("blocks an escalation nobody answers once its hold runs out", () => {
    const { out, held } = play();
    const resolved = out.filter((e) => e.type === "escalation.resolved");
    expect(resolved.map((e) => (e.payload as { decision: string; by: string }))).toEqual([{ escalation_id: expect.any(String), decision: "block", by: "auto-block" }, { escalation_id: expect.any(String), decision: "block", by: "auto-block" }]);
    expect(held).toBeGreaterThanOrEqual(2 * 5_000 - 100);
  });
});

describe("pitch mode: who blocks, who may approve", () => {
  it("counts down to the auto-block only in a window that will block: an admin's, or one playing a recording itself", () => {
    expect(willAutoBlock({ mockOnly: false, admin: true, source: "live" })).toBe(true);
    expect(willAutoBlock({ mockOnly: false, admin: false, source: "live" })).toBe(false);
    expect(willAutoBlock({ mockOnly: false, admin: false, source: "mock" })).toBe(true);
    expect(willAutoBlock({ mockOnly: true, admin: false, source: "idle" })).toBe(true);
  });
  it("offers no Approve on a recording played back (its outcomes cannot change), and does on a live run", () => {
    expect(canApprove({ recording: PITCH_FALLBACK, source: "mock" })).toBe(false);
    expect(canApprove({ recording: null, source: "mock" })).toBe(true);
    expect(canApprove({ recording: null, source: "live" })).toBe(true);
  });
});

describe("the flight's length: the show and pitch mode do not undo each other", () => {
  it("is put back only by whoever shortened it last", () => {
    claimIntroLen("pitch", SHOW_INTRO_SECONDS);
    releaseIntroLen("show"); // the show going "off" as pitch mode starts
    expect(timeline.introLen).toBe(SHOW_INTRO_SECONDS);
    claimIntroLen("show", SHOW_INTRO_SECONDS);
    releaseIntroLen("pitch"); // pitch mode stopped by the show starting
    expect(timeline.introLen).toBe(SHOW_INTRO_SECONDS);
    releaseIntroLen("show");
    expect(timeline.introLen).toBe(INTRO_SECONDS);
  });
});
