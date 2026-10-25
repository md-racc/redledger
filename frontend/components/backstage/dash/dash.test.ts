import { describe, expect, it } from "vitest";
import { initialState, reduce } from "@/lib/reducer";
import type { RLEvent } from "@/lib/types";
import {
  agentTurns, asTimeline, withLatency, compactJson, creditsOf, diffLines, escalationRows, generationEntries, lineageIdOf, playbookHistory, schemeCatalog, scrub,
  splitTool, turnElapsedSec, verdictKind, verdictRows, verdictStats,
} from "./dash";

// battlefield/fixtures/lineages/sample-timeline.json (entries only), inlined: the frontend image is built without battlefield/
const timeline = {"entries":[{"agent":"blue","day":null,"diff":{"added":{},"changed":{},"removed":{}},"episode_id":null,"generation":0,"kind":"playbook","parent_version":null,"rationale":"","source":"seed","version":0},{"agent":"green","day":null,"diff":{"added":{},"changed":{},"removed":{}},"episode_id":null,"generation":0,"kind":"playbook","parent_version":null,"rationale":"","source":"seed","version":0},{"agent":"red","day":null,"diff":{"added":{},"changed":{},"removed":{}},"episode_id":null,"generation":0,"kind":"playbook","parent_version":null,"rationale":"","source":"seed","version":0},{"agent":"red","day":1,"diff":{"added":{"avoid":[]},"changed":{},"removed":{}},"episode_id":"ep_rpt_g1","generation":1,"kind":"playbook","parent_version":0,"rationale":"watching","source":"turn","version":1},{"demo":false,"episode_id":"ep_rpt_g1","generation":1,"kind":"generation","score":{"attacks_caught":1,"attacks_launched":2,"detection_latency_days":0.0,"dollars_blocked":2000.0,"dollars_extracted":3000.0,"false_positive_cost":70.0,"legit_blocked":1,"legit_processed":0},"seed":43,"status":"finished"},{"agent":"blue","day":null,"diff":{"added":{"learned":["ghost_vendor"],"near_band":0.95},"changed":{},"removed":{}},"episode_id":null,"generation":1,"kind":"playbook","parent_version":0,"rationale":"ghost_vendor got past me","source":"reflect","version":1},{"agent":"red","day":null,"diff":{"added":{"favour":{"ghost_vendor":2}},"changed":{"avoid":{"from":[],"to":["duplicate_invoice"]}},"removed":{}},"episode_id":null,"generation":1,"kind":"playbook","parent_version":1,"rationale":"duplicate_invoice blocked","source":"reflect","version":2},{"demo":false,"episode_id":"ep_rpt_g2","generation":2,"kind":"generation","score":{"attacks_caught":1,"attacks_launched":2,"detection_latency_days":0.0,"dollars_blocked":3000.0,"dollars_extracted":4000.0,"false_positive_cost":0.0,"legit_blocked":0,"legit_processed":0},"seed":44,"status":"finished"},{"agent":"red","day":null,"diff":{"added":{"favour.evolved:split_v2":1},"changed":{"avoid":{"from":["duplicate_invoice"],"to":["duplicate_invoice","ghost_vendor"]}},"removed":{"favour.ghost_vendor":2}},"episode_id":null,"generation":2,"kind":"playbook","parent_version":2,"rationale":"ghost_vendor caught","source":"reflect","version":3},{"demo":true,"episode_id":"ep_rpt_g3","generation":3,"kind":"generation","score":{"attacks_caught":0,"attacks_launched":0,"detection_latency_days":null,"dollars_blocked":0.0,"dollars_extracted":0.0,"false_positive_cost":0.0,"legit_blocked":0,"legit_processed":0},"seed":50,"status":"finished"}],"lineage_id":"ln_rpt_sample","partial":false,"status":"finished"};

