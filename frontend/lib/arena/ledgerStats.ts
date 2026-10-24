// Per-day tallies for the ledger ring (the glowing bar wall around the arena): how many payments the gate allowed and
// blocked that day, and how many dollars the fraudsters walked away with. Derived from the reducer state only.
import type { UIState } from "../types";

export interface DayTally {
  day: number;
  allow: number;
  block: number;
  escalate: number;
  stolen: number;
}

export const MAX_DAYS = 12;

export function tallyDays(s: UIState): DayTally[] {
  if (!s.episodeId) return [];
  let last = s.currentDay;
  for (const v of s.verdicts) last = Math.max(last, v.day);
  for (const a of Object.values(s.attacks)) last = Math.max(last, a.day_launched);
  const first = Math.max(0, last - MAX_DAYS + 1);
  const out: DayTally[] = [];
  for (let d = first; d <= last; d++) out.push({ day: d, allow: 0, block: 0, escalate: 0, stolen: 0 });
  const at = (d: number) => out[d - first];
  for (const v of s.verdicts) {
    const t = at(v.day);
    if (!t) continue;
    if (v.verdict === "allow") t.allow++;
    else if (v.verdict === "block") t.block++;
    else t.escalate++;
  }
  for (const a of Object.values(s.attacks)) {
    const t = at(a.day_launched);
    if (t) t.stolen += a.amount_extracted || 0;
  }
  return out;
}

/** Bar heights (metres) for one day's three bar groups. */
export const heights = {
  allow: (n: number) => Math.min(60, 4 + 2.2 * Math.sqrt(n)),
  block: (n: number) => Math.min(60, 4 + 5 * Math.sqrt(n)),
  stolen: (dollars: number) => Math.min(70, 4 + 3.2 * Math.sqrt(dollars / 50)),
};
