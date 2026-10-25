// The dossier's Runtime rows: model from /health (as prod answers it), credits from turn.ended, green honestly keyless.
import { describe, expect, it } from "vitest";
import { initialState } from "../reducer";
import type { TurnInfo, UIState } from "../types";
import { buildDetails, formatValue } from "./details";
import { BLUE_ROSTER, GREEN_ROSTER } from "./roster";
import { creditsLabel, creditsOf, modelLabel, runtimeFromHealth } from "./runtime";

// GET /api/bf/health on prod, 2026-10-25
const PROD_HEALTH = { ok: true, db: true, agents: {
  red: { ok: true, agent: "red", model: "gpt-5.4-mini", droid_ok: true, dry_run: false },
  green: { ok: true, agent: "green", model: "gpt-5.4-mini", droid_ok: false, dry_run: true },
  blue: { ok: true, agent: "blue", model: "gpt-5.4-mini", droid_ok: true, dry_run: false },
} };

const turn = (agent: TurnInfo["agent"], day: number, factory_credits: number | null): TurnInfo => ({ agent, day, started: true, ended: true, ok: true, summary: `${agent} day ${day}`, factory_credits });
const state = (turns: TurnInfo[], currentDay = 1): UIState => ({ ...initialState(), episodeId: "ep_x", currentDay, turns });
const row = (id: string, s: UIState, key: string, runtime = runtimeFromHealth(PROD_HEALTH)) => {
  const d = buildDetails(id, s, { runtime })!;
  const f = d.sections.flatMap((x) => x.fields).find((x) => x.key === key)!;
  return formatValue(f);
};

describe("agent runtime", () => {
  it("reads the model per team from the health payload", () => {
    const h = runtimeFromHealth(PROD_HEALTH)!;
    expect(modelLabel(h.red)).toBe("gpt-5.4-mini");
    expect(modelLabel(h.blue)).toBe("gpt-5.4-mini");
    expect(modelLabel(h.green)).toBe("keyless (DRY_RUN)");
    expect(modelLabel({ ok: true, model: "m", droid_ok: false, dry_run: false })).toBe("m · Droid unavailable");
    expect(modelLabel(undefined)).toBeUndefined();
    expect(runtimeFromHealth({ ok: false })).toBeNull();
  });

  it("sums factory credits from turn.ended, per team, with today's share", () => {
    const s = state([turn("red", 0, 120.5), turn("red", 1, 80), turn("blue", 1, 40), turn("green", 1, null)]);
    expect(creditsOf(s, "red")).toEqual({ total: 200.5, turns: 2, reported: 2, today: 80 });
    expect(creditsLabel(creditsOf(s, "red"), { dry_run: false })).toBe("201 over 2 turns · 80 today");
    expect(creditsLabel(creditsOf(s, "green"), { dry_run: true })).toBe("0 · keyless (DRY_RUN), 1 turn");
    expect(creditsLabel(creditsOf(s, "green"), undefined)).toBe("none reported (1 turn)");
    expect(creditsLabel(null, undefined)).toBeUndefined();
  });

  it("fills the dossier's model and credits for every team; green says keyless", () => {
    const s = state([turn("red", 1, 75), turn("green", 1, null), turn("blue", 1, 30)]);
    expect(row("red:ghost_vendor", s, "model")).toBe("gpt-5.4-mini");
    expect(row("red:ghost_vendor", s, "credits")).toBe("75 over 1 turn · 75 today");
    const blueId = BLUE_ROSTER[0].id;
    expect(row(blueId, s, "model")).toBe("gpt-5.4-mini");
    expect(row(blueId, s, "credits")).toBe("30 over 1 turn · 30 today");
    const greenId = GREEN_ROSTER[0].id;
    expect(row(greenId, s, "model")).toBe("keyless (DRY_RUN)");
    expect(row(greenId, s, "credits")).toBe("0 · keyless (DRY_RUN), 1 turn");
  });

  it("without /health (mock mode, offline) the model stays a placeholder naming its source", () => {
    const d = buildDetails("red:ghost_vendor", state([]), {})!;
    const f = d.sections.flatMap((x) => x.fields).find((x) => x.key === "model")!;
    expect(formatValue(f)).toBeNull();
    expect(f.source).toBe("GET /health → agents.red.model");
  });
});
