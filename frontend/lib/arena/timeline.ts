// Per-frame experience clock shared between the camera rig (writer) and the DOM overlays (readers).
// Mutated every frame; overlays subscribe and write CSS variables directly, so React never re-renders at 60 Hz.

import { COMPANY } from "../company";

export interface Timeline {
  /** 0..1 progress of the auto-playing intro flight */
  intro: number;
  /** 0..1 smoothed page scroll */
  scroll: number;
  /** 0..1 camera position along the rail: scroll passed through the pacing curve (lib/arena/pacing.ts) */
  rail: number;
  /** 1 when the rail has landed and the free orbit is live, eased */
  arena: number;
  /** seconds since the intro started */
  introTime: number;
  /** where the gap between the words "red" and "ledger" is centred, as a fraction of the screen width (0.5 = middle) */
  gapX: number;
  /** length of the intro flight, seconds (the show shortens it) */
  introLen: number;
}

export const timeline: Timeline = { intro: 0, scroll: 0, rail: 0, arena: 0, introTime: 0, gapX: 0.5, introLen: 7.5 };

type Listener = (t: Timeline) => void;
const listeners = new Set<Listener>();

export const subscribeTimeline = (fn: Listener): (() => void) => {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
};
export const emitTimeline = () => listeners.forEach((fn) => fn(timeline));

/** the intro flight: long enough to land the title, short enough for a 90-second budget */
export const INTRO_SECONDS = 7.5;
/** the show's flight (beat "open") */
export const SHOW_INTRO_SECONDS = 5.8;

/**
 * Chapters along the scroll rail: where each one's caption is centred. The rail (CameraRig.tsx RAIL) is a spline through nine poses,
 * so pose k sits at rail position k / 8: each chapter is set exactly on its pose (the guards at pose 2, the clients at 4, the
 * fraudsters at 6). The guards chapter used to sit at 0.2, 40% of the way from the guards' pose to the next one, so the camera was
 * mid-flight behind the colonnade's roof blocks when it was meant to be looking at them.
 */
export const CHAPTERS = [
  { at: 0.0, no: "I", title: "The Palace", line: "Every dollar passes through this rotunda.", body: "A 1915 exhibition hall rebuilt in concrete, now the arena. Every dollar in the ledger passes through its rotunda." },
  { at: 2 / 8, no: "II", title: "The Guards", line: "Ten guards stand at the gate.", body: "Ten guards stand between the clerk and the ledger, one for each of blue's main rules. Click any of them." },
  { at: 4 / 8, no: "III", title: "The Clients", line: "Twelve counterparties: paid, and robbed.", body: `${COMPANY.name}' vendors and staff: the ones being paid, and the ones being robbed.` },
  { at: 6 / 8, no: "IV", title: "The Fraudsters", line: "Eight on the wall. All built.", body: "Eight fraudsters on the wall, a scheme built for each. One mission: get money out the door before the controller notices." },
  { at: 1.0, no: "V", title: "The Arena", line: "Everyone converges.", body: "Everyone converges on the rotunda floor. Run the episode and watch the ledger decide." },
] as const;

// The show and pitch mode both shorten the flight. Whoever set it last owns it, and only the owner puts it back, so stopping one never
// undoes the other's (the show's effect that resets it on "off" used to run right after pitch mode had shortened it).
let introOwner: string | null = null;
/** shorten (or lengthen) the flight for `owner` */
export function claimIntroLen(owner: string, seconds: number) { introOwner = owner; timeline.introLen = seconds; }
/** back to the normal flight, if `owner` still holds it */
export function releaseIntroLen(owner: string) {
  if (introOwner !== owner) return;
  introOwner = null;
  timeline.introLen = INTRO_SECONDS;
}
