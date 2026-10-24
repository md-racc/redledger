// Event + score types mirroring contracts/events.md. Owner: Dev R (consumer) / contracts (shape).
// Run `npm run gen:api` to regenerate lib/api.gen.d.ts from contracts/ledger-api.yaml for REST types.

export type Agent = "red" | "green" | "blue" | "battlefield" | "human";
export type ControllerMode = "off" | "shadow" | "enforce";
export type Verdict = "allow" | "block" | "escalate";

export interface RLEvent<P = Record<string, unknown>> {
  id: number;
  ts: string;
  episode_id: string;
  day: number;
  type: string;
  agent: Agent | null;
  payload: P;
  replay?: boolean;
}

export interface Score {
  dollars_extracted: number;
  dollars_blocked: number;
  false_positive_cost: number;
  detection_latency_days: number | null;
  attacks_launched: number;
  attacks_caught: number;
  legit_blocked: number;
  legit_processed: number;
}

export interface Attack {
  attack_id: string;
  scheme_id: string;
  display_name: string;
  story: string;
  target_amount: number;
  day_launched: number;
  outcome: "pending" | "extracted" | "partial" | "blocked" | "flagged" | "failed";
  amount_extracted: number;
  detected_day: number | null;
}

export interface VerdictCard {
  verdict_id: string;
  day: number;
  agent: string;
  action: string;
  entity_type?: string | null;
  entity_id?: string | null;
  amount?: number | null;
  verdict: Verdict;
  reason: string;
  confidence?: number | null;
  rules_fired: string[];
  enforced: boolean;
}

export interface Escalation {
  escalation_id: string;
  verdict_id: string;
  action: string;
  amount?: number | null;
  reason: string;
  expires_at: string;
  status: "open" | "approve" | "block" | "timeout";
  by?: string;
}

export interface Flag {
  flag_id: string;
  day: number;
  entity_type: string;
  entity_id: string;
  severity: "low" | "medium" | "high";
  reason: string;
}

export interface TurnInfo {
  agent: Agent;
  day: number;
  started: boolean;
  ended: boolean;
  ok?: boolean;
  summary?: string;
  duration_sec?: number;
  factory_credits?: number | null;
}

export interface UIState {
  episodeId: string | null;
  controllerMode: ControllerMode;
  days: number;
  currentDay: number;
  finished: boolean;
  score: Score;
  attacks: Record<string, Attack>;
  verdicts: VerdictCard[];
  escalations: Record<string, Escalation>;
  flags: Flag[];
  frozenVendors: Record<string, string>;
  reports: { report_id: string; day: number }[];
  thinking: Record<string, string>; // key `${agent}:${day}`
  toolCalls: { agent: Agent; day: number; tool: string; args: unknown; tool_use_id: string; ok?: boolean; summary?: string }[];
  turns: TurnInfo[];
  /** team-defined `x.<area>.<name>` events, kept verbatim for generic rendering */
  custom: RLEvent[];
  lastEventId: number;
  errors: { where: string; message: string }[];
}
