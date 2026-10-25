// What an agent has been thinking, for its dossier. Owner: Dev R.
//
// agent.thinking events are deltas; the reducer concatenates them per `${agent}:${day}` (contracts/events.md). This turns that map into a
// newest-first list for one team's agent. Only red, green and blue think; a figure in the arena speaks for its team.
import type { Agent, UIState } from "../types";

export interface Thought { day: number; text: string }

/** Whitespace squeezed, so streamed text with stray newlines reads as prose. */
const tidy = (s: string) => s.replace(/\s+/g, " ").trim();

export function thoughtsOf(state: UIState, agent: Agent): Thought[] {
  const out: Thought[] = [];
  const prefix = `${agent}:`;
  for (const [key, raw] of Object.entries(state.thinking)) {
    if (!key.startsWith(prefix)) continue;
    const day = Number(key.slice(prefix.length));
    const text = tidy(raw);
    if (Number.isFinite(day) && text) out.push({ day, text });
  }
  return out.sort((a, b) => b.day - a.day);
}

/** `text` cut at a word boundary to about `max` characters, with an ellipsis; whole when it already fits. */
export function clip(text: string, max: number): string {
  if (text.length <= max) return text;
  const cut = text.slice(0, max);
  const at = cut.lastIndexOf(" ");
  return `${(at > max * 0.6 ? cut.slice(0, at) : cut).trimEnd()}…`;
}
