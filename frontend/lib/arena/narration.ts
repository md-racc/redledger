// Pitch mode's live narration: a caption per story beat, read from the real events and nothing else. Owner: Dev Ad (crunch).
//
//   day.started          "Day 2 of 4"
//   turn.ended (red)     red's own summary: "I split $13,800.00 across 3 invoices to Acme Office Supply LLC."
//   gate.verdict         a block or an escalation, with blue's human reason (rule ids are turned into words)
//   escalation.resolved  what the human (or the clock) decided
//   attack.outcome       the headline (headlines.ts)
//   turn.started         a quiet status line: whose turn it is, so a 30 s live day never looks frozen
//
// Scores are never computed here: the overlay shows `score.updated` and `episode.ended.final_score` as they come. Events reach this
// after the pacer (useFeed), and `CaptionQueue` gives each caption time to be read. Pure, tested (narration.test.ts).
import type { RLEvent } from "../types";
import { FAIL_SAFE_NOTE, failSafeLabel, isFailSafe } from "../verdictCause";
import { ruleWhy } from "./escalation";
import { cardFor, money } from "./headlines";

export type CaptionTone = "red" | "blue" | "amber" | "green" | "ink";

export interface Caption {
  /** captions with the same key in a row are merged (three identical blocks read "×3") */
  key: string;
  tone: CaptionTone;
  /** small caps over the line: DAY, RED, BLUE BLOCKS, YOUR CALL … */
  tag: string;
  text: string;
  sub?: string;
  /** a red summary is red speaking: shown as a quote */
  quote?: boolean;
  count?: number;
}

type P = Record<string, any>;

/** "[dry-run] …", "[mock] … (attack atk_…)": the tags the stand-ins add, and ids nobody on stage needs. Null when nothing is left to say. */
export function cleanSummary(s: unknown): string | null {
  const t = String(s ?? "")
    .replace(/^\s*\[[^\]]*\]\s*/, "")
    .replace(/\s*\(attack atk_[a-z0-9]+\)\s*$/i, "")
    .replace(/\s+/g, " ")
    .trim();
  return t.length >= 12 ? t : null;
}

const ACTION_WORDS: Record<string, string> = {
  "invoices.pay": "paying an invoice",
  "invoices.approve": "approving an invoice",
  "invoices.match": "matching an invoice",
  "expenses.pay": "reimbursing an expense",
  "expenses.approve": "approving an expense claim",
  "vendor_changes.approve": "accepting new bank details",
  "gl.post": "posting to the books",
};
const actionWords = (a: unknown) => ACTION_WORDS[String(a)] ?? String(a ?? "an action").replace(/[._]/g, " ");

/** a reason written for developers: "Blocked: vendor_age_lt_7d, near_threshold." */
const DEV_REASON = /^[A-Za-z ]+:\s*[a-z0-9_]+(\s*,\s*[a-z0-9_]+)*\.?$/;

/** Blue's reason in plain words: its own sentence when it wrote one, else one sentence for the first rule that fired. */
export function humanReason(p: { reason?: unknown; rules_fired?: unknown; action?: unknown; amount?: unknown }): string {
  const raw = String(p.reason ?? "").trim();
  if (raw && !DEV_REASON.test(raw) && !/^Needs human review/i.test(raw)) return raw;
  const rules = Array.isArray(p.rules_fired) ? (p.rules_fired as string[]) : [];
  for (const r of rules) {
    const why = ruleWhy(r);
    if (why) return why;
  }
  return raw && !DEV_REASON.test(raw) ? raw : "The controller was not sure this is safe.";
}

