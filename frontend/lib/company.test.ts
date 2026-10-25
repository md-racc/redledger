import { describe, expect, it } from "vitest";
import { COMPANY, companyName } from "./company";

describe("the synthetic company", () => {
  it("is Meridian Components unless a snapshot names it", () => {
    expect(COMPANY.name).toBe("Meridian Components");
    expect(companyName()).toBe(COMPANY.name);
    expect(companyName(null)).toBe(COMPANY.name);
    expect(companyName({ company: { name: "  " } })).toBe(COMPANY.name);
    expect(companyName({ company: { name: "Renamed Ltd" } })).toBe("Renamed Ltd");
  });
});
