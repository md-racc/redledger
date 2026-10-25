// The Evolution card as judges see it: every generation, honest control labels, no "[object Object]", and the source said out loud.
import React from "react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeAll, describe, expect, it } from "vitest";
import { EvolutionCard } from "@/components/arena/overlays/EvolutionCard";
import type { LineageReport, LoadedLineage } from "@/lib/arena/lineage";

// vitest compiles the component's JSX with the classic runtime: give it React
beforeAll(() => { (globalThis as { React?: typeof React }).React = React; });

const sample = JSON.parse(readFileSync(join(__dirname, "../../../public/mocks/lineage-report.json"), "utf8")) as LineageReport;
const html = (initial: LoadedLineage, detail = false) => renderToStaticMarkup(<EvolutionCard open driven={false} preferLive={initial.source === "live"} onClose={() => {}} initial={initial} initialDetail={detail} />);
const columns = (out: string) => [...out.matchAll(/<h4><span>Gen (\d+)<\/span>/g)].map((m) => Number(m[1]));

describe("the Evolution card", () => {
  it("shows all five generations of the offline sample, generation 1 first", () => {
    const out = html({ report: sample, source: "recorded" });
    expect(columns(out)).toEqual([1, 2, 3, 4, 5]);
    expect(out).toContain("repeat(5, minmax(0, 1fr))");
    expect(out).toContain("synthetic sample");
    expect(out).not.toContain("recorded lineage");
  });

  it("past six generations keeps the first and the last five and says so", () => {
    const base = sample.generations[1];
    const gens = Array.from({ length: 8 }, (_, i) => ({ ...base, generation: i + 1, episode_id: `ep_${i + 1}`, demo: false }));
    const out = html({ report: { ...sample, generations: gens }, source: "live" });
    expect(columns(out)).toEqual([1, 4, 5, 6, 7, 8]);
    expect(out).toContain("8 generations: showing generation 1 and the last 5 (2 in between hidden)");
    expect(out).toContain("live lineage");
  });

  it("never claims a control was retired because it went quiet", () => {
    const out = html({ report: sample, source: "recorded" }, true);
    expect(out).not.toContain("controls retired");
    expect(out).toContain("controls switched on");
    expect(out).toContain("split sibling");
    // blue's own playbook switched ghost_vendor off after gen 4: that one is on record
    expect(out).toContain("controls switched off");
    // battlefield's retired_rules (no fire in the latest generation) is reported as exactly that
    expect(out).toContain("not fired after this generation");
  });

  it("renders red's learning as words", () => {
    const out = html({ report: sample, source: "recorded" }, true);
    expect(out).not.toContain("[object Object]");
    expect(out).toContain("outcomes of gen 3: split v2 extracted ×2, bank swap blocked");
  });

  it("opens in the simple view: how to read it, red's and blue's totals in words, no rule statistics", () => {
    const out = html({ report: sample, source: "recorded" });
    expect(out).toContain("Each column is one generation");
    expect(out).toMatch(/Red&#x27;s take went up from \$3,000 in generation 1 to \$15,500 in generation 4\./);
    expect(out).toMatch(/Blue&#x27;s blocked total went up from \$2,000 in generation 1 to \$5,000 in generation 4\./);
    expect(out).toContain("Show detail");
    expect(out).toContain("Red tried");
    expect(out).toContain("Blue caught red with:");
    // the numbers behind it stay one click away
    for (const jargon of ["precision", "recall", "not fired after this generation", "outcomes of gen"]) expect(out, jargon).not.toContain(jargon);
    // the honest labels stay in the simple view
    expect(out).toContain("controls switched on");
    expect(out).toContain("controls switched off");
  });

  it("shows the rule statistics and the playbook diffs under Show detail", () => {
    const out = html({ report: sample, source: "recorded" }, true);
    expect(out).toContain("Simple view");
    expect(out).toContain("precision 0.50");
    expect(out).toContain("recall 0.50");
    expect(out).toContain("Red tried · blue&#x27;s controls");
  });

  it("names the fallback when the asked-for lineage was not found", () => {
    const out = html({ report: sample, source: "live", note: "ln_f52a3df83c8d not found · newest finished lineage" });
    expect(out).toContain("ln_f52a3df83c8d not found · newest finished lineage");
  });
});
