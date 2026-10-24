// The recorded episode, re-cut for the show. Owner: Dev R.
//
//   buildOffAct  the same attacks with no controller: nothing is gated, every attempt walks out with the money.
//                This is a projection of the recorded run (battlefield has no recorded controller-off twin of
//                sample-enforce-4d), so the show labels it "projected".
//   buildOnAct   the recorded enforce run, with one verdict turned into an escalation so a human has something to
//                decide: block it (as the recording did) or approve it and watch the fraud slip through.
//
// Both return a script (lib/arena/script.ts): events with times, optionally holding for a human.
import type { RLEvent, Score } from "../types";
import { schedule, type ScriptCtx, type ScriptItem } from "./script";

export interface ActScript {
  items: ScriptItem[];
  /** the escalation this act hands to a human, if any */
  escalationId: string | null;
}

type P = Record<string, any>;
const pay = (e: RLEvent): P => e.payload as P;
const with_ = (e: RLEvent, patch: P, extra: Partial<RLEvent> = {}): RLEvent => ({ ...e, ...extra, payload: { ...e.payload, ...patch } });

/** ids of events made here: far above anything the backend would number */
let synth = 9_000_000;
const nextId = () => ++synth;

// ---- controller off: every attack lands ---------------------------------------------------------------------------

export function projectBaseline(events: RLEvent[], episodeId = "show_off"): RLEvent[] {
  const targets = new Map<string, number>();
  let extracted = 0;
  let launched = 0;
  const baseScore = (p: P): P => ({
    ...p,
    dollars_extracted: extracted,
    dollars_blocked: 0,
    false_positive_cost: 0,
    detection_latency_days: null,
    attacks_launched: launched,
    attacks_caught: 0,
    legit_blocked: 0,
  });
  const out: RLEvent[] = [];
  for (const e of events) {
    const p = pay(e);
    switch (e.type) {
      case "gate.verdict":
      case "flag.raised":
      case "vendor.frozen":
      case "vendor.unfrozen":
      case "escalation.opened":
      case "escalation.resolved":
        continue; // the gate is never consulted, blue finds nothing in time
      case "episode.started":
        out.push(with_(e, { controller_mode: "off" }, { episode_id: episodeId }));
        break;
      case "attack.launched":
        launched++;
        targets.set(p.attack_id, Number(p.target_amount) || 0);
        out.push({ ...e, episode_id: episodeId });
        break;
      case "attack.outcome": {
        const amount = targets.get(p.attack_id) ?? 0;
        extracted += amount;
        out.push(with_(e, { outcome: "extracted", amount_extracted: amount, detected_day: null }, { episode_id: episodeId }));
        break;
      }
      case "score.updated":
        out.push(with_(e, baseScore(p), { episode_id: episodeId }));
        break;
      case "episode.ended":
        out.push(with_(e, { final_score: baseScore(p.final_score ?? {}) }, { episode_id: episodeId }));
        break;
      default:
        out.push({ ...e, episode_id: episodeId });
    }
  }
  return out;
}

export function buildOffAct(fixture: RLEvent[], windowMs: number): ActScript {
  return { items: schedule(projectBaseline(fixture), windowMs), escalationId: null };
}

// ---- controller on, with a human in the loop ----------------------------------------------------------------------

interface Escalated { escId: string; verdictIndex: number; attackId: string; amount: number; day: number }

/**
 * The first verdict, in the last attack that has one, where the near-threshold guard blocked an invoice: in the mock gate
 * that is exactly the rule that asks for review. Late in the run so the decision lands as the climax, not the opening.
 */
function pickEscalation(events: RLEvent[]): Escalated | null {
  const launches = events.map((e, i) => (e.type === "attack.launched" ? i : -1)).filter((i) => i >= 0);
  for (let k = launches.length - 1; k >= 0; k--) {
    const end = k + 1 < launches.length ? launches[k + 1] : events.length;
    for (let i = launches[k]; i < end; i++) {
      const e = events[i];
      if (e.type === "gate.verdict" && pay(e).verdict === "block" && (pay(e).rules_fired ?? []).includes("near_threshold") && Number(pay(e).amount) > 0) {
        return { escId: "esc_show_1", verdictIndex: i, attackId: pay(events[launches[k]]).attack_id, amount: Number(pay(e).amount), day: e.day };
      }
    }
  }
  return null;
}

