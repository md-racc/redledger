// The show's clock, shared between the director (writer) and the overlays (readers). Like lib/arena/timeline.ts it is
// mutated every frame and read by subscribers that write CSS variables, so React never re-renders at 60 Hz.
import { SHOW_SECONDS } from "./show";

export const showClock = {
  /** seconds into the show */
  t: 0,
  total: SHOW_SECONDS,
  /** 0..1 across the "evolve" beat: the evolution card steps through generations on it */
  evolve: 0,
};

type Listener = (c: typeof showClock) => void;
const listeners = new Set<Listener>();
export const subscribeShowClock = (fn: Listener): (() => void) => {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
};
export const emitShowClock = () => listeners.forEach((fn) => fn(showClock));
