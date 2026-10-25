import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import type { RLEvent } from "../types";
import { CaptionQueue, captionFor, cleanSummary, humanReason, statusFor, type Caption } from "./narration";

const ev = (type: string, payload: Record<string, unknown>, over: Partial<RLEvent> = {}): RLEvent => ({ id: 1, ts: "", episode_id: "ep_1", day: 1, type, agent: "battlefield", payload, ...over });
const recording = readFileSync(join(__dirname, "../../public/mocks/pitch-fallback.jsonl"), "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l) as RLEvent);

describe("captions", () => {
  it("numbers the days from one, out of the episode's length", () => {
    const c = captionFor(ev("day.started", { day: 1, legit_injected: { invoices: 4, purchase_orders: 3, expenses: 2 } }), 4)!;
    expect(c.text).toBe("Day 2 of 4");
    expect(c.sub).toMatch(/4 invoices, 3 purchase orders, 2 expense claims arrive/);
    expect(captionFor(ev("day.started", { day: 0 }), 0)!.text).toBe("Day 1");
  });

  it("quotes red's own summary, and only red's", () => {
    const c = captionFor(ev("turn.ended", { agent: "red", ok: true, summary: "I split $13,800.00 across 3 invoices to Acme Office Supply LLC." }))!;
    expect(c).toMatchObject({ tone: "red", quote: true, text: "I split $13,800.00 across 3 invoices to Acme Office Supply LLC." });
    expect(captionFor(ev("turn.ended", { agent: "green", ok: true, summary: "[dry-run] confirmed invoice.pay 4" }))).toBeNull();
    expect(captionFor(ev("turn.ended", { agent: "red", ok: false, summary: "turn timed out after 110 s" }))).toBeNull();
  });

  it("drops the stand-ins' tags and attack ids, and says nothing for an empty summary", () => {
    expect(cleanSummary("[mock] duplicated INV-10179 for $4,004.24 (attack atk_f40dad9ca0b3)")).toBe("duplicated INV-10179 for $4,004.24");
    expect(cleanSummary("[fake] red turn")).toBeNull();
    expect(cleanSummary(undefined)).toBeNull();
  });

  it("narrates blocks and escalations with blue's human reason, never a rule id", () => {
    const block = captionFor(ev("gate.verdict", { verdict: "block", enforced: true, action: "expenses.approve", amount: 266.4, reason: "Control hold — Employee explicitly lacks an HR onboarding record.", rules_fired: [] }))!;
    expect(block).toMatchObject({ tone: "blue", tag: "Blue blocks", text: "Control hold — Employee explicitly lacks an HR onboarding record.", sub: "Approving an expense claim · $266" });
    const dev = captionFor(ev("gate.verdict", { verdict: "block", enforced: true, action: "invoices.approve", amount: 4920, reason: "Blocked: vendor_age_lt_7d, near_threshold.", rules_fired: ["vendor_age_lt_7d", "near_threshold"] }))!;
    expect(dev.text).toBe("The vendor was only added in the last week, and this is over $1,000.");
    expect(dev.text).not.toMatch(/_/);
    const shadow = captionFor(ev("gate.verdict", { verdict: "block", enforced: false, action: "invoices.pay", reason: "Duplicate of a paid invoice." }))!;
    expect(shadow.tag).toMatch(/would block/i);
    const esc = captionFor(ev("gate.verdict", { verdict: "escalate", action: "vendor_changes.approve", amount: null, reason: "Needs independent verification — Destination change overlaps open invoices; independently verify before approval." }))!;
    expect(esc).toMatchObject({ tone: "amber", tag: "Blue asks a human" });
    expect(esc.text).toMatch(/^Needs independent verification/);
    expect(captionFor(ev("gate.verdict", { verdict: "allow", action: "invoices.pay" }))).toBeNull();
    expect(humanReason({ reason: "", rules_fired: ["some_new_rule"] })).toBe("The controller was not sure this is safe.");
  });

  it("uses the shared headline for an outcome, and says when the clock blocked an escalation", () => {
    const out = captionFor(ev("attack.outcome", { outcome: "extracted", scheme_id: "threshold_split", amount_extracted: 13800, detected_day: null }))!;
    expect(out).toMatchObject({ tone: "red", text: "Threshold Splitting walks off with $13,800" });
    const res = captionFor(ev("escalation.resolved", { escalation_id: "esc_1", decision: "block", by: "auto-block" }))!;
    expect(res.text).toMatch(/Nobody decided in time/);
    expect(captionFor(ev("escalation.resolved", { escalation_id: "esc_1", decision: "approve", by: "judge" }))!.text).toBe("A human approved it");
  });

  it("does not caption the bookkeeping, and never computes a score", () => {
    for (const t of ["score.updated", "ledger.mutation", "agent.tool_call", "agent.thinking", "episode.ended", "report.posted"]) expect(captionFor(ev(t, { text: "x", final_score: {} }))).toBeNull();
  });

  it("tells the real recording's story", () => {
    const texts = recording.map((e) => captionFor(e, 6)).filter((c): c is Caption => !!c).map((c) => c.text);
    expect(texts).toContain("Day 3 of 6");
    expect(texts).toContain("I split $13,800.00 across 3 invoices to Acme Office Supply LLC.");
    expect(texts.some((t) => t.startsWith("Needs independent verification"))).toBe(true);
    expect(texts).toContain("Ghost Employee is shut down");
  });
});

describe("the status line", () => {
  it("says whose turn it is and clears when the turn ends", () => {
    expect(statusFor(ev("turn.started", { agent: "red" }))).toMatch(/Red is planning/);
    expect(statusFor(ev("turn.ended", { agent: "red" }))).toBeNull();
    expect(statusFor(ev("gate.verdict", {}))).toBeUndefined();
  });
});

describe("CaptionQueue", () => {
  const cap = (key: string): Caption => ({ key, tone: "ink", tag: "T", text: key });
  const T = { minMs: 1000, maxMs: 3000, fastMs: 200, maxWaiting: 4 };

  it("shows the first at once and the next only after the first has been up long enough", () => {
    const q = new CaptionQueue(T);
    expect(q.push(cap("a"))).toBe(true);
    expect(q.push(cap("b"))).toBe(false);
    expect(q.advance(900)).toBe(false);
    expect(q.current?.key).toBe("a");
    expect(q.advance(200)).toBe(true);
    expect(q.current?.key).toBe("b");
  });

  it("merges the same caption in a row into a count", () => {
    const q = new CaptionQueue(T);
    q.push(cap("block"));
    expect(q.push(cap("block"))).toBe(true);
    expect(q.current?.count).toBe(2);
    q.push(cap("x"));
    q.push(cap("y"));
    q.push(cap("y"));
    q.advance(1000);
    q.advance(1000);
    expect(q.current).toMatchObject({ key: "y", count: 2 });
  });

  it("speeds up when captions pile up, and keeps only the newest few", () => {
    const q = new CaptionQueue(T);
    for (const k of ["a", "b", "c", "d", "e", "f", "g"]) q.push(cap(k));
    expect(q.waiting).toBe(4);
    q.advance(200);
    expect(q.current?.key).toBe("d"); // b and c were dropped
  });

  it("clears the screen when nothing follows", () => {
    const q = new CaptionQueue(T);
    q.push(cap("a"));
    expect(q.advance(3000)).toBe(true);
    expect(q.current).toBeNull();
  });
});
