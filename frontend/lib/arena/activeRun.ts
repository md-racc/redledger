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

// ---- joining the current run on load ---------------------------------------------------------------------------------
// Every window (arena, backstage, /ops) shows the run that is going, whoever started it, and a viewer never starts one. These are the
// pieces they share: what "the current run" is, and which failures mean the backend is really gone (only then the recording plays).

/** What a window should be watching: the running episode, or the current generation of a running lineage. */
export interface CurrentRun {
  episodeId: string;
  lineageId: string | null;
}

interface EpisodeLike { id?: unknown; status?: unknown; lineage_id?: unknown }

/** The active episode in a GET /episodes list: running and not a replay (replays never count as the active run; contracts). */
export function runningEpisode<T extends EpisodeLike>(list: readonly T[] | null | undefined): T | null {
  return (list ?? []).find((e) => e.status === "running" && !String(e.id).startsWith("replay_")) ?? null;
}

/** The reads `currentRun` needs (lib/api.ts in the app, a fake in tests). */
export interface RunReader {
  listEpisodes: () => Promise<EpisodeLike[]>;
  lineages: () => Promise<(LineageLike & { id?: unknown })[]>;
  lineage: (id: string) => Promise<LineageLike>;
}

/**
 * The run on stage now, or null when nothing is running. Only reads. A running episode wins; otherwise a running lineage's current
 * generation (between two generations no episode is running, but the lineage is). Throws when the backend can't be read, so callers can
 * tell "nothing is running" (null) from "no answer" (see `isUnreachable`).
 */
export async function currentRun(api: RunReader): Promise<CurrentRun | null> {
  const busy = runningEpisode(await api.listEpisodes());
  if (busy) return { episodeId: String(busy.id), lineageId: typeof busy.lineage_id === "string" ? busy.lineage_id : null };
  const lineages = await api.lineages().catch(() => []);
  const ln = (Array.isArray(lineages) ? lineages : []).find((l) => lineageIsLive(l) && typeof l.id === "string");
  if (!ln) return null;
  const id = ln.id as string;
  const detail = ln.generations?.length ? ln : await api.lineage(id).catch(() => null);
  const ep = currentEpisodeOfLineage(detail);
  return ep ? { episodeId: ep, lineageId: id } : null;
}

/** One poll of the current run: `live`/`idle` with the run, `offline` when unreachable, null for a hiccup (a 429, a 403: ask again). */
export async function readRun(api: RunReader): Promise<{ link: "live" | "idle"; run: CurrentRun | null } | { link: "offline"; run: null } | null> {
  try {
    const run = await currentRun(api);
    return { link: run ? "live" : "idle", run };
  } catch (e) {
    return isUnreachable(e) ? { link: "offline", run: null } : null;
  }
}

export interface JoinState {
  /** what the window has on screen from the battlefield: someone else's run (`attached`), or its own run / act / sandbox */
  liveKind: "run" | "act" | "sandbox" | "attached" | null;
  /** the episode on screen */
  episodeId: string | null;
  /** the episode on screen has ended */
  finished: boolean;
  /** the recording or locally played attacks are playing */
  playingLocal: boolean;
  /** following is on (the show turns it off while it plays), not paused, nothing being started */
  follow: boolean;
}

/**
 * Should a window switch to the run `found`? Yes when it has nothing of its own on screen, or watches another run that is not this
 * one (a new run, a lineage's next generation). Never over an admin's own run, act or sandbox until it has finished, nor over the
 * recording while it plays. Reading only: joining never creates anything.
 */
export function shouldJoin(found: CurrentRun | null, s: JoinState): boolean {
  if (!found || !s.follow) return false;
  if (s.liveKind === "attached") return found.episodeId !== s.episodeId;
  if (s.liveKind !== null) return s.finished;
  return !s.playingLocal;
}

/**
 * Is this failure "the backend is not there" (a network error, a timeout, a 5xx, including the proxy's 502 when it is not configured)?
 * Only then may a window fall back to the recording. A 409 (another run), a 403 (a viewer's write), a 429 or a 404 is the backend
 * answering: never a reason to play the recording instead of the live run.
 */
export function isUnreachable(err: unknown): boolean {
  if (err instanceof TypeError) return true; // fetch's network failure
  const e = err as { name?: unknown; status?: unknown } | null;
  if (e && (e.name === "TimeoutError" || e.name === "AbortError")) return true;
  return typeof e?.status === "number" && e.status >= 500;
}
