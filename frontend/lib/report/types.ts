// The controls assessment report: battlefield GET /api/fe/episodes/{ep}/controls (battlefield/app/api/frontend.py,
// build_controls_report). Money is in dollars. Ground truth appears only as words (fraud / legit), never as an origin key.

export type Effect = "block" | "escalate" | "note";
export type GapWhy = "no control fired" | "note only" | "escalation approved" | "audit only" | "not enforced";

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

export interface Side {
  /** distinct items the control fired on */
  n: number;
  /** their amounts (a vendor change carries none) */
  dollars: number;
  /** of those, items it blocked or escalated */
  stopped: number;
}

export interface ControlRow {
  control_id: string;
  fired: number;
  blocks: number;
  escalations: number;
  /** allowed with this rule fired */
  notes: number;
  on_fraud: Side;
  on_legit: Side;
  schemes: string[];
  effect: Effect;
  learned: boolean;
  verdict_ids: string[];
}

export interface EscalationCounts {
  approved: number;
  blocked: number;
  timeout: number;
  open: number;
}

export interface SchemeRow {
  scheme_id: string;
  display_name: string;
  attempts: number;
  first_day: number;
  targeted: number;
  extracted: number;
  outcomes: Record<string, number>;
  caught_by: string[];
  noted_by: string[];
  flags: number;
  vendors_frozen: number;
  escalations: EscalationCounts;
  detection_latency_days: number | null;
}

export interface Gap {
  scheme_id: string;
  display_name: string;
  extracted: number;
  why: GapWhy;
  controls_on_paid: string[];
  caught_elsewhere: string[];
  audit_detected: boolean;
  paid_entity_ids: string[];
}

export interface FalsePositiveItem {
  entity_type: string;
  entity_id: string;
  amount: number;
  verdict: "block" | "escalate";
  rules: string[];
  reason: string;
  day: number | null;
  enforced: boolean;
  cost: number;
  verdict_ids: string[];
}

export interface Evidence {
  scheme_id: string;
  attack_ids: string[];
  entity_ids: string[];
  verdict_ids: string[];
  escalation_ids: string[];
  flag_ids: string[];
}

export interface ControlsReport {
  episode: {
    id: string;
    seed: number | null;
    controller_mode: "off" | "shadow" | "enforce" | string;
    days: number | null;
    status: string;
    current_day: number | null;
    lineage_id: string | null;
    generation: number | null;
    created_at?: string | null;
    started_at?: string | null;
    finished_at?: string | null;
  };
  final: boolean;
  source: "ledger" | "events";
  score: Score;
  totals: { attempted: number; extracted: number; blocked: number; attacks: number; schemes: number; schemes_with_loss: number; controls_seen: number };
  gate: { allow: number; block: number; escalate: number; total: number; escalations: EscalationCounts };
  controls: ControlRow[];
  schemes: SchemeRow[];
  gaps: Gap[];
  false_positives: { cost: number; legit_blocked: number; legit_escalated: number; total_items: number; items: FalsePositiveItem[]; penalty: { rate: number; flat: number } };
  audit: { flags_raised: number; flags_on_fraud: number; flags_on_legit: number; vendors_frozen: number; fraud_vendors_frozen: number; reports: number };
  evidence: Evidence[];
}

/** One agent's model as GET /health reports it (agentkit DroidAgent.health). */
export interface AgentModel {
  agent: string;
  model: string | null;
  dry_run: boolean | null;
  ok: boolean;
}
