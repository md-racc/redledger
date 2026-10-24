import { describe, expect, it } from "vitest";
import { initialState, reduce } from "./reducer";
import type { RLEvent } from "./types";

const ev = (id: number, type: string, payload: any, day = 0, agent: any = "battlefield"): RLEvent => ({ id, ts: "2026-01-01T00:00:00Z", episode_id: "ep", day, type, agent, payload });

describe("reducer", () => {
  it("tracks attacks and outcomes", () => {
    let s = initialState();
    s = reduce(s, ev(1, "episode.started", { controller_mode: "enforce", days: 3, seed: 1 }));
    s = reduce(s, ev(2, "attack.launched", { attack_id: "a1", scheme_id: "ghost_vendor", display_name: "Ghost Vendor", story: "x", target_amount: 4920 }, 1));
    s = reduce(s, ev(3, "attack.outcome", { attack_id: "a1", outcome: "blocked", amount_extracted: 0 }, 1));
    expect(s.attacks.a1.outcome).toBe("blocked");
    expect(s.controllerMode).toBe("enforce");
  });
  it("is idempotent on replayed ids", () => {
    let s = initialState();
    const e = ev(5, "flag.raised", { flag_id: "f", entity_type: "vendor", entity_id: "v", severity: "high", reason: "r" }, 2, "blue");
    s = reduce(reduce(s, e), e);
    expect(s.flags.length).toBe(1);
  });
});
