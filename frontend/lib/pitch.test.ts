// The pitch (docs/PITCH.md) is cut from docs/STORY.md and quotes only docs/EVIDENCE.md's numbers. This keeps the three in step.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import type { LiveRuns } from "./arena/liveRuns";

// Windows checkouts may hold CRLF: the tests care about the words, not the line endings
const read = (p: string) => readFileSync(join(__dirname, "..", p), "utf8").replace(/\r\n/g, "\n");
const pitch = read("../docs/PITCH.md");
const story = read("../docs/STORY.md");
const evidence = read("../docs/EVIDENCE.md");
const words = (t: string) => t.replace(/[*_`#>|[\]]/g, " ").split(/\s+/).filter(Boolean).length;
const section = (doc: string, head: string) => doc.split(head)[1]!.split(/\n## /)[0]!;

describe("the judging talk", () => {
  const talk = section(pitch, "## 1. The 5-minute judging talk");

  it("has all four voices, in order", () => {
    const heads = [...talk.matchAll(/^### (\S+)/gm)].map((m) => m[1]!);
    expect(heads).toEqual(["Al", "R", "M", "Ad", "Questions"]);
  });

  it("is honest about what is live and what blue does not do", () => {
    expect(talk).toMatch(/runs our logic without a model/);
    expect(talk).toMatch(/blue doesn't learn new rules yet/);
    expect(talk).toMatch(/three of red's twelve attempts/);
  });

  it("has a line for every track we enter", () => {
    const card = section(pitch, "## 2. Track card");
    for (const t of ["Hyphenate", "Factory", "Microsoft", "CRS", "Armadin", "Most Technically Advanced"]) expect(card, t).toContain(`**${t}`);
  });
});

describe("the numbers", () => {
  it("are the ones the Real run tab shows", () => {
    const runs = JSON.parse(read("public/mocks/live-runs.json")) as LiveRuns;
    expect(Math.round(runs.runs.off.score.dollars_extracted)).toBe(10285);
    for (const doc of [story, pitch]) expect(doc).toContain("$10,285");
    expect(pitch).toMatch(/ten thousand two hundred eighty-five dollars/);
  });

  it("never quote the pre-rescoring controller-on figure as a loss", () => {
    expect(story).not.toMatch(/1,824/);
    expect(pitch.replace(/don't quote \$1,824/, "")).not.toMatch(/1,824/);
  });

  it("never say Tiger Data's TimescaleDB runs in production", () => {
    for (const doc of [story, pitch]) expect(doc).not.toMatch(/timescale[^.\n]*in production/i);
    expect(evidence).toMatch(/Prod runs plain Postgres 16/);
  });

  it("cite the Droid SDK features we claim", () => {
    for (const f of ["restrict_tools", "disable_builtin_skills"]) expect(evidence, f).toContain(f);
  });
});
