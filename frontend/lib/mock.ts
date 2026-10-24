// Fixture replay with no backend: NEXT_PUBLIC_MOCK=true. Owner: Dev R.
import type { RLEvent } from "./types";

const cache = new Map<string, Promise<RLEvent[]>>();

/** The recording, fetched once. Callers share the same array: treat it as read-only. */
export function loadFixture(name = "sample"): Promise<RLEvent[]> {
  let p = cache.get(name);
  if (!p) {
    p = fetch(`/mocks/${name}.jsonl`).then(async (r) => (await r.text()).split("\n").filter(Boolean).map((l) => JSON.parse(l) as RLEvent));
    p.catch(() => cache.delete(name)); // a failed fetch is retried next time
    cache.set(name, p);
  }
  return p;
}

/** Replays events with pacing; returns a cancel fn. */
export function replay(events: RLEvent[], onEvent: (e: RLEvent) => void, msPerEvent = 150): () => void {
  let i = 0;
  const t = setInterval(() => {
    if (i >= events.length) return clearInterval(t);
    onEvent({ ...events[i++], replay: true });
  }, msPerEvent);
  return () => clearInterval(t);
}
