// Render quality ladder. The scene is heavy (the Palace is ~1M triangles with shadows and a post chain), so the
// canvas steps down by itself when the frame rate stays low (lib/arena/governor.ts) and `?q=0..3` pins a level for testing.
export interface Quality {
  level: 0 | 1 | 2 | 3;
  dpr: [number, number];
  shadows: boolean;
  shadowMap: number;
  /** re-render the shadow map every n-th frame (the sun is fixed; only the agents move) */
  shadowEvery: number;
  post: "full" | "lite" | "off";
}

export const QUALITY: Record<0 | 1 | 2 | 3, Quality> = {
  3: { level: 3, dpr: [1, 1.5], shadows: true, shadowMap: 2048, shadowEvery: 2, post: "full" },
  2: { level: 2, dpr: [1, 1.25], shadows: true, shadowMap: 1024, shadowEvery: 3, post: "lite" },
  1: { level: 1, dpr: [1, 1.1], shadows: true, shadowMap: 1024, shadowEvery: 6, post: "off" },
  0: { level: 0, dpr: [1, 1], shadows: false, shadowMap: 512, shadowEvery: 1, post: "off" },
};

export function initialLevel(): 0 | 1 | 2 | 3 {
  if (typeof window === "undefined") return 3;
  const q = new URLSearchParams(window.location.search).get("q");
  if (q !== null && /^[0-3]$/.test(q)) return Number(q) as 0 | 1 | 2 | 3;
  const small = window.matchMedia?.("(max-width: 760px), (pointer: coarse)").matches;
  return small ? 2 : 3;
}

export const pinnedByUrl = () => typeof window !== "undefined" && new URLSearchParams(window.location.search).has("q");
