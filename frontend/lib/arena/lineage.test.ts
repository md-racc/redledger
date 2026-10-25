// The Evolution card's story beats, against the synthetic sample and against prod-shaped playbooks (ln_f52a3df83c8d).
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../api";
import { PINNED_LINEAGE, blueControlsAfter, brief, cardLineage, diffChips, lineageFromUrl, loadLineageReport, notesAfter, visibleGenerations, type LineageReport, type PlaybookVersion } from "./lineage";

const sample = JSON.parse(readFileSync(join(__dirname, "../../public/mocks/lineage-report.json"), "utf8")) as LineageReport;

const pb = (p: Partial<PlaybookVersion>): PlaybookVersion => ({ version: 0, parent_version: null, generation: 0, source: "seed", day: null, rationale: "", content: {}, diff: { added: {}, changed: {}, removed: {} }, ...p });
const obs = (generation: number, day: number, scheme: string, outcome: string, caught: boolean) => ({ id: `${generation}-${day}-${"f".repeat(60)}`, day, caught, scheme, outcome, controls: ["allow"], generation });

/** the shape prod's lineage report has: blue keeps `learned` / `retired` lists plus a `blue_review` pointer; red keeps object observations */
function prodShaped(): LineageReport {
  const learned = ["learned:bank_change_any_amount", "learned:duplicate_amount_loose", "learned:near_threshold_wide", "learned:young_vendor_any_amount"];
  const before = [obs(1, 3, "threshold_split", "extracted", true)];
  const after = [...before, obs(1, 4, "duplicate_invoice", "extracted", false), obs(1, 5, "threshold_split", "extracted", true), obs(1, 6, "threshold_split", "extracted", false)];
  return {
    ...sample,
    blue: { learned_rules: [{ rule_id: "learned:young_vendor_any_amount", first_generation: 2 }], new_rules: [], retired_rules: [{ rule_id: "duplicate_invoice", last_generation: 1 }, { rule_id: "learned:young_vendor_any_amount", last_generation: 2 }] },
    playbooks: {
      red: [
        pb({}),
        pb({ version: 4, parent_version: 0, generation: 1, source: "turn", content: { red_evolution: { version: 1, observations: before } } }),
        pb({ version: 5, parent_version: 4, generation: 1, source: "reflect", rationale: "Fold own disclosed attack outcomes", content: { red_evolution: { version: 1, observations: after } }, diff: { added: {}, removed: {}, changed: { "red_evolution.observations": { from: before, to: after } } } }),
      ],
      blue: [
        pb({}),
        pb({ version: 1, parent_version: 0, generation: 1, source: "reflect", rationale: "Retained 4 learned review controls; retired 0", content: { learned, retired: [], near_band: 0.9, blue_review: ["ln_f52a3df83c8d", 1, "ep_x"] }, diff: { added: { learned, retired: [], near_band: 0.9, blue_review: ["ln_f52a3df83c8d", 1, "ep_x"] }, changed: {}, removed: {} } }),
        pb({ version: 2, parent_version: 1, generation: 2, source: "reflect", content: { learned, retired: [], near_band: 0.8, blue_review: ["ln_f52a3df83c8d", 2, "ep_y"] }, diff: { added: {}, removed: {}, changed: { blue_review: { from: ["ln_f52a3df83c8d", 1, "ep_x"], to: ["ln_f52a3df83c8d", 2, "ep_y"] }, near_band: { from: 0.9, to: 0.8 } } } }),
      ],
      green: [pb({})],
    },
  };
}