/** The caption an event earns, or null (most events earn none). `days` is the episode's length, when known. */
export function captionFor(e: RLEvent, days = 0): Caption | null {
  const p = e.payload as P;
  switch (e.type) {
    case "day.started": {
      const d = Number(p.day ?? e.day);
      const li = (p.legit_injected ?? {}) as P;
      const bits = [li.invoices ? `${li.invoices} invoices` : "", li.purchase_orders ? `${li.purchase_orders} purchase orders` : "", li.expenses ? `${li.expenses} expense claims` : ""].filter(Boolean);
      return { key: `day:${e.episode_id}:${d}`, tone: "ink", tag: "Business day", text: days > 0 ? `Day ${d + 1} of ${days}` : `Day ${d + 1}`, sub: bits.length ? `${bits.join(", ")} arrive. Red moves first.` : undefined };
    }
    case "turn.ended": {
      if (p.agent !== "red" || p.ok === false) return null;
      const text = cleanSummary(p.summary);
      return text ? { key: `red:${e.id}`, tone: "red", tag: "Red, in its own words", text, quote: true } : null;
    }
    case "gate.verdict": {
      if (p.verdict !== "block" && p.verdict !== "escalate") return null;
      if (isFailSafe(p)) return { key: `failsafe:${p.verdict}`, tone: "ink", tag: "Fail-safe", text: failSafeLabel(p.verdict), sub: FAIL_SAFE_NOTE };
      const reason = humanReason(p);
      const amt = money(p.amount);
      const what = `${actionWords(p.action)}${amt ? ` · ${amt}` : ""}`;
      if (p.verdict === "escalate") return { key: `esc:${reason}`, tone: "amber", tag: "Blue asks a human", text: reason, sub: `${cap(what)}. A person decides, on the card.` };
      const would = p.enforced === false;
      return { key: `block:${would}:${reason}`, tone: "blue", tag: would ? "Blue would block (shadow)" : "Blue blocks", text: reason, sub: cap(what) };
    }
    case "escalation.resolved": {
      if (p.by === "auto-block") return { key: `res:${e.id}`, tone: "blue", tag: "Blocked on the clock", text: "Nobody decided in time, so it stays blocked.", sub: "An unanswered escalation is a block: the money stays put." };
      const c = cardFor(e);
      return c ? { key: `res:${e.id}`, tone: c.tone === "red" ? "red" : "blue", tag: c.tag, text: c.head, sub: c.sub } : null;
    }
    case "attack.outcome": {
      const c = cardFor(e);
      return c ? { key: `out:${e.id}`, tone: c.tone === "red" ? "red" : "blue", tag: c.tag, text: c.head, sub: c.sub } : null;
    }
    default:
      return null;
  }
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

const TURN: Record<string, string> = {
  red: "Red is planning its next scheme",
  green: "Green is working through the day's bills, every payment gated by blue",
  blue: "Blue is auditing the books",
};

/** The quiet status line: a string when an agent's turn starts, null when the turn or day ends, undefined for no change. */
export function statusFor(e: RLEvent): string | null | undefined {
  const p = e.payload as P;
  if (e.type === "turn.started") return TURN[String(p.agent)] ?? null;
  if (e.type === "turn.ended" || e.type === "day.ended" || e.type === "episode.ended") return null;
  return undefined;
}

export interface CaptionTiming {
  /** a caption stays at least this long while others wait */
  minMs: number;
  /** with nothing after it, a caption leaves after this long */
  maxMs: number;
  /** when three or more are waiting, each gets only this long */
  fastMs: number;
  /** at most this many wait; past it the oldest is dropped (a catch-up burst on joining a run must not take a minute to read) */
  maxWaiting: number;
  /**
   * Reading time: a caption with more to read stays longer than `minMs` (`baseMs` plus `perWordMs` for each word of its text and
   * sub-line), up to `maxReadMs`. Left out, every caption holds for `minMs`.
   */
  baseMs?: number;
  perWordMs?: number;
  maxReadMs?: number;
}
export const CAPTION_TIMING: CaptionTiming = { minMs: 4200, maxMs: 11_000, fastMs: 2400, maxWaiting: 4, baseMs: 1800, perWordMs: 340, maxReadMs: 13_000 };

const wordCount = (c: Caption) => `${c.text} ${c.sub ?? ""}`.split(/\s+/).filter(Boolean).length;

/** How long a caption is held while others wait: its reading time, never under `minMs`. A quote from red, or a reason from blue, is
 *  something to read (and to speak over); a bare "Day 2 of 4" is not. */
export function holdFor(c: Caption, t: CaptionTiming = CAPTION_TIMING): number {
  if (t.baseMs === undefined || t.perWordMs === undefined) return t.minMs;
  return Math.min(t.maxReadMs ?? t.maxMs, Math.max(t.minMs, t.baseMs + wordCount(c) * t.perWordMs));
}

/** One caption on screen at a time, each given time to be read; identical ones in a row are merged into a count. */
export class CaptionQueue {
  current: Caption | null = null;
  private q: Caption[] = [];
  private shown = 0;

  constructor(private t: CaptionTiming = CAPTION_TIMING) {}

  get waiting() { return this.q.length; }

  /** returns true when what is on screen changed */
  push(c: Caption): boolean {
    const last = this.q.length ? this.q[this.q.length - 1] : this.current;
    if (last && last.key === c.key) {
      const merged = { ...last, count: (last.count ?? 1) + 1 };
      if (this.q.length) { this.q[this.q.length - 1] = merged; return false; }
      this.current = merged;
      return true;
    }
    this.q.push(c);
    if (this.q.length > this.t.maxWaiting) this.q.splice(0, this.q.length - this.t.maxWaiting);
    if (!this.current) return this.next();
    return false;
  }

  /** advance the clock; returns true when what is on screen changed */
  advance(dtMs: number): boolean {
    this.shown += dtMs;
    if (!this.current) return this.q.length ? this.next() : false;
    const hold = holdFor(this.current, this.t);
    const min = this.q.length >= 3 ? Math.min(hold, this.t.fastMs) : hold;
    if (this.q.length && this.shown >= min) return this.next();
    // with nothing after it a caption lingers, and never leaves before it could be read
    if (!this.q.length && this.shown >= Math.max(this.t.maxMs, hold)) { this.current = null; return true; }
    return false;
  }

  clear() { this.current = null; this.q = []; this.shown = 0; }

  private next(): boolean {
    this.current = this.q.shift() ?? null;
    this.shown = 0;
    return true;
  }
}
