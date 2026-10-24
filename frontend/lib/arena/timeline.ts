// Per-frame experience clock shared between the camera rig (writer) and the DOM overlays (readers).
// Mutated every frame; overlays subscribe and write CSS variables directly, so React never re-renders at 60 Hz.

export interface Timeline {
  /** 0..1 progress of the auto-playing intro flight */
  intro: number;
  /** 0..1 smoothed scroll progress along the chapter rail */
  scroll: number;
  /** 1 when the rail has landed and the free orbit is live, eased */
  arena: number;
  /** seconds since the intro started */
  introTime: number;
}

export const timeline: Timeline = { intro: 0, scroll: 0, arena: 0, introTime: 0 };

type Listener = (t: Timeline) => void;
const listeners = new Set<Listener>();

export const subscribeTimeline = (fn: Listener): (() => void) => {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
};
export const emitTimeline = () => listeners.forEach((fn) => fn(timeline));

export const INTRO_SECONDS = 12.5;

/** Chapters along the scroll rail: where each one's caption is centred. */
export const CHAPTERS = [
  { at: 0.0, no: "01", title: "The Palace", body: "A 1915 exhibition hall rebuilt in concrete, now the arena. Every dollar in the ledger passes through its rotunda." },
  { at: 0.2, no: "02", title: "The Guards", body: "Ten gate rules stand between the clerk and the ledger. Each one is a person you can click." },
  { at: 0.43, no: "03", title: "The Clients", body: "Coastal Supply Co.'s vendors and staff: the ones being paid, and the ones being robbed." },
  { at: 0.71, no: "04", title: "The Fraudsters", body: "Eight schemes, one mission: get money out the door before the controller notices." },
  { at: 1.0, no: "05", title: "The Arena", body: "Everyone converges on the rotunda floor. Run the episode and watch the ledger decide." },
] as const;