export function buildOnAct(fixture: RLEvent[], windowMs: number, holdMs: number, episodeId = "show_on"): ActScript {
  const base = fixture.map((e) => ({ ...e, episode_id: episodeId }));
  const esc = pickEscalation(base);
  if (!esc) return { items: schedule(base, windowMs), escalationId: null };

  // block path: the verdict asks a human, the human blocks (the recorded outcome stands)
  const v = base[esc.verdictIndex];
  const vp = pay(v);
  const verdict = with_(v, { verdict: "escalate", reason: `Needs human review: ${(vp.rules_fired ?? []).join(", ")}.` });
  const opened: RLEvent = {
    id: nextId(), ts: v.ts, episode_id: episodeId, day: v.day, type: "escalation.opened", agent: "battlefield",
    payload: { escalation_id: esc.escId, verdict_id: vp.verdict_id, action: vp.action, entity_type: vp.entity_type, entity_id: vp.entity_id, amount: esc.amount, reason: `Needs human review: ${(vp.rules_fired ?? []).join(", ")}.`, expires_at: new Date(Date.now() + holdMs).toISOString() },
  };
  const events = [...base.slice(0, esc.verdictIndex), verdict, opened, ...base.slice(esc.verdictIndex + 1)];
  const openedAt = esc.verdictIndex + 1;

  // approve path: that one invoice goes through. The attack ends "partial" and the money leaves.
  let outcomeSeen = false;
  const approveOf = (e: RLEvent): RLEvent | null => {
    const p = pay(e);
    if (e.type === "attack.outcome" && p.attack_id === esc.attackId) {
      outcomeSeen = true;
      return with_(e, { outcome: "partial", amount_extracted: esc.amount, detected_day: e.day });
    }
    if (outcomeSeen && e.type === "score.updated") return with_(e, shift(p as Score, esc.amount));
    if (outcomeSeen && e.type === "episode.ended") return with_(e, { final_score: { ...(p.final_score ?? {}), ...shift((p.final_score ?? {}) as Score, esc.amount) } });
    return null;
  };

  const timed = schedule(events, windowMs);
  const guardBlock = (ctx: ScriptCtx) => ctx.decisions[esc.escId] !== "approve";
  const guardApprove = (ctx: ScriptCtx) => ctx.decisions[esc.escId] === "approve";
  const items: ScriptItem[] = [];
  timed.forEach((it, idx) => {
    const alt = idx > openedAt ? approveOf(events[idx]) : null;
    if (alt) {
      items.push({ ...it, when: guardBlock }, { at: it.at, e: { ...alt, replay: true }, when: guardApprove });
    } else {
      items.push(it);
    }
  });

  const resolved = (decision: "block" | "approve" | "timeout", by: string): RLEvent => ({
    id: nextId(), ts: new Date().toISOString(), episode_id: episodeId, day: esc.day, type: "escalation.resolved", agent: "human", replay: true,
    payload: { escalation_id: esc.escId, decision, by },
  });
  // the escalation stops the clock until a human decides; nobody deciding means the recorded block
  const openItem = items[items.findIndex((it) => it.e === timed[openedAt].e)];
  openItem.build = () => with_(openItem.e, { expires_at: new Date(Date.now() + holdMs).toISOString() }); // the countdown starts when it opens
  openItem.hold = {
    until: (ctx) => !!ctx.decisions[esc.escId],
    maxMs: holdMs,
    timeout: (ctx, emit) => { ctx.decisions[esc.escId] = "block"; emit(resolved("block", "judge")); },
  };
  return { items, escalationId: esc.escId };
}

const shift = (s: Score, amount: number): Partial<Score> => ({ dollars_extracted: (s.dollars_extracted ?? 0) + amount, dollars_blocked: Math.max(0, (s.dollars_blocked ?? 0) - amount) });

/** The event a human decision emits (the feed calls this when someone clicks Approve or Block). */
export function decisionEvent(esc: { escalation_id: string; episode_id?: string; day?: number }, decision: "approve" | "block", by = "judge"): RLEvent {
  return {
    id: nextId(), ts: new Date().toISOString(), episode_id: esc.episode_id ?? "show", day: esc.day ?? 0, type: "escalation.resolved", agent: "human", replay: true,
    payload: { escalation_id: esc.escalation_id, decision, by },
  };
}

/** The last score a stream carries. */
export function finalScoreOf(events: RLEvent[]): Score | null {
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (e.type === "episode.ended") return (e.payload as P).final_score as Score;
    if (e.type === "score.updated") return e.payload as unknown as Score;
  }
  return null;
}
