// Single event reducer: every UI view derives from this state. Owner: Dev R.
// WebSocket, REST catch-up, and fixture replay all feed the same function.
import type { Agent, RLEvent, UIState } from "./types";

export const initialState = (): UIState => ({
  episodeId: null,
  controllerMode: "shadow",
  days: 10,
  currentDay: 0,
  finished: false,
  score: { dollars_extracted: 0, dollars_blocked: 0, false_positive_cost: 0, detection_latency_days: null, attacks_launched: 0, attacks_caught: 0, legit_blocked: 0, legit_processed: 0 },
  attacks: {},
  verdicts: [],
  escalations: {},
  flags: [],
  frozenVendors: {},
  reports: [],
  thinking: {},
  toolCalls: [],
  turns: [],
  custom: [],
  lastEventId: 0,
  errors: [],
});

export function reduce(s: UIState, e: RLEvent): UIState {
  if (e.id <= s.lastEventId && !e.replay) return s; // idempotent on catch-up
  const p = e.payload as any;
  const next: UIState = { ...s, lastEventId: Math.max(s.lastEventId, e.id), episodeId: s.episodeId ?? e.episode_id };
  switch (e.type) {
    case "episode.started":
      return { ...next, controllerMode: p.controller_mode, days: p.days, currentDay: 0, finished: false };
    case "episode.ended":
      return { ...next, finished: true, score: p.final_score ?? s.score };
    case "controller.changed":
      return { ...next, controllerMode: p.to };
    case "day.started":
      return { ...next, currentDay: p.day };
    case "turn.started":
      return { ...next, turns: [...s.turns, { agent: p.agent, day: e.day, started: true, ended: false }] };
    case "turn.ended": {
      const turns = s.turns.map((t) => (t.agent === p.agent && t.day === e.day && !t.ended ? { ...t, ended: true, ok: p.ok, summary: p.summary, duration_sec: p.duration_sec, factory_credits: p.factory_credits } : t));
      return { ...next, turns };
    }
    case "attack.launched":
      return { ...next, attacks: { ...s.attacks, [p.attack_id]: { ...p, day_launched: e.day, outcome: "pending", amount_extracted: 0, detected_day: null } } };
    case "attack.outcome": {
      const a = s.attacks[p.attack_id];
      return a ? { ...next, attacks: { ...s.attacks, [p.attack_id]: { ...a, outcome: p.outcome, amount_extracted: p.amount_extracted, detected_day: p.detected_day ?? null } } } : next;
    }
    case "agent.thinking": {
      const key = `${e.agent}:${e.day}`;
      return { ...next, thinking: { ...s.thinking, [key]: (s.thinking[key] ?? "") + (p.text ?? "") } };
    }
    case "agent.tool_call":
      return { ...next, toolCalls: [...s.toolCalls, { agent: e.agent as Agent, day: e.day, tool: p.tool, args: p.args, tool_use_id: p.tool_use_id }] };
    case "agent.tool_result":
      return { ...next, toolCalls: s.toolCalls.map((c) => (c.tool_use_id === p.tool_use_id ? { ...c, ok: p.ok, summary: p.summary } : c)) };
    case "gate.verdict":
      return { ...next, verdicts: [...s.verdicts, { ...p, day: e.day }] };
    case "escalation.opened":
      return { ...next, escalations: { ...s.escalations, [p.escalation_id]: { ...p, status: "open" } } };
    case "escalation.resolved": {
      const esc = s.escalations[p.escalation_id];
      return esc ? { ...next, escalations: { ...s.escalations, [p.escalation_id]: { ...esc, status: p.decision, by: p.by } } } : next;
    }
    case "flag.raised":
      return { ...next, flags: [...s.flags, { ...p, day: e.day }] };
    case "vendor.frozen":
      return { ...next, frozenVendors: { ...s.frozenVendors, [p.vendor_id]: p.reason ?? "" } };
    case "vendor.unfrozen": {
      const { [p.vendor_id]: _, ...rest } = s.frozenVendors;
      return { ...next, frozenVendors: rest };
    }
    case "report.posted":
      return { ...next, reports: [...s.reports, { report_id: p.report_id, day: p.day }] };
    case "score.updated":
      return { ...next, score: p };
    case "error":
      return { ...next, errors: [...s.errors, p] };
    default:
      if (e.type.startsWith("x.")) return { ...next, custom: [...s.custom, e] };
      return next;
  }
}

export const openEscalations = (s: UIState) => Object.values(s.escalations).filter((e) => e.status === "open");
export const attacksByDay = (s: UIState) => Object.values(s.attacks).sort((a, b) => a.day_launched - b.day_launched);
export const blockedVerdicts = (s: UIState) => s.verdicts.filter((v) => v.verdict !== "allow");
