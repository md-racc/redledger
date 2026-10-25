import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import type { RLEvent } from "../types";
import { buildPitchFallback, PITCH_DAYS, PITCH_FALLBACK, pitchEpisode, pitchQuery, pitchStatus, planPitch } from "./pitch";
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
