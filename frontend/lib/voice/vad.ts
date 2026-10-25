// Knowing when the speaker has finished, so nobody has to find the Stop button. Owner: Dev R.
//
// The recorder reports the microphone's peak level (0..1) about ten times a second. This turns that stream into one of three
// answers: keep listening, they have finished (talked, then went quiet), or nobody spoke at all. It is plain arithmetic on levels
// and a clock, so it is tested without a microphone. In a loud room the level never drops below TALKING, so it never says
// "finished": the Stop button and the 45 s limit in useVoice still work.

export const TALKING = 0.04; // a peak above this is somebody talking
export const TALKING_READS = 3; // this many readings in a row before we believe it (a click or a cough is not speech)
export const PAUSE_MS = 1600; // quiet for this long after talking means finished
export const GIVE_UP_MS = 9000; // never heard talking in this long means nobody is speaking

export type Verdict = "keep_going" | "finished" | "nobody_spoke";

export interface EndpointerOptions { talking: number; reads: number; pauseMs: number; giveUpMs: number }

export interface Endpointer {
  /** one microphone reading at wall-clock `now` (ms) */
  feed(level: number, now: number): Verdict;
  /** true once talking has been confirmed */
  readonly heard: boolean;
}

export function createEndpointer(opts: Partial<EndpointerOptions> = {}): Endpointer {
  const o: EndpointerOptions = { talking: TALKING, reads: TALKING_READS, pauseMs: PAUSE_MS, giveUpMs: GIVE_UP_MS, ...opts };
  let startedAt: number | null = null;
  let lastTalk = 0;
  let run = 0;
  let heard = false;
  return {
    get heard() { return heard; },
    feed(level, now) {
      if (startedAt === null) startedAt = now;
      if (level >= o.talking) {
        run++;
        if (run >= o.reads) { heard = true; lastTalk = now; }
      } else {
        run = 0;
      }
      if (heard) return now - lastTalk >= o.pauseMs ? "finished" : "keep_going";
      return now - startedAt >= o.giveUpMs ? "nobody_spoke" : "keep_going";
    },
  };
}
