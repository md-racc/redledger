import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../api";
import { currentEpisodeOfLineage, currentRun, isUnreachable, lineageIsLive, parseActiveRun, readRun, runningEpisode, shouldJoin, type JoinState } from "./activeRun";

const body = (o: unknown) => JSON.stringify(o);

/** A battlefield as the windows see it: reads, plus the writes a viewer must never reach (spied, so a test can prove they weren't). */
function fakeBackend(o: { episodes?: unknown[]; lineages?: unknown[]; lineage?: Record<string, unknown>; fail?: unknown } = {}) {
  const read = <T,>(v: T) => vi.fn(async () => { if (o.fail) throw o.fail; return v; });
  return {
    listEpisodes: read((o.episodes ?? []) as any[]),
    lineages: read((o.lineages ?? []) as any[]),
    lineage: vi.fn(async (id: string) => { if (o.fail) throw o.fail; return (o.lineage ?? {})[id] as any; }),
    createEpisode: vi.fn(async () => ({ id: "ep_new" })),
    start: vi.fn(async () => {}),
    step: vi.fn(async () => {}),
  };
}

describe("another run is active", () => {
  it("reads battlefield's 409 and names the run to watch", () => {
    const e = new ApiError("POST", "/episodes/ep_new/start", 409, body({ error: "another run is active", episode_id: "ep_busy", lineage_id: null }));
    expect(parseActiveRun(e)).toEqual({ episodeId: "ep_busy", lineageId: null });
    const l = new ApiError("POST", "/episodes/ep_new/step", 409, body({ error: "another run is active", episode_id: null, lineage_id: "ln_7" }));
    expect(parseActiveRun(l)).toEqual({ episodeId: null, lineageId: "ln_7" });
  });

  it("is not fooled by other errors", () => {
    expect(parseActiveRun(new ApiError("POST", "/x", 409, body({ error: "no active turn for this agent" })))).toBeNull();
    expect(parseActiveRun(new ApiError("POST", "/x", 409, body({ detail: "episode is running; pause first" })))).toBeNull();
    expect(parseActiveRun(new ApiError("POST", "/x", 500, body({ error: "another run is active" })))).toBeNull();
    expect(parseActiveRun(new ApiError("POST", "/x", 409, "not json"))).toBeNull();
    expect(parseActiveRun(new TypeError("Failed to fetch"))).toBeNull();
    expect(parseActiveRun(null)).toBeNull();
  });

  it("keeps the message the old callers read", () => {
    expect(new ApiError("POST", "/episodes/e/start", 409, "x").message).toBe("POST /episodes/e/start → 409: x");
  });
});

describe("which episode a lineage is on", () => {
  const gens = [
    { generation: 1, episode_id: "ep_g1", status: "finished" },
    { generation: 2, episode_id: "ep_g2", status: "running" },
    { generation: 3, episode_id: null, status: "created" },
  ];

  it("watches the generation that is running", () => {
    expect(currentEpisodeOfLineage({ status: "running", current_generation: 2, generations: gens })).toBe("ep_g2");
  });

  it("falls back to the current generation, then the latest one with an episode", () => {
    const idle = gens.map((g) => ({ ...g, status: g.generation === 2 ? "paused" : g.status }));
    expect(currentEpisodeOfLineage({ current_generation: 1, generations: idle })).toBe("ep_g1");
    expect(currentEpisodeOfLineage({ current_generation: 9, generations: idle })).toBe("ep_g2");
    expect(currentEpisodeOfLineage({ generations: [] })).toBeNull();
    expect(currentEpisodeOfLineage(null)).toBeNull();
  });

  it("knows when there is nothing left to follow", () => {
    expect(lineageIsLive({ status: "running" })).toBe(true);
    for (const status of ["finished", "failed", "paused", "created"]) expect(lineageIsLive({ status })).toBe(false);
  });
});

