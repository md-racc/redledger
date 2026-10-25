import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  agentModels,
  controlRating,
  controlText,
  effectiveControls,
  executiveSummary,
  gapExplanation,
  gapRecommendation,
  isNotFinalAnswer,
  list,
  listSome,
  lostSentence,
  modelText,
  outcomeText,
  pct,
  reportDate,
  reportFilename,
  schemesByLoss,
  usd,
} from "./summary";
import type { ControlsReport, Gap } from "./types";

// the recorded demo (docs/recordings/demo-enforce-redblue-live.jsonl) as battlefield's builder derives it
const fixture: ControlsReport = JSON.parse(readFileSync("public/mocks/controls-report.json", "utf8"));
const clone = (): ControlsReport => structuredClone(fixture);

describe("the mock fixture", () => {
  it("carries the recorded demo's numbers and no ground-truth keys", () => {
    expect(fixture.final).toBe(true);
    expect(fixture.score.dollars_extracted).toBe(20350.37);
    expect([fixture.lost, fixture.to_attacker_accounts, fixture.to_real_parties]).toEqual([20350.37, 18180, 2170.37]);
    for (const s of fixture.schemes) expect((s.to_attacker_accounts ?? 0) + (s.to_real_parties ?? 0)).toBeCloseTo(s.lost, 2);
    expect(fixture.false_positives.cost).toBe(50);
    expect(fixture.false_positives.legit_blocked).toBe(1);
    const gaps = Object.fromEntries(fixture.gaps.map((g) => [g.scheme_id, g]));
    expect(gaps.ghost_vendor!.extracted).toBe(4380);
    expect(gaps.ghost_vendor!.why).toBe("note only");
    expect(gaps.bank_swap!.extracted).toBe(1824.22);
    expect(gaps.threshold_split!.extracted).toBe(13800);
    expect(gaps.expense_inflation!.extracted).toBe(346.15);
    expect(fixture.schemes.find((s) => s.scheme_id === "ghost_employee")!.outcomes.blocked).toBe(1);
    expect(JSON.stringify(fixture)).not.toMatch(/"(origin|entity_origin|origin_of_source)"\s*:/);
  });
});

describe("formatting", () => {
  it("money, shares and lists", () => {
    expect(usd(20350.37)).toBe("$20,350.37");
    expect(usd(4380, true)).toBe("$4,380");
    expect(usd(Number.NaN)).toBe("$0.00");
    expect(usd(undefined)).toBe("$0.00");
    expect(pct(20350.37, 27565.92)).toBe("74%");
    expect(pct(5, 0)).toBe("0%");
    expect(list([])).toBe("");
    expect(list(["a"])).toBe("a");
    expect(list(["a", "b", "c"])).toBe("a, b and c");
    expect(listSome(["a", "b", "c"])).toBe("a, b and c");
    expect(listSome(["a", "b", "c", "d", "e"])).toBe("a, b, c and 2 more");
  });

  it("names controls in a reader's words, unknown ones de-snaked", () => {
    expect(controlText("vendor_age_lt_7d")).toBe("Vendor has less than seven days of history");
    expect(controlText("learned:bank_change_any_amount")).toMatch(/^Learned: /);
    expect(controlText("some_new_rule")).toBe("Some new rule");
    expect(controlText("learned:fresh_idea")).toBe("Learned: Fresh idea");
  });

  it("outcomes in a fixed order without zeros", () => {
    expect(outcomeText({ extracted: 0, partial: 1, blocked: 0, flagged: 0, failed: 0, pending: 0 })).toBe("1 partial");
    expect(outcomeText({ blocked: 2, extracted: 1 })).toBe("1 extracted, 2 blocked");
    expect(outcomeText({})).toBe("none");
  });

  it("dates and file names", () => {
    expect(reportDate(fixture)).toBe("25 October 2026");
    const r = clone();
    r.episode.finished_at = r.episode.started_at = r.episode.created_at = null;
    expect(reportDate(r)).toBe("");
    r.episode.id = "replay_x/../y";
    expect(reportFilename(r)).toBe("controls-assessment-replay_x----y.json");
  });
});

