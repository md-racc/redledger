// Pitch mode: the main screen runs a LIVE episode instead of the 90-second show. Owner: Dev Ad (crunch).
//
//   P, ?pitch=1, or the title's "Live pitch" button (admins)
//   → the intro flight, the tour fast-forwarded, the arena
//   → join the run that is going, or (admin) start one: enforce, seed 42 (?seed=), 4 days, no attack plan (red picks its schemes)
//   → captions from the real events (narration.ts), an escalation a presenter answers within 40 s (else it is blocked)
//   → at episode.ended a closing card with the final score and the controls report
//
// With no backend (NEXT_PUBLIC_MOCK=true, or unreachable) it plays a REAL prod recording (public/mocks/pitch-fallback.jsonl,
// copied from docs/recordings/demo-enforce-redblue-live.jsonl), labelled RECORDED with its episode id and date.
//
// Pure, tested (pitch.test.ts). The React side is components/arena/usePitch.ts; the feed side is useFeed's `pitch()`.
import type { RLEvent } from "../types";
import type { CurrentRun } from "./activeRun";
import { schedule, type ScriptCtx, type ScriptItem } from "./script";
import { decisionEvent } from "./showScripts";

export const PITCH_SEED = 42;
export const PITCH_DAYS = 4;
/** an escalation nobody answers in pitch mode is blocked after this long (battlefield itself waits 90 s) */
export const PITCH_AUTOBLOCK_MS = 40_000;
/** the scroll tour, fast-forwarded */
export const PITCH_TOUR_MS = 3_400;
/** the recorded fallback, its six days spread over this long (holds for a human come on top) */
export const PITCH_FALLBACK_WINDOW_MS = 96_000;
/** the other screens on stage */
export const SIDE_SCREENS = ["red.redledger.us", "blue.redledger.us"] as const;

export interface RecordingInfo {
  /** the file under public/mocks, without .jsonl */
  fixture: string;
  episodeId: string;
  /** when it was recorded on prod, YYYY-MM-DD */
  date: string;
  /** the agents as they ran when it was recorded (docs/recordings/README.md) */
  agents: Record<"red" | "green" | "blue", { mode: "live" | "keyless"; model?: string }>;
}

/** docs/recordings/demo-enforce-redblue-live.jsonl: seed 42, 6 days, enforce, red and blue's audit live on gpt-5.4-mini, green keyless. */
export const PITCH_FALLBACK: RecordingInfo = {
  fixture: "pitch-fallback",
  episodeId: "ep_d9b561111d60",
  date: "2026-10-25",
  agents: { red: { mode: "live", model: "gpt-5.4-mini" }, green: { mode: "keyless" }, blue: { mode: "live", model: "gpt-5.4-mini" } },
};

/** `?pitch=1` starts pitch mode on load; `?seed=` overrides the seed of the episode an admin creates. */
export function pitchQuery(search: string): { on: boolean; seed: number } {
  const q = new URLSearchParams(search);
  const p = q.get("pitch");
  const s = Number.parseInt(q.get("seed") ?? "", 10);
  return { on: p === "1" || p === "true" || p === "live", seed: Number.isFinite(s) && s >= 0 ? s : PITCH_SEED };
}

export type PitchPlan = "join" | "create" | "wait" | "fallback";

/**
 * What pitch mode does once the arena is up. A running run is always joined (one active run at a time; the operator's lineage or
 * episode is the show). Otherwise an admin creates one; a viewer never does, so it waits and joins the run when the operator starts it.
 * Only a backend that is genuinely unreachable (or mock mode) plays the recording.
 */
export function planPitch(input: { mockOnly: boolean; admin: boolean; reach: "live" | "offline"; active: CurrentRun | null }): PitchPlan {
  if (input.mockOnly || input.reach === "offline") return "fallback";
  if (input.active) return "join";
  return input.admin ? "create" : "wait";
}

/** The episode pitch mode creates: no attack_plan, so red chooses its own schemes (that is when its reasoning is rich). */
export const pitchEpisode = (seed: number) => ({ controller_mode: "enforce" as const, seed, days: PITCH_DAYS });

/** Story weight of each recorded event (only the ratios matter): room for a caption after red's summary, a verdict, an outcome. */
export function pitchWeight(e: RLEvent): number {
  const p = e.payload as { verdict?: string; agent?: string };
  switch (e.type) {
    case "day.started": return 1.4;
    case "turn.started": return 0.3;
    case "turn.ended": return p.agent === "red" ? 3.4 : 0.5;
    case "attack.launched": return 2.0;
    case "attack.outcome": return 3.2;
    case "gate.verdict": return p.verdict === "allow" ? 0.03 : 1.6;
    case "escalation.opened": return 0.4;
    case "escalation.resolved": return 0.8;
    case "flag.raised": case "vendor.frozen": return 0.4;
    case "score.updated": return 0.2;
    case "report.posted": return 0.3;
    case "episode.ended": return 1;
    default: return 0.005;
  }
}

/**
 * The recorded fallback as a script. Each escalation waits for a human (its countdown restarts when it is shown); whoever decides,
 * or the auto-block, emits the decision, and the recording's own resolution (a 90 s timeout on prod) is then dropped. If nobody can
 * decide (a viewer's window), the hold ends after `holdMs` with a block. The recorded outcomes stand either way: they are what happened.
 */
export function buildPitchFallback(fixture: readonly RLEvent[], windowMs = PITCH_FALLBACK_WINDOW_MS, holdMs = PITCH_AUTOBLOCK_MS + 3000): ScriptItem[] {
  const items = schedule([...fixture], windowMs, pitchWeight);
  for (const it of items) {
    const p = it.e.payload as { escalation_id?: string };
    const id = p.escalation_id;
    if (!id) continue;
    if (it.e.type === "escalation.opened") {
      const e = it.e;
      it.build = () => ({ ...e, payload: { ...e.payload, expires_at: new Date(Date.now() + holdMs).toISOString() } });
      it.hold = {
        until: (ctx: ScriptCtx) => !!ctx.decisions[id],
        maxMs: holdMs,
        timeout: (ctx, emit) => { ctx.decisions[id] = "block"; emit(decisionEvent({ escalation_id: id, episode_id: e.episode_id, day: e.day }, "block", "auto-block")); },
      };
    } else if (it.e.type === "escalation.resolved") {
      it.when = (ctx: ScriptCtx) => !ctx.decisions[id];
    }
  }
  return items;
}

/** The one line under the pitch badge: what pitch mode is showing, in words. */
export function pitchStatus(result: "live" | "joined" | "waiting" | "recorded" | "refused" | "connecting" | null, ctx: { source: "idle" | "live" | "mock"; mockOnly: boolean; seed: number; note: string }): string | null {
  switch (result) {
    case null: return null;
    case "connecting": return "Connecting to the battlefield…";
    case "live": return `A live episode, started now · seed ${ctx.seed} · ${PITCH_DAYS} business days · red picks its own schemes`;
    case "joined": return "Joined the run already in progress";
    case "waiting": return ctx.source === "live" ? "Joined the run already in progress" : "Waiting for the operator to start the live run";
    case "recorded": return `${ctx.mockOnly ? "Mock mode" : "The backend is unreachable"}: playing a real run recorded on prod`;
    case "refused": return ctx.note;
  }
}
