// A live socket delivers a whole business day in one burst: the attack, its verdicts, the outcome, the report, all within
// a second. The 3D scene needs time to show each beat, so live events go through this queue, which hands them on one at a
// time with a pause after each that fits what it is. Only presentation is delayed; nothing is dropped or reordered, and
// when the queue backs up it speeds itself up rather than fall behind. Owner: Dev R.
import type { RLEvent } from "../types";

/** ms to wait after this event before the next one is shown */
export function delayAfter(e: RLEvent): number {
  const p = e.payload as { verdict?: string };
  switch (e.type) {
    case "day.started": return 450;
    case "attack.launched": return 1500;
    case "attack.outcome": return 1700;
    case "gate.verdict": return p.verdict === "allow" ? 0 : 450;
    case "flag.raised": return 350;
    case "vendor.frozen": return 350;
    case "escalation.resolved": return 500;
    case "episode.ended": return 300;
    default: return 0;
  }
}

export class Pacer {
  private q: RLEvent[] = [];
  private wait = 0;

  push(e: RLEvent) { this.q.push(e); }
  get length() { return this.q.length; }
  clear() { this.q = []; this.wait = 0; }

  /** advance the clock; emits whatever is due */
  advance(dtMs: number, emit: (e: RLEvent) => void) {
    this.wait -= dtMs;
    // behind by more than a screenful: go faster so the picture never drifts far from the truth
    const k = this.q.length > 60 ? 0.1 : this.q.length > 25 ? 0.4 : 1;
    while (this.wait <= 0 && this.q.length) {
      const e = this.q.shift()!;
      emit(e);
      this.wait = delayAfter(e) * k;
    }
  }
}
