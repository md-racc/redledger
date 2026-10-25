import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { enforceStory, schemeMix, type LiveRuns } from "./liveRuns";

const root = join(__dirname, "../../..");
const summary = JSON.parse(readFileSync(join(__dirname, "../../public/mocks/live-runs.json"), "utf8")) as LiveRuns;
const events = (f: string) => readFileSync(join(root, "docs", "recordings", f), "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l) as { type: string; payload: Record<string, any>; episode_id: string });

describe("the live-run summary", () => {
  it("matches the recordings it was made from (run `node tools/gen-live-runs.mjs` after they change)", () => {
    for (const [key, file] of [["off", "demo-off-live.jsonl"], ["enforce", "demo-enforce-live.jsonl"]] as const) {
      const ev = events(file);
      const ended = ev.find((e) => e.type === "episode.ended")!;
      const run = summary.runs[key];
      expect(run.score).toEqual(ended.payload.final_score);
      expect(run.episode_id).toBe(ev[0]!.episode_id);
      expect(run.attacks).toHaveLength(ev.filter((e) => e.type === "attack.launched").length);
      expect(run.by_day).toHaveLength(run.days);
    }
  });

  it("carries the numbers the pitch says out loud", () => {
    expect(summary.runs.off.mode).toBe("off");
    expect(summary.runs.enforce.mode).toBe("enforce");
    expect(Math.round(summary.runs.off.score.dollars_extracted)).toBe(10285);
    expect(Math.round(summary.runs.enforce.score.dollars_extracted)).toBe(1824);
    expect(summary.runs.enforce.score.false_positive_cost).toBe(100);
    expect(summary.runs.off.seed).toBe(summary.runs.enforce.seed);
    expect(summary.runs.off.days).toBe(10);
  });

  it("is numbers only: no agent text or tool-call ids", () => {
    const text = JSON.stringify(summary);
    expect(text).not.toMatch(/toolu_|call_[0-9a-f]{8}|summary"|thinking/i);
  });
});

describe("telling it", () => {
  it("tallies what red launched, most common first", () => {
    const mix = schemeMix(summary.runs.enforce);
    expect(mix[0]!.n).toBeGreaterThanOrEqual(mix[mix.length - 1]!.n);
    expect(mix.reduce((s, m) => s + m.n, 0)).toBe(summary.runs.enforce.attacks.length);
  });

  it("says in one plain paragraph how the controller-on run went", () => {
    const s = enforceStory(summary.runs.enforce);
    expect(s).toMatch(/Red launched 10 attacks/);
    expect(s).toMatch(/1 was caught/);
    expect(s).toMatch(/3 bank changes to a person; nobody answered, so each was blocked/);
  });
});
