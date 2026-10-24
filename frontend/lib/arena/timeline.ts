// Per-frame experience clock shared between the camera rig (writer) and the DOM overlays (readers).
// Mutated every frame; overlays subscribe and write CSS variables directly, so React never re-renders at 60 Hz.

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

/** Chapters along the scroll rail: where each one's caption is centred. */
export const CHAPTERS = [
  { at: 0.0, no: "I", title: "The Palace", line: "Every dollar passes through this rotunda.", body: "A 1915 exhibition hall rebuilt in concrete, now the arena. Every dollar in the ledger passes through its rotunda." },
  { at: 0.2, no: "II", title: "The Guards", line: "Ten rules gate every payment.", body: "Ten gate rules stand between the clerk and the ledger. Each one is a person you can click." },
  { at: 0.43, no: "III", title: "The Clients", line: "Twelve counterparties: paid, and robbed.", body: "Coastal Supply Co.'s vendors and staff: the ones being paid, and the ones being robbed." },
  { at: 0.71, no: "IV", title: "The Fraudsters", line: "Eight schemes. One mission.", body: "Eight schemes, one mission: get money out the door before the controller notices." },
  { at: 1.0, no: "V", title: "The Arena", line: "Everyone converges.", body: "Everyone converges on the rotunda floor. Run the episode and watch the ledger decide." },
] as const;
