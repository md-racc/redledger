import { describe, expect, it } from "vitest";
import { provenance } from "./provenance";
import type { Backend } from "./useFeed";

const live = (agents: Backend["agents"]): Backend => ({ state: "live", agents, keyless: false });
const OFF: Backend = { state: "offline", agents: null, keyless: false };

describe("provenance", () => {
  it("calls a running battlefield LIVE and says which agents are real", () => {
    const p = provenance({ backend: live({ red: { ok: true, dry_run: false, model: "gpt-5.4-mini" }, green: { ok: true, dry_run: true }, blue: { ok: true, dry_run: true } }), source: "live", inShow: false, episodeId: "ep_1" });
    expect(p.badge).toBe("LIVE");
    expect(p.agentsLine).toBe("red live (gpt-5.4-mini) · green keyless · blue keyless");
    expect(p.episode).toBe("ep_1");
  });

  it("calls a played-back recording RECORDED, and says nothing about agents it cannot see", () => {
    const p = provenance({ backend: OFF, source: "mock", inShow: false, episodeId: "sample" });
    expect(p.badge).toBe("RECORDED");
    expect(p.agentsLine).toBe("red unknown · green unknown · blue unknown");
  });

  it("calls the show SHOW, and a backend replay REPLAY", () => {
    expect(provenance({ backend: OFF, source: "mock", inShow: true, episodeId: null }).badge).toBe("SHOW");
    const live = provenance({ backend: { state: "live", agents: null, keyless: true }, source: "live", inShow: true, episodeId: "ep_2" });
    expect(live.badge).toBe("SHOW");
    expect(live.meaning).toMatch(/live episodes/);
    expect(provenance({ backend: OFF, source: "live", inShow: false, episodeId: "replay_demo" }).badge).toBe("REPLAY");
  });

  it("is IDLE before anything runs, and reports a down agent as down", () => {
    expect(provenance({ backend: OFF, source: "idle", inShow: false, episodeId: null }).badge).toBe("IDLE");
    const p = provenance({ backend: live({ red: { ok: false }, green: { ok: true, dry_run: true }, blue: { ok: true, dry_run: true } }), source: "live", inShow: false, episodeId: "e" });
    expect(p.agents[0]).toEqual({ name: "red", mode: "down" });
  });

  it("does not name a model for a keyless agent", () => {
    const p = provenance({ backend: live({ red: { ok: true, dry_run: true, model: "gpt-5.4-mini" }, green: { ok: true, dry_run: true }, blue: { ok: true, dry_run: true } }), source: "live", inShow: false, episodeId: "e" });
    expect(p.agents[0]).toEqual({ name: "red", mode: "keyless" });
  });
});