describe("which generations the card shows", () => {
  it("shows every generation up to six, generation 1 included", () => {
    const gens = [1, 2, 3, 4, 5].map((generation) => ({ generation }));
    expect(visibleGenerations(gens)).toEqual({ shown: gens, hidden: 0 });
    const six = [...gens, { generation: 6 }];
    expect(visibleGenerations(six).shown.map((g) => g.generation)).toEqual([1, 2, 3, 4, 5, 6]);
  });

  it("past six keeps the first and the last five and counts the rest", () => {
    const gens = Array.from({ length: 9 }, (_, i) => ({ generation: i + 1 }));
    const v = visibleGenerations(gens);
    expect(v.shown.map((g) => g.generation)).toEqual([1, 5, 6, 7, 8, 9]);
    expect(v.hidden).toBe(3);
  });

  it("the offline sample exercises five generations (four headless and the demo)", () => {
    expect(sample.generations.map((g) => g.generation)).toEqual([1, 2, 3, 4, 5]);
    expect(sample.generations.filter((g) => g.demo).map((g) => g.generation)).toEqual([5]);
    expect(sample.lineage.name).toMatch(/synthetic/);
  });
});

describe("blue's controls come from its playbook, not from rule silence", () => {
  it("prod-shaped: four controls switched on after generation 1, none switched off ever", () => {
    const r = prodShaped();
    const g1 = blueControlsAfter(r, 1);
    expect(g1.basis).toBe("playbook");
    expect(g1.on).toEqual(["learned:bank_change_any_amount", "learned:duplicate_amount_loose", "learned:near_threshold_wide", "learned:young_vendor_any_amount"]);
    expect(g1.off).toEqual([]);
    // battlefield's "retired" is only "did not fire in the latest generation": reported as quiet, never as switched off
    expect(g1.quiet).toEqual(["duplicate_invoice"]);
    const g2 = blueControlsAfter(r, 2);
    expect(g2.on).toEqual([]);
    expect(g2.off).toEqual([]);
    expect(g2.quiet).toEqual(["learned:young_vendor_any_amount"]);
  });

  it("sample: switched on after 1 and 3, switched off after 4 when the playbook records it", () => {
    expect(blueControlsAfter(sample, 1).on).toEqual(["learned:ghost_vendor"]);
    expect(blueControlsAfter(sample, 3).on).toEqual(["learned:split_sibling"]);
    expect(blueControlsAfter(sample, 4)).toMatchObject({ on: [], off: ["learned:ghost_vendor"] });
  });

  it("without control lists in blue's playbook it says 'first fired', never 'switched off'", () => {
    const r = { ...prodShaped() };
    r.playbooks = { ...r.playbooks, blue: [pb({}), pb({ version: 1, parent_version: 0, generation: 1, source: "reflect", content: { near_band: 0.9 } })] };
    const c = blueControlsAfter(r, 2);
    expect(c.basis).toBe("report");
    expect(c.on).toEqual(["learned:young_vendor_any_amount"]);
    expect(c.off).toEqual([]);
  });
});

