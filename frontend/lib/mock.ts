// Fixture replay with no backend: NEXT_PUBLIC_MOCK=true. Owner: Dev R.
import type { RLEvent } from "./types";

export async function loadFixture(name = "sample"): Promise<RLEvent[]> {
  const txt = await (await fetch(`/mocks/${name}.jsonl`)).text();
  return txt.split("\n").filter(Boolean).map((l) => JSON.parse(l) as RLEvent);
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
