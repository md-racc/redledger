// The HUD's status line between runs: honest about the backend, and pointing at the last finished run.
import { describe, expect, it } from "vitest";
import { newestEnded, newestIsPaused, parseScore, runStatus, type RunStatusInput } from "./useActiveRun";

const base: RunStatusInput = { mock: false, note: "checking the backend…", backend: "checking", link: "checking", onScreen: false, paused: false };

describe("runStatus (the idle label)", () => {
  it("says 'Between runs', not 'backend offline', when the backend answers and nothing runs", () => {
    const s = runStatus({ ...base, backend: "live", link: "idle", note: "backend live" });
    expect(s).toMatchObject({ badge: "BETWEEN RUNS", reachable: true, between: true });
    expect(s.note).toMatch(/^Between runs/);
  });

  it("trusts the run poll over a health probe that timed out", () => {
    const s = runStatus({ ...base, backend: "offline", link: "idle", note: "backend offline · recorded run" });
    expect(s.badge).toBe("BETWEEN RUNS");
    expect(s.note).not.toMatch(/offline/);
    expect(s.reachable).toBe(true);
  });

  it("says 'Paused' when the newest run is paused", () => {
    const s = runStatus({ ...base, backend: "live", link: "idle", paused: true });
    expect(s.badge).toBe("PAUSED");
    expect(s.note).toMatch(/^Paused/);
  });

  it("keeps 'backend offline' for a real failure to reach the backend", () => {
    for (const link of ["offline", "checking"] as const) {
      const s = runStatus({ ...base, backend: "offline", link, note: "backend offline · recorded run" });
      expect(s).toMatchObject({ badge: null, reachable: false, between: false, note: "backend offline · recorded run" });
    }
  });

  it("leaves the feed's note alone while something is on screen, and in mock mode", () => {
    expect(runStatus({ ...base, backend: "live", link: "idle", onScreen: true, note: "live · ep_1" })).toMatchObject({ badge: null, note: "live · ep_1", between: false });
    expect(runStatus({ ...base, mock: true, note: "mock mode · recorded episode" })).toMatchObject({ badge: null, note: "mock mode · recorded episode", reachable: false });
  });

  it("never says offline while a run is going and the screen is about to join it", () => {
    const s = runStatus({ ...base, backend: "offline", link: "live", note: "backend offline · recorded run" });
    expect(s.badge).toBeNull();
    expect(s.note).not.toMatch(/offline/);
  });
});

describe("the last finished run", () => {
  const list = [
    { id: "replay_x", status: "finished" },
    { id: "ep_new", status: "created" },
    { id: "ep_3", status: "finished" },
    { id: "ep_2", status: "paused" },
    { id: "ep_1", status: "finished" },
  ];

  it("is the newest real episode that ended (GET /episodes is newest first; replays and unstarted ones skipped)", () => {
    expect(newestEnded(list)).toEqual({ episodeId: "ep_3", status: "finished" });
    expect(newestEnded([{ id: "ep_9", status: "failed" }])).toEqual({ episodeId: "ep_9", status: "failed" });
    expect(newestEnded([{ id: "ep_9", status: "running" }])).toBeNull();
    expect(newestEnded(null)).toBeNull();
  });

  it("counts as paused only when the newest started run is paused", () => {
    expect(newestIsPaused(list)).toBe(false);
    expect(newestIsPaused([{ id: "ep_2", status: "paused" }, { id: "ep_1", status: "finished" }])).toBe(true);
  });

  it("reads the score answer, and refuses something that is not one", () => {
    expect(parseScore({ dollars_extracted: 1200, dollars_blocked: 9000, false_positive_cost: 50, attacks_launched: 4, attacks_caught: 3 })).toMatchObject({ dollars_extracted: 1200, attacks_caught: 3, legit_blocked: 0, detection_latency_days: null });
    expect(parseScore({ error: "nope" })).toBeNull();
    expect(parseScore(null)).toBeNull();
  });
});