describe("playbook chips are words, never [object Object]", () => {
  it("summarises what red's reflection holds about the generation, by scheme and outcome", () => {
    const red = notesAfter(prodShaped(), 1).find((n) => n.agent === "red")!;
    expect(red.chips.join(" ")).not.toContain("[object Object]");
    expect(red.chips).toEqual(["outcomes of gen 1: threshold split extracted ×3, duplicate invoice extracted"]);
  });

  it("a generic diff of object lists names what was added", () => {
    const before = [obs(1, 3, "threshold_split", "extracted", true)];
    const after = [...before, obs(1, 4, "duplicate_invoice", "failed", false), obs(1, 5, "duplicate_invoice", "failed", false)];
    expect(diffChips({ added: {}, removed: {}, changed: { "x.list": { from: before, to: after } } })).toEqual(["+ x list: duplicate invoice failed ×2"]);
  });

  it("an added record becomes one chip per key, bookkeeping dropped, long text clipped", () => {
    const chips = diffChips({ added: { green_reflection: { schema_version: 1, last_review_counts: { fraud_paid: 5 }, procedure_reminders: ["Re-read current entity state and existing payments before dependent writes; count only confirmed receipts."] } }, changed: {}, removed: {} });
    expect(chips[0]).toBe("+ green reflection last review counts: fraud paid ×5");
    expect(chips[1].length).toBeLessThan(110);
    expect(chips.join(" ")).not.toContain("schema version");
  });

  it("drops bookkeeping and blue's control lists (they have their own line)", () => {
    const blue = notesAfter(prodShaped(), 1).find((n) => n.agent === "blue")!;
    expect(blue.chips).toEqual(["+ near band: 0.9"]);
    expect(notesAfter(prodShaped(), 2).find((n) => n.agent === "blue")!.chips).toEqual(["~ near band: 0.8"]);
  });

  it("brief: objects by id and key param, maps by count, long lists capped", () => {
    expect(brief({ scheme_id: "evolved:split_v2", target_amount: 4000 })).toBe("split v2 $4,000");
    expect(brief({ "evolved:split_v2": 1, ghost_vendor: 2 })).toBe("split v2 ×1, ghost vendor ×2");
    expect(brief(["a", "b", "c", "d", "e", "f"])).toBe("a, b, c, d +2 more");
    expect(brief([])).toBe("none");
    expect(brief({ nested: { deep: { x: 1 } } })).not.toContain("[object Object]");
    expect(diffChips({ added: {}, changed: { avoid: { from: ["duplicate_invoice"], to: ["duplicate_invoice", "ghost_vendor"] } }, removed: {} })).toEqual(["+ avoid: ghost vendor"]);
  });

  it("every note in the sample renders as text", () => {
    for (const g of sample.generations) for (const n of notesAfter(sample, g.generation)) expect(n.chips.join(" ")).not.toMatch(/object Object/);
  });
});

describe("which lineage loads", () => {
  const report = (id: string) => ({ ...sample, lineage: { ...sample.lineage, id } });
  const fallback = async () => sample;

  it("?lineage=<id> wins, else the pinned showcase lineage", () => {
    expect(lineageFromUrl("?lineage=ln_abc123")).toBe("ln_abc123");
    expect(lineageFromUrl("?lineage=../etc")).toBeNull();
    expect(cardLineage("?show=1")).toBe(PINNED_LINEAGE);
    expect(cardLineage("?lineage=ln_abc123")).toBe("ln_abc123");
    expect(PINNED_LINEAGE).toBe("ln_f52a3df83c8d");
  });

  it("loads the requested lineage", async () => {
    const client = { lineages: vi.fn(), fe: { lineageReport: vi.fn(async (id: string) => report(id)) } };
    const l = await loadLineageReport(true, PINNED_LINEAGE, client, fallback);
    expect(l).toMatchObject({ source: "live", report: { lineage: { id: PINNED_LINEAGE } } });
    expect(l.note).toBeUndefined();
    expect(client.lineages).not.toHaveBeenCalled();
  });

  it("falls back to the newest finished lineage when the pinned one 404s, and says so", async () => {
    const client = {
      lineages: vi.fn(async () => [{ id: "ln_running", status: "running", generations: [1] }, { id: "ln_new", status: "finished", generations: [1, 2] }, { id: "ln_old", status: "finished", generations: [1, 2] }]),
      fe: { lineageReport: vi.fn(async (id: string) => { if (id === PINNED_LINEAGE) throw new ApiError("GET", "/x", 404, "{}"); return report(id); }) },
    };
    const l = await loadLineageReport(true, PINNED_LINEAGE, client, fallback);
    expect(l.source).toBe("live");
    expect(l.report.lineage.id).toBe("ln_new");
    expect(l.note).toContain(`${PINNED_LINEAGE} not found`);
  });

  it("with no backend, or in mock mode, shows the synthetic sample", async () => {
    const down = { lineages: vi.fn(async () => { throw new TypeError("fetch failed"); }), fe: { lineageReport: vi.fn(async () => { throw new TypeError("fetch failed"); }) } };
    expect((await loadLineageReport(true, PINNED_LINEAGE, down, fallback)).source).toBe("recorded");
    expect((await loadLineageReport(false, PINNED_LINEAGE, down, fallback)).source).toBe("recorded");
    expect(down.fe.lineageReport).toHaveBeenCalledTimes(1);
  });
});
