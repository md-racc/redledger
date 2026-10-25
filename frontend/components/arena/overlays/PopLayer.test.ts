// Floating pops ("NEEDS A DECISION", "REVIEW", "BLOCKED") never paint over the title lettering.
import { describe, expect, it } from "vitest";
import { popsVisible } from "@/components/arena/overlays/PopLayer";

describe("popsVisible", () => {
  it("hides pops while the title is up", () => {
    expect(popsVisible("loading", 0)).toBe(false);
    expect(popsVisible("intro", 0)).toBe(false);
    expect(popsVisible("scroll", 0.05)).toBe(false); // the title is still sliding off
  });
  it("shows them once the title is gone, and always in the arena", () => {
    expect(popsVisible("scroll", 0.4)).toBe(true);
    expect(popsVisible("arena", 0)).toBe(true);
    expect(popsVisible("arena", 1)).toBe(true);
  });
});