let id = 0;
const ev = (type: string, payload: Record<string, unknown>, o: Partial<RLEvent> = {}): RLEvent => ({ id: ++id, ts: new Date(Date.UTC(2026, 9, 25, 12, 0, 0) + id * 1000).toISOString(), episode_id: "ep_1", day: 1, type, agent: "battlefield", payload, ...o });

describe("agentTurns", () => {
  it("groups thinking and tool calls per turn and pairs results by tool_use_id", () => {
    id = 0;
    const events = [
      ev("turn.started", { agent: "red" }),
      ev("agent.thinking", { text: "Looking at " }, { agent: "red" }),
      ev("agent.thinking", { text: "vendors." }, { agent: "red" }),
      ev("agent.tool_call", { tool: "mcp__ledger__list_vendors", args: { limit: 5 }, tool_use_id: "tu_1" }, { agent: "red" }),
      ev("agent.tool_call", { tool: "mcp__ledger__create_vendor", args: { name: "Acme" }, tool_use_id: "tu_2" }, { agent: "red" }),
      ev("agent.tool_result", { tool_use_id: "tu_2", ok: true, summary: "vendor v_9" }, { agent: "red" }),
      ev("agent.tool_result", { tool_use_id: "tu_1", ok: false, summary: "timeout" }, { agent: "red" }),
      ev("agent.thinking", { text: "not mine" }, { agent: "blue" }),
      ev("turn.ended", { agent: "red", ok: true, summary: "made a vendor", duration_sec: 12.5, factory_credits: 0.4 }),
      ev("turn.started", { agent: "red" }, { day: 2 }),
      ev("agent.thinking", { text: "day two" }, { agent: "red", day: 2 }),
    ];
    const turns = agentTurns(events, "red");
    expect(turns).toHaveLength(2);
    const [t1, t2] = turns;
    expect(t1!.thinking).toBe("Looking at vendors.");
    expect(t1!.ended).toBe(true);
    expect(t1!.credits).toBe(0.4);
    expect(t1!.summary).toBe("made a vendor");
    expect(t1!.tools.map((t) => [t.tool_use_id, t.ok, t.summary])).toEqual([["tu_1", false, "timeout"], ["tu_2", true, "vendor v_9"]]);
    expect(t1!.tools[0]!.latencyMs).toBe(3000); // call #4 → result #7, one second apart each
    expect(t1!.tools[1]!.latencyMs).toBe(1000);
    expect(t2!.ended).toBe(false);
    expect(t2!.thinking).toBe("day two");
    expect(t2!.n).toBe(2);
  });

  it("pairs a result without tool_use_id with the oldest waiting call", () => {
    id = 0;
    const turns = agentTurns([
      ev("turn.started", { agent: "blue" }),
      ev("agent.tool_call", { tool: "a", args: {} }, { agent: "blue" }),
      ev("agent.tool_call", { tool: "b", args: {} }, { agent: "blue" }),
      ev("agent.tool_result", { ok: true, summary: "first" }, { agent: "blue" }),
    ], "blue");
    expect(turns[0]!.tools.map((t) => [t.tool, t.ok, t.summary])).toEqual([["a", true, "first"], ["b", undefined, ""]]);
  });

  it("puts agent events outside a turn into an implicit block and skips duplicate ids", () => {
    id = 0;
    const a = ev("agent.thinking", { text: "x" }, { agent: "red" });
    const turns = agentTurns([a, a, ev("playbook.updated", { agent: "red", version: 3, parent_version: 2, source: "turn", rationale: "lean on splits" })], "red");
    expect(turns).toHaveLength(1);
    expect(turns[0]!.implicit).toBe(true);
    expect(turns[0]!.thinking).toBe("x");
    expect(turns[0]!.notes[0]!.text).toContain("playbook v3 (from v2) · turn: lean on splits");
  });

  it("reports elapsed time for a running turn", () => {
    id = 0;
    const [t] = agentTurns([ev("turn.started", { agent: "red" })], "red");
    expect(turnElapsedSec(t!, Date.parse(t!.startTs!) + 4500)).toBeCloseTo(4.5);
  });
});

