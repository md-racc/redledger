// The recorded live-red runs (recordings, #136), summarised by tools/gen-live-runs.mjs into public/mocks/live-runs.json. Owner: Dev R.
//
// The 90-second show plays the mock-agent recording (richer to watch: every scheme, a decision to make). These are the real runs it stands in
// for: the same seed for ten days with the controller off and on, red live on Droid. The Compare card's "Real run" tab shows them.
//
// Money lost comes from the live controls report (#207 scoring: lost = reached an attacker-controlled account), carried as
// `controls_report`. `score` is the recording's own pre-#207 scoreboard: for the controller-on run it counted $1,824.22 that was a
// decoy invoice paid into the real vendor's account, so it must not be shown as money lost. `runScore` is what the card shows.
import type { Score } from "../types";

/** Headline figures from the live controls report (`/report/<episode>`), copied by tools/gen-live-runs.mjs. */
export interface ControlsReportFigures {
  lost: number;
  to_attacker: number;
  caught: number;
  launched: number;
  blocked: number;
  fp_cost: number;
  note: string;
  source: string;
}

export interface LiveRun {
  episode_id: string;
  mode: "off" | "shadow" | "enforce";
  seed: number;
  days: number;
  /** the recording's own final scoreboard (pre-#207); prefer `runScore` */
  score: Score;
  controls_report?: ControlsReportFigures;
  /** cumulative, one row per day, from the recording's scoreboard; prefer `lostByDay` */
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

/** The score the card shows: the controls report's figures where there are some, else the recording's scoreboard. */
export function runScore(run: LiveRun): Score {
  const r = run.controls_report;
  if (!r) return run.score;
  return { ...run.score, dollars_extracted: r.lost, dollars_blocked: r.blocked, false_positive_cost: r.fp_cost, attacks_caught: r.caught, attacks_launched: r.launched };
}

/** Cumulative money lost per day, never above the controls report's total (a scoreboard figure the report rescored as no loss drops out). */
export function lostByDay(run: LiveRun): { day: number; lost: number }[] {
  const cap = runScore(run).dollars_extracted;
  return run.by_day.map((d) => ({ day: d.day, lost: Math.min(d.extracted, cap) }));
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
