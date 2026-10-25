// The Evolution card's two plain sentences: what red got away with, and what blue stopped, first generation to last. Pure, tested
// (evoSummary.test.ts). Nothing is estimated: each is a comparison of two scores the battlefield reported. Owner: Dev R.
import { money } from "./headlines";
import type { GenReport } from "./lineage";

const usd = (n: number) => money(n) || "$0";

export interface EvoLead {
  red: string;
  blue: string;
}

function trend(who: string, what: string, a: number, b: number, from: number, to: number): string {
  const span = `generation ${from} to generation ${to}`;
  if (a === b) return `${who} ${what} stayed at ${usd(a)} from ${span}.`;
  return `${who} ${what} went ${b > a ? "up" : "down"} from ${usd(a)} in generation ${from} to ${usd(b)} in generation ${to}.`;
}

/** Null with fewer than two finished generations to compare (the run being watched has no score of its own yet). */
export function evoLead(gens: GenReport[]): EvoLead | null {
  const done = gens.filter((g) => !g.demo);
  if (done.length < 2) return null;
  const first = done[0]!, last = done[done.length - 1]!;
  return {
    red: trend("Red's", "take", first.score.dollars_extracted, last.score.dollars_extracted, first.generation, last.generation),
    blue: trend("Blue's", "blocked total", first.score.dollars_blocked, last.score.dollars_blocked, first.generation, last.generation),
  };
}
