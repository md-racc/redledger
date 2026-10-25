// The pitch is two pages, for all four people, and it names every sponsor we enter. This keeps it that way.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import type { LiveRuns } from "./arena/liveRuns";

// Windows checkouts may hold CRLF: the tests care about the words, not the line endings
const read = (p: string) => readFileSync(join(__dirname, "..", p), "utf8").replace(/\r\n/g, "\n");
const script = read("docs/pitch-script.md");
const sponsors = read("docs/sponsors.md");
const words = (t: string) => t.replace(/[*_`#>|[\]]/g, " ").split(/\s+/).filter(Boolean).length;

/** two pages at a readable size, with a table on the second */
const MAX_WORDS = 1050;
const MAX_PER_PAGE = 540;

describe("the pitch script", () => {
  it("fits two pages", () => {
    expect(words(script)).toBeLessThanOrEqual(MAX_WORDS);
    const pages = script.split(/\n---\n/);
    expect(pages).toHaveLength(2);
    for (const p of pages) expect(words(p)).toBeLessThanOrEqual(MAX_PER_PAGE);
  });

  it("has all four voices, in order", () => {
    const heads = [...script.matchAll(/^## (.+)$/gm)].map((m) => m[1]!);
    expect(heads.slice(0, 5)).toEqual(["R: open", "GREEN: laptop 3", "BLUE: laptop 4", "RED: laptop 2", "R: close"]);
  });

  it("says each sponsor's name out loud, in bold, before the table", () => {
    const spoken = script.split("## Sponsors")[0]!;
    for (const name of ["Factory", "Hyphenate", "Tiger Data", "Armadin", "Vultr", "ElevenLabs"]) expect(spoken, name).toMatch(new RegExp(`\\*\\*${name}`));
  });

  it("lists every sponsor in the table, with a straight status", () => {
    const table = script.split("## Sponsors")[1]!;
    for (const name of ["Factory", "Hyphenate", "Tiger Data", "Vultr", "Microsoft", "Armadin", "ElevenLabs", "CRS"]) expect(table, name).toContain(name);
    expect(table).toMatch(/production Postgres 16/); // never "TimescaleDB in production"
  });

  it("never says Tiger Data's TimescaleDB runs in production", () => {
    expect(script).not.toMatch(/timescale[^.\n]*in production/i);
  });

  it("says the numbers the Real run tab shows", async () => {
    const runs = JSON.parse(read("public/mocks/live-runs.json")) as LiveRuns;
    expect(Math.round(runs.runs.off.score.dollars_extracted / 1000)).toBe(10); // "about ten thousand"
    expect(script).toMatch(/about ten thousand dollars gone with no controller/);
    expect(Math.round(runs.runs.enforce.score.dollars_extracted / 100)).toBe(18); // "about eighteen hundred"
    expect(script).toMatch(/about eighteen hundred with one/);
  });

  it("is honest about what is live", () => {
    expect(script).toMatch(/red and blue's audit are live/);
    expect(script).toMatch(/Green is keyless on the same harness/);
    expect(script).toMatch(/The show was a recording/);
  });
});

describe("the sponsor sheet", () => {
  it("covers every prize we enter and says what we are not claiming", () => {
    for (const h of ["## Factory", "## Hyphenate", "## Tiger Data", "## Vultr", "## Microsoft", "## Armadin", "## ElevenLabs", "## CRS", "## MLH Best Use of Gen AI", "## Not claimed"]) expect(sponsors, h).toContain(h);
    expect(sponsors).toMatch(/Production runs plain Postgres 16/);
    expect(sponsors).toMatch(/never tested against the real service/);
  });

  it("names the Droid SDK features we use", () => {
    for (const f of ["restrict_tools", "disable_builtin_skills", "ThinkingDelta", "X-Tool-Use-Id", "HIGH", "OFF"]) expect(sponsors, f).toContain(f);
  });
});
