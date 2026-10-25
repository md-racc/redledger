// Event → one feed card, in plain English. Owner: Dev R.
//
// The same idea as battlefield's GET /fe/episodes/{ep}/feed (headline + subline per card-worthy event), composed here so
// it works for the live socket, a script and the offline simulator alike, and so every card knows which agent in the
// arena it is about (click the card, the camera goes to them).
import type { RLEvent } from "../types";
import { FAIL_SAFE_NOTE, FAIL_SAFE_TAG, failSafeLabel, isFailSafe } from "../verdictCause";
import { blueIdForRule, redIdForScheme, ROSTER_BY_ID } from "./roster";

export type CardTone = "red" | "blue" | "green" | "amber" | "ink";

export interface FeedCard {
  id: number;
  /** unique per card on screen (event ids repeat across replays of the same recording) */
  uid?: number;
  tone: CardTone;
  /** the small caps label: ATTACK, BLOCK, HUMAN … */
  tag: string;
  head: string;
  sub: string;
  /** the arena agent this is about, if any */
  agentId?: string;
  day: number;
}

export const money = (n: unknown): string => {
  const v = Number(n);
  return Number.isFinite(v) && v !== 0 ? `$${Math.round(v).toLocaleString()}` : "";
};
const nameOf = (id: string | null | undefined, fallback: string) => (id && ROSTER_BY_ID[id]?.name) || fallback;
const pretty = (s: string) => s.replace(/^learned:/, "learned ").replace(/^evolved:/, "evolved ").replace(/_/g, " ");

type P = Record<string, any>;

