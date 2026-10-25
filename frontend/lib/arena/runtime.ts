// What each team's agent is running on, for the dossier's Runtime rows: the model from battlefield's health payload
// (`GET /api/bf/health` → agents.<team>.{model, droid_ok, dry_run}) and Factory credits summed from `turn.ended`.
// Owner: Ad.
import { useEffect, useState } from "react";
import { api } from "../api";
import type { UIState } from "../types";

export type Team = "red" | "green" | "blue";
export interface AgentRuntime { ok?: boolean; model?: string | null; droid_ok?: boolean; dry_run?: boolean }
export type RuntimeHealth = Partial<Record<Team, AgentRuntime>> | null;

/** The dossier's "Droid model" row. A keyless agent says so: its model is configured but never called. */
export function modelLabel(h: AgentRuntime | undefined): string | undefined {
  if (!h) return undefined;
  if (h.dry_run) return "keyless (DRY_RUN)";
  if (h.ok === false) return h.model ? `${h.model} · agent down` : "agent down";
  if (!h.model) return undefined;
  return h.droid_ok === false ? `${h.model} · Droid unavailable` : h.model;
}

export interface Credits { total: number; turns: number; reported: number; today: number | null }

/** Factory credits a team's agent spent this episode: the sum of its `turn.ended → factory_credits` (null when DRY_RUN). */
export function creditsOf(s: UIState, team: Team): Credits | null {
  const ended = s.turns.filter((t) => t.agent === team && t.ended);
  if (!ended.length) return null;
  const num = ended.filter((t) => typeof t.factory_credits === "number");
  const day = s.currentDay;
  const todays = num.filter((t) => t.day === day);
  return { total: num.reduce((n, t) => n + (t.factory_credits as number), 0), turns: ended.length, reported: num.length, today: todays.length ? todays.reduce((n, t) => n + (t.factory_credits as number), 0) : null };
}

/** The dossier's "Factory credits" row. */
export function creditsLabel(c: Credits | null, h: AgentRuntime | undefined): string | undefined {
  if (!c) return h?.dry_run ? "0 · keyless (DRY_RUN)" : undefined;
  if (!c.reported) return h?.dry_run ? `0 · keyless (DRY_RUN), ${c.turns} turn${c.turns === 1 ? "" : "s"}` : `none reported (${c.turns} turn${c.turns === 1 ? "" : "s"})`;
  const total = Math.round(c.total).toLocaleString();
  return `${total} over ${c.reported} turn${c.reported === 1 ? "" : "s"}${c.today != null ? ` · ${Math.round(c.today).toLocaleString()} today` : ""}`;
}

/** Pick the agents out of a health payload. */
export function runtimeFromHealth(h: unknown): RuntimeHealth {
  const agents = (h as { agents?: unknown } | null)?.agents;
  if (!agents || typeof agents !== "object") return null;
  const out: Partial<Record<Team, AgentRuntime>> = {};
  for (const t of ["red", "green", "blue"] as const) {
    const a = (agents as Record<string, unknown>)[t];
    if (a && typeof a === "object") out[t] = a as AgentRuntime;
  }
  return out;
}

const MOCK_ONLY = process.env.NEXT_PUBLIC_MOCK === "true";
const TTL_MS = 30_000;
let cached: { at: number; value: Promise<RuntimeHealth> } | null = null;

/** The agents' runtime from `/health`, fetched when `active` (the dossier is open), shared and kept 30 s. Null in mock mode or offline. */
export function useAgentRuntime(active: boolean): RuntimeHealth {
  const [h, setH] = useState<RuntimeHealth>(null);
  useEffect(() => {
    if (!active || MOCK_ONLY) return;
    let dead = false;
    if (!cached || Date.now() - cached.at > TTL_MS) {
      const value = api.health(AbortSignal.timeout(3500)).then(runtimeFromHealth, () => null);
      cached = { at: Date.now(), value };
    }
    void cached.value.then((v) => { if (!dead) setH(v); });
    return () => { dead = true; };
  }, [active]);
  return h;
}
