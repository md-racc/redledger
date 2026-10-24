// Scripted event streams: a list of events with times, played by a clock we control. Owner: Dev R.
//
// Both the 90-second show and the free-play replay feed the arena the same way a live socket would (one `RLEvent` at a
// time), but from a script, so the timing is ours: the story beats get the room the 3D scene needs, the quiet
// bookkeeping flies by, and pausing the show pauses the world. A script can also stop and wait for a human, which is how a
// scripted escalation hands the decision to whoever is watching.
import type { RLEvent, Score } from "../types";

export interface ScriptCtx {
  /** human decisions by escalation id, written by the UI (or by a hold timing out) */
  decisions: Record<string, "approve" | "block" | "timeout">;
  /** the score as the arena shows it right now, for items that build an event from it */
  getScore?: () => Score;
}

export interface ScriptItem {
  /** ms from the start of the script (the runner's own clock, which a hold stops) */
  at: number;
  e: RLEvent;
  /** build the event at emit time instead of using `e` (a score that depends on what happened before it) */
  build?: (ctx: ScriptCtx) => RLEvent;
  /** skip this item at emit time unless it returns true (used for the two outcomes of a human decision) */
  when?: (ctx: ScriptCtx) => boolean;
  /** after emitting this item, stop the clock until `until` is true; after `maxMs` call `timeout` and carry on */
  hold?: { until: (ctx: ScriptCtx) => boolean; maxMs: number; timeout: (ctx: ScriptCtx, emit: (e: RLEvent) => void) => void };
}

export class ScriptRunner {
  private i = 0;
  private t = 0;
  private held: { item: ScriptItem; ms: number } | null = null;
  readonly items: ScriptItem[];

  constructor(items: ScriptItem[], private emit: (e: RLEvent) => void, readonly ctx: ScriptCtx = { decisions: {} }) {
    // stable by time: equal times keep their written order
    this.items = items.map((it, k) => ({ it, k })).sort((a, b) => a.it.at - b.it.at || a.k - b.k).map((x) => x.it);
  }

  get done(): boolean { return this.i >= this.items.length && !this.held; }
  get elapsed(): number { return this.t; }
  get holding(): boolean { return !!this.held; }
  /** the length of the script without any hold, ms */
  get length(): number { return this.items.length ? this.items[this.items.length - 1].at : 0; }

  /** Move the clock on by `dtMs` and emit everything that became due. Returns how many events went out. */
  advance(dtMs: number): number {
    let sent = 0;
    if (this.held) {
      const { item } = this.held;
      this.held.ms += dtMs;
      if (item.hold!.until(this.ctx)) this.held = null;
      else if (this.held.ms >= item.hold!.maxMs) { item.hold!.timeout(this.ctx, this.emit); this.held = null; }
      else return 0;
    }
    this.t += dtMs;
    while (this.i < this.items.length && this.items[this.i].at <= this.t) {
      const it = this.items[this.i++];
      if (it.when && !it.when(this.ctx)) continue;
      this.emit(it.build ? it.build(this.ctx) : it.e);
      sent++;
      if (it.hold && !it.hold.until(this.ctx)) {
        this.held = { item: it, ms: 0 };
        break;
      }
    }
    return sent;
  }

  /** Emit everything that is left, in order, ignoring time and holds (a skip). */
  flush(): number {
    let sent = 0;
    this.held = null;
    while (this.i < this.items.length) {
      const it = this.items[this.i++];
      if (it.when && !it.when(this.ctx)) continue;
      this.emit(it.build ? it.build(this.ctx) : it.e);
      sent++;
    }
    return sent;
  }
}

/**
 * Spread a recorded episode over `windowMs`, in order. Each event gets a weight (how long the arena needs before the next
 * thing happens) and the weights are scaled to fill the window: a fraud attempt needs a few seconds for the fraudster to
 * walk up and work the client, an outcome needs a few more for the guard to run it down, bookkeeping needs none.
 */
export function schedule(events: RLEvent[], windowMs: number, weight: (e: RLEvent) => number = storyWeight): ScriptItem[] {
  const total = events.reduce((n, e) => n + weight(e), 0) || 1;
  let acc = 0;
  return events.map((e) => {
    const at = (acc / total) * windowMs;
    acc += weight(e);
    return { at, e: { ...e, replay: true } };
  });
}

/** Seconds-ish of 3D time each event type is worth (only the ratios matter: `schedule` rescales them). */
export function storyWeight(e: RLEvent): number {
  const p = e.payload as { verdict?: string };
  switch (e.type) {
    case "day.started": return 0.5;
    case "attack.launched": return 2.4;
    case "attack.outcome": return 2.2;
    case "gate.verdict": return p.verdict === "allow" ? 0.02 : 0.5;
    case "flag.raised": return 0.3;
    case "vendor.frozen": return 0.3;
    case "escalation.opened": return 0.2;
    case "episode.ended": return 0.6;
    default: return 0.02;
  }
}
