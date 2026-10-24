import { describe, expect, it } from "vitest";
import { ApiError } from "../api";
import { currentEpisodeOfLineage, lineageIsLive, parseActiveRun } from "./activeRun";

const body = (o: unknown) => JSON.stringify(o);

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
