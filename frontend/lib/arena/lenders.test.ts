// The lenders card says only what its sources say, and the old synthetic company's name is gone from frontend/.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { ALSO, AS_OF, AXIOS, DISCLAIMER, HEADLINE, LENDERS, TIE, type Source } from "./lenders";

const root = join(__dirname, "..", "..");
const read = (p: string) => readFileSync(join(root, p), "utf8").replace(/\r\n/g, "\n");
const allSources: Source[] = [AXIOS, ...LENDERS.flatMap((l) => l.sources), ...ALSO.map((a) => a.source)];

describe("the lenders", () => {
  it("are the five, in order", () => {
    expect(LENDERS.map((l) => l.name)).toEqual(["JPMorgan Chase", "Bank of America", "Citi", "Wells Fargo", "Morgan Stanley"]);
  });

  it("each cite a source that has an outlet, a link and a date inside the research window", () => {
    for (const l of LENDERS) expect(l.sources.length, l.name).toBeGreaterThan(0);
    for (const s of allSources) {
      expect(s.outlet, s.url).toBeTruthy();
      expect(s.url, s.outlet).toMatch(/^https:\/\/[^\s]+$/);
      expect(s.date, s.url).toMatch(/^2026-10-\d\d$/);
      expect(s.date <= AS_OF, s.url).toBe(true);
    }
  });

  it("never say a bank lost money, was attacked or was breached, which no source says", () => {
    for (const l of LENDERS) expect(`${l.chip} ${l.says} ${l.notClaimed}`, l.name).not.toMatch(/\b(lost|losses|attacked|breach(ed)?|hacked|stolen|drained)\b/i);
  });

  it("show Wells Fargo as having no statement, and Morgan Stanley as denying", () => {
    const wells = LENDERS.find((l) => l.id === "wells")!;
    expect(wells.spoken).toBe(false);
    expect(wells.chip).toMatch(/no statement/i);
    expect(wells.notClaimed).toMatch(/do not say/i);
    const ms = LENDERS.find((l) => l.id === "morgan-stanley")!;
    expect(ms.says).toMatch(/has not observed/);
    expect(ms.says).toMatch(/anonymous/);
    expect(ms.notClaimed).toMatch(/It says it has not/);
  });

  it("carry the anonymous sourcing of the report they follow, and say they are not partners", () => {
    expect(HEADLINE).toMatch(/anonymous/);
    expect(AXIOS.note).toMatch(/anonymous/);
    expect(DISCLAIMER).toMatch(/not partners, customers or sponsors/);
    expect(DISCLAIMER).toMatch(/synthetic/);
    expect(TIE).toMatch(/90 seconds/); // the escalation timeout the gate really has
  });

  it("have every source in docs/EVIDENCE.md, and the pitch names Axios and Wells Fargo's silence", () => {
    const doc = read("../docs/EVIDENCE.md");
    for (const s of allSources) expect(doc, s.url).toContain(s.url);
    for (const n of ["JPMorgan Chase", "Bank of America", "Citi", "Wells Fargo", "Morgan Stanley", "Axios"]) expect(doc, n).toContain(n);
    const script = read("../docs/PITCH.md");
    expect(script).toContain("Axios");
    expect(script).toMatch(/Wells Fargo has said nothing we could find/);
  });
});

describe("the old synthetic company", () => {
  const needle = ["Coastal", "Supply"].join(" ");
  const skip = new Set(["node_modules", ".next", ".git", "coverage"]);
  const text = /\.(ts|tsx|mjs|md|css|json|jsonl|txt)$/;
  const files = (dir: string): string[] =>
    readdirSync(dir).flatMap((f) => {
      if (skip.has(f)) return [];
      const p = join(dir, f);
      return statSync(p).isDirectory() ? files(p) : text.test(f) ? [p] : [];
    });

  it("is not named anywhere in frontend/", () => {
    const hits = files(root).filter((p) => !p.endsWith("lenders.test.ts") && readFileSync(p, "utf8").includes(needle));
    expect(hits).toEqual([]);
  });
});
