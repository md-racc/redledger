// The backend, messy: a recorded live-red run as a stream of raw update messages. Owner: Dev R.
//
// With no battlefield behind it (or `?replay=1`), the red and blue consoles replay recordings/demo-enforce-live.jsonl: red live on
// Droid for ten days, the real tool calls, ledger writes, verdicts, escalations and reasoning, about 1,200 events. Unlike the arena's show
// (lib/arena/showScripts.ts, paced for the 3D scene) this keeps the run's own rhythm, so bursts stay bursts and the pauses between turns
// stay pauses, only faster. That is what a live backend looks like.
import type { RLEvent } from "../types";
import { schedule, type ScriptItem } from "../arena/script";

export const RECORDING = "demo-enforce-live";

/** a pause longer than this, in the original run, is cut to it (a Droid turn thinking for 20 s would stall a console) */
const MAX_GAP_S = 4;

/** `events` spread over `windowMs` in proportion to the real gaps between them, in order, none at exactly the same instant. */
export function recordingScript(events: RLEvent[], windowMs: number): ScriptItem[] {
  const at = events.map((e) => Date.parse(e.ts));
  const gap = new Map<number, number>();
  events.forEach((e, i) => {
    const next = at[i + 1];
    const d = next !== undefined && Number.isFinite(next) && Number.isFinite(at[i]!) ? Math.min(MAX_GAP_S, Math.max(0, (next - at[i]!) / 1000)) : 0.05;
    gap.set(e.id, d + 0.002);
  });
  return schedule(events, windowMs, (e) => gap.get(e.id) ?? 0.05);
}