describe("every window joins the current run on load", () => {
  it("finds the running episode, never a replay, and only reads", async () => {
    const bf = fakeBackend({ episodes: [{ id: "replay_x", status: "running" }, { id: "ep_9", status: "running", lineage_id: null }, { id: "ep_8", status: "finished" }] });
    expect(await currentRun(bf)).toEqual({ episodeId: "ep_9", lineageId: null });
    expect(runningEpisode([{ id: "replay_1", status: "running" }])).toBeNull();
    expect(bf.createEpisode).not.toHaveBeenCalled();
    expect(bf.start).not.toHaveBeenCalled();
  });

  it("between two generations, follows the running lineage to its current generation", async () => {
    const bf = fakeBackend({
      episodes: [{ id: "ep_g1", status: "finished", lineage_id: "ln_1" }],
      lineages: [{ id: "ln_0", status: "finished" }, { id: "ln_1", status: "running" }],
      lineage: { ln_1: { status: "running", current_generation: 2, generations: [{ generation: 1, episode_id: "ep_g1", status: "finished" }, { generation: 2, episode_id: "ep_g2", status: "created" }] } },
    });
    expect(await currentRun(bf)).toEqual({ episodeId: "ep_g2", lineageId: "ln_1" });
  });

  it("no active run is an answer: idle, nothing created, no recording", async () => {
    const bf = fakeBackend({ episodes: [{ id: "ep_1", status: "finished" }], lineages: [{ id: "ln_1", status: "finished" }] });
    expect(await currentRun(bf)).toBeNull();
    expect(await readRun(bf)).toEqual({ link: "idle", run: null });
    expect(bf.createEpisode).not.toHaveBeenCalled();
  });

  it("only an unreachable backend is offline; a 429 or 403 is a hiccup", async () => {
    expect(await readRun(fakeBackend({ fail: new TypeError("Failed to fetch") }))).toEqual({ link: "offline", run: null });
    expect(await readRun(fakeBackend({ fail: new ApiError("GET", "/episodes", 502, body({ error: "battlefield proxy is not configured" })) }))).toEqual({ link: "offline", run: null });
    expect(await readRun(fakeBackend({ fail: new ApiError("GET", "/episodes", 429, body({ error: "rate limited" })) }))).toBeNull();
    expect(await readRun(fakeBackend({ fail: new ApiError("GET", "/episodes", 403, body({ error: "forbidden" })) }))).toBeNull();
  });

  it("falls back to the recording only when the backend is really gone", () => {
    expect(isUnreachable(new TypeError("Failed to fetch"))).toBe(true);
    expect(isUnreachable(Object.assign(new Error("t"), { name: "TimeoutError" }))).toBe(true);
    for (const s of [500, 502, 503, 504]) expect(isUnreachable(new ApiError("POST", "/episodes", s, "")), String(s)).toBe(true);
    expect(isUnreachable(new ApiError("POST", "/episodes/e/start", 409, body({ error: "another run is active", episode_id: "ep_1", lineage_id: null })))).toBe(false);
    expect(isUnreachable(new ApiError("POST", "/episodes", 403, body({ error: "viewer" })))).toBe(false);
    expect(isUnreachable(new ApiError("GET", "/episodes", 429, ""))).toBe(false);
    expect(isUnreachable(null)).toBe(false);
  });

  describe("when a window switches to the run that is going", () => {
    const idle: JoinState = { liveKind: null, episodeId: null, finished: false, playingLocal: false, follow: true };
    const run = { episodeId: "ep_live", lineageId: null };

    it("joins from idle, and moves to a new run or a lineage's next generation", () => {
      expect(shouldJoin(run, idle)).toBe(true);
      expect(shouldJoin(run, { ...idle, liveKind: "attached", episodeId: "ep_old" })).toBe(true);
      expect(shouldJoin(run, { ...idle, liveKind: "attached", episodeId: "ep_live" })).toBe(false);
    });

    it("stays put with nothing running, while the show plays, or over the recording", () => {
      expect(shouldJoin(null, idle)).toBe(false);
      expect(shouldJoin(run, { ...idle, follow: false })).toBe(false);
      expect(shouldJoin(run, { ...idle, playingLocal: true })).toBe(false);
    });

    it("leaves an admin's own run, act or sandbox alone until it has finished", () => {
      for (const liveKind of ["run", "act", "sandbox"] as const) {
        expect(shouldJoin(run, { ...idle, liveKind, episodeId: "ep_mine" }), liveKind).toBe(false);
        expect(shouldJoin(run, { ...idle, liveKind, episodeId: "ep_mine", finished: true }), liveKind).toBe(true);
      }
    });
  });
});
