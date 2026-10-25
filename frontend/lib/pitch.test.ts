// The pitch (root PITCH.md) is cut from STORY.md and quotes only EVIDENCE.md's numbers. This keeps the three in step.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import type { LiveRuns } from "./arena/liveRuns";

// Windows checkouts may hold CRLF: the tests care about the words, not the line endings
const read = (p: string) => readFileSync(join(__dirname, "..", p), "utf8").replace(/\r\n/g, "\n");
const pitch = read("../PITCH.md");
const story = read("../STORY.md");
const evidence = read("../EVIDENCE.md");
const words = (t: string) => t.replace(/[*_`#>|[\]]/g, " ").split(/\s+/).filter(Boolean).length;
const section = (doc: string, head: string) => doc.split(head)[1]!.split(/\n## /)[0]!;

/** the video's voiceover, the last cell of each timed row in §1 */
const voiceover = section(pitch, "## 1. The 90-second video")
  .split("\n")
  .filter((l) => /^\| \d:\d\d/.test(l))
  .map((l) => l.split("|").at(-2)!.trim());

describe("the video", () => {
  it("fits 90 seconds of speech", () => {
    expect(voiceover.length).toBeGreaterThanOrEqual(6);
    expect(words(voiceover.join(" "))).toBeLessThanOrEqual(230);
  });
});

describe("the judging talk", () => {
  const talk = section(pitch, "## 2. The 5-minute judging talk");

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
    const card = section(pitch, "## 3. Track card");
    for (const t of ["Hyphenate", "Factory", "Microsoft", "CRS", "Armadin", "Atlassian", "Most Technically Advanced"]) expect(card, t).toContain(`**${t}`);
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