export function cardFor(e: RLEvent): FeedCard | null {
  const p = e.payload as P;
  const base = { id: e.id, day: e.day };
  switch (e.type) {
    case "episode.started":
      return { ...base, tone: "ink", tag: "EPISODE", head: `Episode starts · controller ${p.controller_mode}`, sub: `seed ${p.seed} · ${p.days} business days` };
    case "day.started": {
      const li = (p.legit_injected ?? {}) as P;
      return { ...base, tone: "ink", tag: `DAY ${p.day}`, head: `Day ${p.day} opens`, sub: `${li.invoices ?? 0} invoices · ${li.purchase_orders ?? 0} POs · ${li.expenses ?? 0} expenses arrive` };
    }
    case "attack.launched": {
      const id = redIdForScheme(p.scheme_id) ?? undefined;
      return { ...base, tone: "red", tag: "ATTACK", head: `${p.display_name ?? nameOf(id, p.scheme_id)} begins`, sub: `${p.story ?? ""}${money(p.target_amount) ? `  Target ${money(p.target_amount)}.` : ""}`.trim(), agentId: id };
    }
    case "gate.verdict": {
      if (p.verdict === "allow") return null;
      // blue did not answer: the ledger's default held it, no guard caught anything (lib/verdictCause.ts)
      if (isFailSafe(p)) return { ...base, tone: "ink", tag: FAIL_SAFE_TAG, head: failSafeLabel(p.verdict), sub: `${p.action}${money(p.amount) ? ` · ${money(p.amount)}` : ""} · ${FAIL_SAFE_NOTE}` };
      const rule = (p.rules_fired ?? [])[0] as string | undefined;
      const guard = rule ? blueIdForRule(rule) ?? undefined : undefined;
      const name = nameOf(guard, "Blue");
      const amt = money(p.amount);
      if (p.verdict === "escalate") return { ...base, tone: "amber", tag: "REVIEW", head: `${name} asks for a second opinion`, sub: `${p.action}${amt ? ` · ${amt}` : ""}`, agentId: guard };
      return { ...base, tone: "blue", tag: p.enforced === false ? "WOULD BLOCK" : "BLOCK", head: `${name} ${p.enforced === false ? "would have stopped" : "stopped"} ${amt || "a payment"}`, sub: `${p.action} · ${pretty((p.rules_fired ?? []).join(" + ")) || p.reason}`, agentId: guard };
    }
    case "escalation.opened":
      if (isFailSafe(p)) return { ...base, tone: "ink", tag: FAIL_SAFE_TAG, head: failSafeLabel("escalate"), sub: `${p.action}${money(p.amount) ? ` · ${money(p.amount)}` : ""} · a human decides; unanswered, it stays blocked` };
      return { ...base, tone: "amber", tag: "HUMAN", head: "Needs a human decision", sub: `${p.action}${money(p.amount) ? ` · ${money(p.amount)}` : ""} — ${p.reason}` };
    case "escalation.resolved":
      return p.decision === "approve"
        ? { ...base, tone: "red", tag: "APPROVED", head: "A human approved it", sub: `by ${p.by} — the invoice goes through` }
        : { ...base, tone: "blue", tag: p.decision === "timeout" ? "TIMEOUT" : "BLOCKED", head: p.decision === "timeout" ? "Nobody answered: blocked" : "A human blocked it", sub: `by ${p.by}` };
    case "flag.raised":
      return { ...base, tone: "blue", tag: "FLAG", head: `Blue flags a ${p.entity_type} (${p.severity})`, sub: p.reason ?? "", agentId: blueIdForRule("already_flagged_high") ?? undefined };
    case "vendor.frozen":
      return { ...base, tone: "blue", tag: "FROZEN", head: "A vendor is frozen", sub: p.reason ?? "" };
    case "attack.outcome": {
      const id = redIdForScheme(p.scheme_id) ?? undefined;
      const name = nameOf(id, p.scheme_id);
      if (p.outcome === "extracted" || p.outcome === "partial") return { ...base, tone: "red", tag: p.outcome === "partial" ? "PARTIAL" : "STOLEN", head: `${name} walks off with ${money(p.amount_extracted) || "money"}`, sub: p.detected_day != null ? `detected on day ${p.detected_day}, too late` : "nobody noticed", agentId: id };
      return { ...base, tone: "blue", tag: p.outcome === "flagged" ? "CAUGHT" : "STOPPED", head: `${name} is shut down`, sub: p.detected_day != null ? `detected on day ${p.detected_day}` : "the attempt failed", agentId: id };
    }
    case "report.posted":
      return { ...base, tone: "ink", tag: "REPORT", head: `Controller report · day ${p.day}`, sub: "Blue's end-of-day audit is filed" };
    case "controller.changed":
      return { ...base, tone: p.to === "enforce" ? "blue" : p.to === "off" ? "red" : "amber", tag: "MODE", head: `Controller ${p.from} → ${p.to}`, sub: p.to === "enforce" ? "Blocks are real now" : p.to === "shadow" ? "Verdicts recorded, nothing blocked" : "The gate is not consulted" };
    case "episode.ended": {
      const s = (p.final_score ?? {}) as P;
      return { ...base, tone: "ink", tag: "FINAL", head: "Episode over", sub: `${money(s.dollars_extracted) || "$0"} stolen · ${money(s.dollars_blocked) || "$0"} blocked · ${s.attacks_caught ?? 0}/${s.attacks_launched ?? 0} caught` };
    }
    case "agent.thinking": {
      const text = String(p.text ?? "").trim();
      if (!text) return null;
      const tone: CardTone = e.agent === "red" ? "red" : e.agent === "blue" ? "blue" : e.agent === "green" ? "green" : "ink";
      return { ...base, tone, tag: `${String(e.agent ?? "agent").toUpperCase()} THINKS`, head: text.length > 96 ? `${text.slice(0, 93)}…` : text, sub: "" };
    }
    case "generation.started":
      return { ...base, tone: "amber", tag: `GEN ${p.generation}`, head: `Generation ${p.generation} begins`, sub: `playbooks: red v${p.playbook_versions?.red ?? 0} · green v${p.playbook_versions?.green ?? 0} · blue v${p.playbook_versions?.blue ?? 0}` };
    case "playbook.updated":
      return { ...base, tone: p.agent === "red" ? "red" : p.agent === "blue" ? "blue" : "green", tag: "PLAYBOOK", head: `${p.agent} rewrites its playbook (v${p.version})`, sub: p.rationale ?? "" };
    case "debrief.delivered":
      return { ...base, tone: "ink", tag: "DEBRIEF", head: `${p.agent} is debriefed`, sub: `${p.revealed_attacks ?? 0} resolved attacks revealed` };
    default:
      return null;
  }
}
