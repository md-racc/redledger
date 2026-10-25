import { describe, expect, it } from "vitest";
import { EXAMPLES } from "./examples";
import { closestScheme } from "./intent";

describe("try-saying examples", () => {
  it.each(EXAMPLES.map((e) => [e.label, e.text, e.scheme] as const))("%s: the console picks the scheme the chip promises", (_label, text, scheme) => {
    const g = closestScheme(text);
    expect(g.scheme).toBe(scheme);
    expect(g.confident).toBe(true);
  });

  it("fit in the box (500 characters) and cover more than one language", () => {
    for (const e of EXAMPLES) expect(e.text.length).toBeLessThanOrEqual(500);
    expect(new Set(EXAMPLES.map((e) => e.label)).size).toBe(EXAMPLES.length);
    expect(EXAMPLES.length).toBeGreaterThanOrEqual(3);
  });
});
