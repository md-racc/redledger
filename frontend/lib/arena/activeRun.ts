// Battlefield allows one active run at a time (contracts/ledger-api.yaml, #122/#123). Starting, resuming or stepping another episode
// while one is running answers 409 {error: "another run is active", episode_id, lineage_id}. On stage the operator runs the live
// lineage or episode, so when the site gets that 409 it should watch that run, not fail and not start another. Owner: Dev R.
//
// Pure helpers, tested (activeRun.test.ts). The feed (useFeed.ts) does the attaching.

export interface ActiveRun {
  /** the running episode, when battlefield names one */
  episodeId: string | null;
  /** the running lineage, when the active run is an evolution run: its current generation's episode is what to watch */
  lineageId: string | null;
}

/** Is this error battlefield's "another run is active"? `lib/api.ts` throws an ApiError carrying the status and the body text. */
export function parseActiveRun(err: unknown): ActiveRun | null {
  const e = err as { status?: unknown; body?: unknown } | null;
  if (!e || e.status !== 409) return null;
  let body: unknown = e.body;
  if (typeof body === "string") {
    try { body = JSON.parse(body); } catch { return null; }
  }
  const o = body as { error?: unknown; episode_id?: unknown; lineage_id?: unknown } | null;
  if (!o || o.error !== "another run is active") return null;
  return { episodeId: typeof o.episode_id === "string" ? o.episode_id : null, lineageId: typeof o.lineage_id === "string" ? o.lineage_id : null };
}

interface LineageLike {
  status?: string;
  current_generation?: number;
  generations?: { generation: number; episode_id?: string | null; status?: string }[];
}

/** The episode of a lineage that is on stage now: the generation that is running, else the current one, else the latest with an episode. */
export function currentEpisodeOfLineage(l: LineageLike | null | undefined): string | null {
  const gens = (l?.generations ?? []).filter((g) => !!g.episode_id);
  if (!gens.length) return null;
  const running = gens.filter((g) => g.status === "running");
  if (running.length) return running[running.length - 1].episode_id!;
  const current = gens.find((g) => g.generation === l?.current_generation);
  return (current ?? gens[gens.length - 1]).episode_id!;
}

/** Is the lineage still going? (a finished, failed or paused lineage has nothing more to follow) */
export const lineageIsLive = (l: LineageLike | null | undefined): boolean => l?.status === "running";