describe("the assessment", () => {
  it("rates controls by what they did to fraud and to legit work", () => {
    const rows = Object.fromEntries(fixture.controls.map((c) => [c.control_id, c]));
    expect(controlRating(rows.no_hr_record!)).toBe("effective");
    expect(controlRating(rows.bank_change_with_open_invoices!)).toBe("effective, noisy");
    expect(controlRating(rows.vendor_age_lt_7d!)).toBe("ineffective");
    expect(controlRating(rows.near_threshold!)).toBe("not tested");
    expect(effectiveControls(fixture).map((c) => c.control_id)).toEqual(["no_hr_record", "bank_change_with_open_invoices"]);
  });

  it("writes the executive summary from the data, one sentence per point", () => {
    const s = executiveSummary(fixture);
    expect(s[0]).toBe("An adaptive attacker made 6 attempts across 6 schemes worth $27,565.92; $1,480.00 of it was stopped.");
    expect(s[1]).toBe(
      "$20,350.37 lost to fraud (74% of attempted), of which $18,180.00 reached attacker-controlled accounts and $2,170.37 was paid to real vendors/employees on fraudulent documents (an overpayment, usually recoverable).",
    );
    expect(s[2]).toMatch(/^2 controls stopped fraudulent items: "Employee has no HR onboarding record" \(3 items, \$1,480\.00\) and /);
    expect(s[3]).toBe("4 schemes still extracted money: Threshold Splitting ($13,800.00, note only), Ghost Vendor ($4,380.00, note only), Bank Account Swap ($1,824.22, no control fired) and 1 more.");
    expect(s[4]).toBe("False positives cost $50.00: 1 legitimate item blocked and 0 escalated for review.");
    expect(s).toHaveLength(5);
  });

  it("says so when nothing was attempted, nothing got through, or the controller was not enforcing", () => {
    const r = clone();
    r.totals = { ...r.totals, attacks: 0, schemes: 0, attempted: 0, extracted: 0, blocked: 0 };
    r.controls = [];
    r.gaps = [];
    r.false_positives = { ...r.false_positives, cost: 0, legit_blocked: 0, legit_escalated: 0 };
    r.episode.controller_mode = "shadow";
    const s = executiveSummary(r);
    expect(s[0]).toMatch(/no attempts/);
    expect(s).toContain("No legitimate item was blocked or escalated: false-positive cost is $0.00.");
    expect(s[s.length - 1]).toMatch(/shadow mode/);
    const clean = clone();
    clean.gaps = [];
    expect(executiveSummary(clean)).toContain("No scheme extracted money: there are no open gaps from this run.");
  });

  it("explains every gap reason in plain English, with a recommendation", () => {
    const g = (why: Gap["why"], extra: Partial<Gap> = {}): Gap => ({
      scheme_id: "s",
      display_name: "S",
      extracted: 1,
      why,
      controls_on_paid: ["vendor_age_lt_7d"],
      caught_elsewhere: [],
      audit_detected: false,
      paid_entity_ids: [],
      ...extra,
    });
    expect(gapExplanation(g("note only"), "enforce")).toBe('"Vendor has less than seven days of history" fired, but only as a note: the payment was allowed.');
    expect(gapExplanation(g("no control fired", { caught_elsewhere: ["bank_change_with_open_invoices"] }), "enforce")).toMatch(
      /^No gate control fired on the items that were paid\. The gate did act on another part of the scheme \("Bank account change while invoices are open"\)/,
    );
    expect(gapExplanation(g("no control fired"), "off")).toMatch(/switched off/);
    expect(gapExplanation(g("escalation approved"), "enforce")).toMatch(/human reviewer approved/);
    expect(gapExplanation(g("audit only"), "enforce")).toMatch(/after-the-fact audit/);
    expect(gapExplanation(g("not enforced"), "shadow")).toMatch(/shadow mode/);
    expect(gapRecommendation(g("note only"))).toMatch(/^Promote "Vendor has less than seven days of history" from a note/);
    for (const why of ["no control fired", "escalation approved", "audit only", "not enforced"] as const) expect(gapRecommendation(g(why))).toMatch(/\.$/);
  });

  it("says where lost money landed, or that a replay can't tell", () => {
    const r = clone();
    r.to_attacker_accounts = r.to_real_parties = null;
    expect(lostSentence(r)).toBe("$20,350.37 lost to fraud (74% of attempted); where it landed is not recorded for a replayed run.");
    const all = clone();
    all.to_attacker_accounts = all.lost;
    all.to_real_parties = 0;
    expect(lostSentence(all)).toMatch(/and \$0\.00 was paid to real vendors\/employees on fraudulent documents\.$/);
    const none = clone();
    none.lost = none.to_attacker_accounts = none.to_real_parties = 0;
    expect(lostSentence(none)).toBe("No money was lost to fraud.");
  });

  it("orders schemes worst first", () => {
    expect(schemesByLoss(fixture.schemes).map((s) => s.scheme_id).slice(0, 3)).toEqual(["threshold_split", "ghost_vendor", "bank_swap"]);
  });
});

describe("plumbing", () => {
  it("reads the agents' models from /health", () => {
    const h = { ok: true, agents: { blue: { ok: true, model: "gpt-5.4-mini", dry_run: false }, red: { ok: true, model: "gpt-5.4-mini", dry_run: false }, green: { ok: true, model: "custom:x", dry_run: true } } };
    const m = agentModels(h);
    expect(m.map((x) => x.agent)).toEqual(["red", "green", "blue"]);
    expect(modelText(m[0]!)).toBe("gpt-5.4-mini");
    expect(modelText(m[1]!)).toBe("custom:x (dry run: canned turns)");
    expect(modelText(agentModels({ agents: { red: { ok: false, error: "down" } } })[0]!)).toBe("unreachable");
    expect(agentModels(null)).toEqual([]);
    expect(agentModels({ agents: "x" })).toEqual([]);
  });

  it("recognizes the proxy's not-final answer and nothing else", () => {
    expect(isNotFinalAnswer(403, JSON.stringify({ error: "viewer", detail: "available when the run ends" }))).toBe(true);
    expect(isNotFinalAnswer(403, JSON.stringify({ error: "viewer" }))).toBe(false);
    expect(isNotFinalAnswer(404, JSON.stringify({ error: "viewer", detail: "available when the run ends" }))).toBe(false);
    expect(isNotFinalAnswer(403, "not json")).toBe(false);
  });
});
