// Floating text pops ("BLOCKED", "+$4,920"). The 3D side writes world positions; the DOM layer renders them.
import type { FxTone } from "./sim";

export interface Pop {
  id: number;
  x: number;
  y: number;
  z: number;
  text: string;
  tone: FxTone;
  age: number;
  /** projected screen position, written by the 3D side every frame */
  sx: number;
  sy: number;
  onScreen: boolean;
}

export const POP_LIFE = 2.6;
export const pops: Pop[] = [];
let seq = 1;

export function addPop(p: Pick<Pop, "x" | "y" | "z" | "text" | "tone">) {
  if (pops.length >= 8) pops.shift();
  pops.push({ id: seq++, ...p, age: 0, sx: 0, sy: 0, onScreen: false });
}

export function agePops(dt: number) {
  for (let i = pops.length - 1; i >= 0; i--) {
    pops[i].age += dt;
    if (pops[i].age > POP_LIFE) pops.splice(i, 1);
  }
}

/** Screen-space anchors for the persistent labels (faction banners over the spawn groups, the hover/selection tag). */
export interface Anchor { sx: number; sy: number; on: boolean; scale: number }
const mk = (): Anchor => ({ sx: 0, sy: 0, on: false, scale: 1 });
export const anchors = { red: mk(), blue: mk(), green: mk(), tag: mk() };