describe("creditsOf", () => {
  it("sums turn.ended credits per agent, null as nothing", () => {
    id = 0;
    const c = creditsOf([
      ev("turn.ended", { agent: "red", factory_credits: 1.5 }),
      ev("turn.ended", { agent: "red", factory_credits: 0.5 }),
      ev("turn.ended", { agent: "blue", factory_credits: null }),
      ev("turn.ended", { agent: "blue", factory_credits: 2 }),
    ]);
    expect(c).toEqual({ byAgent: { red: 2, blue: 2 }, total: 4, reported: true });
    expect(creditsOf([ev("turn.ended", { agent: "red", factory_credits: null })]).reported).toBe(false);
  });
});

describe("verdicts", () => {
  it("tells a clean allow from an allow with notes", () => {
    expect(verdictKind({ verdict: "allow", rules_fired: [] })).toBe("allow");
    expect(verdictKind({ verdict: "allow", rules_fired: ["near_threshold"] })).toBe("noted");
    expect(verdictKind({ verdict: "allow", rules_fired: [], cause: "gate_unavailable" })).toBe("noted");
    expect(verdictKind({ verdict: "block", rules_fired: [] })).toBe("block");
    expect(verdictKind({ verdict: "escalate" })).toBe("escalate");
  });

  it("lists verdicts newest first, once per verdict id, with latency stats", () => {
    id = 0;
    const rows = verdictRows([
      ev("gate.verdict", { verdict_id: "v1", agent: "green", action: "payments.release", amount: 900, verdict: "allow", rules_fired: [], reason: "ok", enforced: true, latency_ms: 10 }),
      ev("gate.verdict", { verdict_id: "v2", agent: "green", action: "payments.release", amount: 4900, verdict: "block", rules_fired: ["near_threshold"], reason: "just under", enforced: false, latency_ms: 30, cause: "control", origin: "red" }),
      ev("gate.verdict", { verdict_id: "v2", agent: "green", action: "payments.release", verdict: "block" }),
    ]);
    expect(rows.map((r) => r.key)).toEqual(["v2", "v1"]);
    expect(rows[0]).toMatchObject({ kind: "block", enforced: false, cause: "control", latencyMs: 30, rules: ["near_threshold"] });
    expect(JSON.stringify(rows)).not.toContain("origin");
    const s = verdictStats(rows);
    expect(s.counts).toEqual({ block: 1, escalate: 0, noted: 0, allow: 1 });
    expect(s.avgMs).toBe(20);
    expect(s.p95Ms).toBe(30);
    expect(s.shadow).toBe(1);
  });
});

describe("withLatency", () => {
  it("fills latency from the verdicts read when the event has none", () => {
    id = 0;
    const rows = verdictRows([ev("gate.verdict", { verdict_id: "v1", verdict: "allow", rules_fired: [] }), ev("gate.verdict", { verdict_id: "v2", verdict: "allow", rules_fired: [], latency_ms: 5 })]);
    const out = withLatency(rows, [{ verdict_id: "v1", latency_ms: 42 }, { verdict_id: "v2", latency_ms: 99 }]);
    expect(out.map((r) => [r.key, r.latencyMs])).toEqual([["v2", 5], ["v1", 42]]);
  });
});

