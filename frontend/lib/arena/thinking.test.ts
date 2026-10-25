import { describe, expect, it } from "vitest";
import { initialState, reduce } from "../reducer";
import type { RLEvent } from "../types";
import { clip, thoughtsOf } from "./thinking";

const think = (id: number, agent: "red" | "blue", day: number, text: string): RLEvent => ({ id, ts: "2026-10-25T00:00:00Z", episode_id: "ep", day, type: "agent.thinking", agent, payload: { text } });

describe("an agent's thoughts", () => {
  it("joins the streamed deltas per day, newest day first, for that agent only", () => {
    let s = initialState();
    for (const e of [think(1, "red", 1, "Looking at "), think(2, "red", 1, "the books.\n"), think(3, "blue", 1, "blue thought"), think(4, "red", 3, "Day three plan")]) s = reduce(s, e);
    expect(thoughtsOf(s, "red")).toEqual([{ day: 3, text: "Day three plan" }, { day: 1, text: "Looking at the books." }]);
    expect(thoughtsOf(s, "blue")).toEqual([{ day: 1, text: "blue thought" }]);
    expect(thoughtsOf(s, "green")).toEqual([]);
  });

  it("ignores empty text and keys that are not a day", () => {
    const s = initialState();
    s.thinking = { "red:2": "   \n ", "red:x": "nope", "red:4": "ok" };
    expect(thoughtsOf(s, "red")).toEqual([{ day: 4, text: "ok" }]);
  });
});

describe("clip", () => {
  it("leaves short text alone and cuts long text at a word", () => {
    expect(clip("short", 20)).toBe("short");
    const long = "alpha beta gamma delta epsilon zeta eta theta";
    const c = clip(long, 24);
    expect(c.endsWith("…")).toBe(true);
    expect(c.length).toBeLessThanOrEqual(25);
    expect(long.startsWith(c.slice(0, -1))).toBe(true);
    expect(c).not.toMatch(/\s…$/);
  });
});
