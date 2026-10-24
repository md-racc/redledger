// Shared timing for the holographic scenery: it powers up with the tour.
import { useArena } from "@/lib/arena/store";
import { timeline } from "@/lib/arena/timeline";

export const smooth = (a: number, b: number, x: number) => {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a)));
  return t * t * (3 - 2 * t);
};

/** 0 while the title is up, ramping in as the tour starts, 1 in the arena: the holograms power up with the tour. */
export function presence(): number {
  const st = useArena.getState();
  if (st.stage === "arena") return 1;
  if (st.stage !== "scroll") return 0;
  return smooth(0.03, 0.16, timeline.rail);
}