describe("escalationRows", () => {
  it("puts open ones first with the time left", () => {
    id = 0;
    let s = initialState();
    const now = Date.UTC(2026, 9, 25, 12, 0, 0);
    s = reduce(s, ev("escalation.opened", { escalation_id: "e1", verdict_id: "v1", action: "payments.release", amount: 10, reason: "r", expires_at: new Date(now + 90_000).toISOString() }));
    s = reduce(s, ev("escalation.opened", { escalation_id: "e2", verdict_id: "v2", action: "invoices.approve", amount: 20, reason: "r", expires_at: new Date(now + 30_000).toISOString(), cause: "control" }));
    s = reduce(s, ev("escalation.resolved", { escalation_id: "e1", decision: "approve", by: "judge" }));
    const rows = escalationRows(s, now);
    expect(rows.map((r) => [r.id, r.status])).toEqual([["e2", "open"], ["e1", "approve"]]);
    expect(rows[0]!.remainingSec).toBe(30);
    expect(rows[0]!.cause).toBe("control");
  });
});

describe("schemeCatalog", () => {
  it("lists all eight schemes and marks the ones used", () => {
    const cat = schemeCatalog([
      { attack_id: "a1", scheme_id: "ghost_vendor", display_name: "Ghost Vendor", story: "", target_amount: 5000, day_launched: 1, outcome: "extracted", amount_extracted: 5000, detected_day: null },
      { attack_id: "a2", scheme_id: "ghost_vendor", display_name: "Ghost Vendor", story: "", target_amount: 5000, day_launched: 2, outcome: "blocked", amount_extracted: 0, detected_day: 2 },
      { attack_id: "a3", scheme_id: "evolved:split_ghost", display_name: "Split Ghost", story: "new", target_amount: 100, day_launched: 3, outcome: "pending", amount_extracted: 0, detected_day: null },
    ]);
    expect(cat).toHaveLength(9);
    expect(cat.find((c) => c.id === "ghost_vendor")).toMatchObject({ used: 2, extracted: 5000, caught: 1, lastOutcome: "blocked" });
    expect(cat.filter((c) => c.used === 0)).toHaveLength(7);
    expect(cat[8]).toMatchObject({ id: "evolved:split_ghost", evolved: true, name: "Split Ghost" });
  });
});

describe("evolution", () => {
  it("reads the sample lineage timeline", () => {
    const tl = asTimeline(timeline, "x");
    expect(tl?.lineage_id).toBe("ln_rpt_sample");
    const red = playbookHistory(tl, "red");
    expect(red.map((e) => e.version)).toEqual([3, 2, 1, 0]);
    expect(generationEntries(tl).map((g) => g.generation)).toEqual([1, 2, 3]);
    const lines = diffLines(red[1]!.diff);
    expect(lines.some((l) => l.op === "+" && l.key === "favour")).toBe(true);
    expect(lines.some((l) => l.op === "~" && l.key === "avoid" && l.text.includes("duplicate_invoice"))).toBe(true);
  });

  it("finds the lineage of the followed episode", () => {
    id = 0;
    expect(lineageIdOf([ev("generation.started", { lineage_id: "ln_a", generation: 2 })], null, null)).toBe("ln_a");
    expect(lineageIdOf([], { id: "ep_1", lineage_id: "ln_b" }, null)).toBe("ln_b");
    expect(lineageIdOf([], { id: "ep_1" }, { episodeId: "ep_1", lineageId: "ln_c" })).toBe("ln_c");
    expect(lineageIdOf([], { id: "ep_1" }, { episodeId: "ep_2", lineageId: "ln_c" })).toBeNull();
    expect(lineageIdOf([], { id: "ep_1" }, null)).toBeNull();
  });
});

describe("printing", () => {
  it("never prints origin", () => {
    expect(scrub({ a: 1, origin: "red", nested: [{ entity_origin: "red", b: 2 }] })).toEqual({ a: 1, nested: [{ b: 2 }] });
    expect(compactJson({ origin: "red", x: "y" })).toBe('{"x":"y"}');
  });
  it("splits an MCP tool id", () => {
    expect(splitTool("mcp__ledger__list_vendors")).toEqual({ ns: "mcp__ledger__", name: "list_vendors" });
    expect(splitTool("list_vendors")).toEqual({ ns: "", name: "list_vendors" });
  });
});
