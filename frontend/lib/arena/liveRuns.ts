// The recorded live-red runs (docs/recordings, #136), summarised by tools/gen-live-runs.mjs into public/mocks/live-runs.json. Owner: Dev R.
//
// The 90-second show plays the mock-agent recording (richer to watch: every scheme, a decision to make). These are the real runs it stands in
// for: the same seed for ten days with the controller off and on, red live on Droid. The Compare card's "Real run" tab shows them so the
// numbers the pitch says out loud ("about ten thousand lost, about eighteen hundred") are on screen too.
import type { Score } from "../types";

export interface LiveRun {
  episode_id: string;
  mode: "off" | "shadow" | "enforce";
  seed: number;
  days: number;
  score: Score;
  /** cumulative, one row per day */
  by_day: { day: number; extracted: number; blocked: number }[];
  attacks: { day: number; scheme_id: string; display_name: string; target_amount: number }[];
  escalations: { opened: number; timed_out: number };
  red_credits: number;
}

export interface LiveRuns {
  recorded: string;
  where: string;
  note: string;
  source: string;
  runs: { off: LiveRun; enforce: LiveRun };
}

let cached: Promise<LiveRuns | null> | null = null;

/** The summary, fetched once; null if it cannot be read (the tab then says so). */
export function loadLiveRuns(): Promise<LiveRuns | null> {
  cached ??= fetch("/mocks/live-runs.json")
    .then((r) => (r.ok ? (r.json() as Promise<LiveRuns>) : null))
    .catch(() => null)
    .then((v) => { if (!v) cached = null; return v; });
  return cached;
}

/** "10 duplicate invoices" style tally of what red launched, most common first. */
export function schemeMix(run: LiveRun): { name: string; n: number }[] {
  const by = new Map<string, { name: string; n: number }>();
  for (const a of run.attacks) {
    const cur = by.get(a.scheme_id) ?? { name: a.display_name || a.scheme_id, n: 0 };
    cur.n++;
    by.set(a.scheme_id, cur);
  }
  return [...by.values()].sort((a, b) => b.n - a.n);
}

/** One plain sentence about how the controller-on run went, from the numbers. */
export function enforceStory(run: LiveRun): string {
  const mix = schemeMix(run);
  const top = mix[0];
  const parts = [`Red launched ${run.attacks.length} attacks${top && top.n > 1 ? `, ${top.n} of them ${top.name.toLowerCase()}s` : ""}.`];
  parts.push(`${run.score.attacks_caught} ${run.score.attacks_caught === 1 ? "was" : "were"} caught.`);
  if (run.escalations.opened > 0) parts.push(`Blue sent ${run.escalations.opened} bank ${run.escalations.opened === 1 ? "change" : "changes"} to a person; nobody answered, so ${run.escalations.timed_out === run.escalations.opened ? "each was" : `${run.escalations.timed_out} were`} blocked.`);
  return parts.join(" ");
}
