// Builds the content of the agent modal. Owner: Dev R.
//
// Every field has a `source`: the endpoint or event the value comes from. While a value is missing the modal shows a
// placeholder naming that source, so the host (or the next dev) can see exactly what to pass in.
//
// Three ways to feed it:
//   1. live data     - derived below from the reducer state (attacks, verdicts, flags, frozen vendors)
//   2. catalogs      - `catalogs.schemes` (GET /schemes) and `catalogs.vendors` (GET /fe/episodes/{ep}/vendors)
//   3. host overrides - `<ArenaExperience agentDetails={{ "red:ghost_vendor": { story: "...", fields: { target: 1200 } } }} />`
import { BLUE_RULES, GREEN_ROSTER, RED_SCHEMES, TEAM_META, greenIdFor, ROSTER_BY_ID, blueIdForRule } from "./roster";
import type { AgentDetailOverrides, AgentDetails, DetailField, DetailSection } from "./types";
import type { Attack, UIState } from "../types";

export interface Catalogs {
  schemes?: { id: string; display_name?: string; story?: string; params_schema?: { properties?: Record<string, unknown> }; expected_impact?: { min: number; max: number } }[] | null;
  vendors?: { id: string; name?: string; category?: string; status?: string; risk_score?: number; lifetime_paid?: number; invoice_count?: number; blocked_count?: number; created_day?: number }[] | null;
}

const f = (key: string, label: string, value: DetailField["value"], source: string, kind: DetailField["kind"] = "text"): DetailField => ({ key, label, value, source, kind });
const sec = (title: string, fields: DetailField[]): DetailSection => ({ title, fields });

const OUTCOME_TONE: Record<string, "ok" | "warn" | "bad" | "idle"> = { pending: "warn", extracted: "bad", partial: "bad", blocked: "ok", flagged: "ok", failed: "ok" };

export function buildDetails(id: string, state: UIState, catalogs: Catalogs = {}, overrides: AgentDetailOverrides = {}): AgentDetails | null {
  const spec = ROSTER_BY_ID[id];
  if (!spec) return null;
  const live = state.episodeId != null;
  let d: AgentDetails;
  if (spec.team === "red") d = redDetails(id, state, catalogs, live);
  else if (spec.team === "blue") d = blueDetails(id, state, live);
  else d = greenDetails(id, state, catalogs, live);
  return applyOverrides(d, overrides[id]);
}

// ---- red: fraudsters ----------------------------------------------------------------------------------------------

function redDetails(id: string, s: UIState, c: Catalogs, live: boolean): AgentDetails {
  const key = id.slice(4);
  const def = RED_SCHEMES.find((r) => r.key === key)!;
  const cat = c.schemes?.find((x) => x.id === key);
  const attacks: Attack[] = Object.values(s.attacks).filter((a) => a.scheme_id === key).sort((a, b) => a.day_launched - b.day_launched);
  const last = attacks[attacks.length - 1];
  const caught = attacks.filter((a) => ["blocked", "flagged", "failed"].includes(a.outcome));
  const detected = attacks.filter((a) => a.detected_day != null);
  const latency = detected.length ? detected.reduce((n, a) => n + ((a.detected_day as number) - a.day_launched), 0) / detected.length : null;
  const impact = cat?.expected_impact;

  return {
    id, team: "red", role: TEAM_META.red.singular,
    title: cat?.display_name ?? def.name,
    caption: `scheme · ${key}`,
    story: cat?.story ?? last?.story ?? def.blurb,
    status: last ? { label: last.outcome, tone: OUTCOME_TONE[last.outcome] ?? "idle" } : live ? { label: "waiting", tone: "idle" } : null,
    placeholder: !live && !cat,
    sections: [
      sec("Scheme", [
        f("scheme_id", "scheme_id", key, "GET /schemes → id", "mono"),
        f("expected_impact", "Expected impact", impact ? `$${impact.min.toLocaleString()} – $${impact.max.toLocaleString()}` : undefined, "GET /schemes → expected_impact"),
        f("params", "Tunable params", cat?.params_schema?.properties ? Object.keys(cat.params_schema.properties).join(", ") || "none" : undefined, "GET /schemes → params_schema", "mono"),
      ]),
      sec("This episode", [
        f("attempts", "Attempts", live ? attacks.length : undefined, "event attack.launched", "int"),
        f("targeted", "Targeted", live ? sum(attacks, (a) => a.target_amount) : undefined, "attack.launched → target_amount", "money"),
        f("extracted", "Extracted", live ? sum(attacks, (a) => a.amount_extracted) : undefined, "attack.outcome → amount_extracted", "money"),
        f("caught", "Caught by controller", live ? caught.length : undefined, "attack.outcome → outcome", "int"),
        f("latency", "Detection latency (days)", live ? (latency == null ? "–" : latency.toFixed(1)) : undefined, "attack.outcome → detected_day"),
        f("last_attack", "Latest attack", last?.attack_id, "event attack.launched → attack_id", "mono"),
      ]),
      sec("Runtime", [
        f("model", "Droid model", undefined, "GET /health → red.model", "mono"),
        f("credits", "Factory credits (today)", undefined, "turn.ended → factory_credits", "int"),
        f("turn", "Last turn summary", s.turns.filter((t) => t.agent === "red" && t.ended).at(-1)?.summary, "turn.ended → summary"),
      ]),
    ],
  };
}

// ---- blue: guards -------------------------------------------------------------------------------------------------

function blueDetails(id: string, s: UIState, live: boolean): AgentDetails {
  const key = id.slice(5);
  const def = BLUE_RULES.find((r) => r.key === key)!;
  const mine = s.verdicts.filter((v) => (v.rules_fired ?? []).some((r) => blueIdForRule(r) === id));
  const blocks = mine.filter((v) => v.verdict === "block");
  const esc = mine.filter((v) => v.verdict === "escalate");
  const lastV = mine[mine.length - 1];
  const conf = mine.filter((v) => v.confidence != null);
  const mode = s.controllerMode;
  const tone = mode === "enforce" ? "ok" : mode === "shadow" ? "warn" : "idle";
  const sev = ["", "low", "medium", "high"][def.severity];

  return {
    id, team: "blue", role: TEAM_META.blue.singular,
    title: def.name,
    caption: `gate rule · ${key}`,
    story: def.blurb,
    status: live ? { label: mode === "off" ? "gate off" : mode === "shadow" ? "shadow · log only" : "enforcing", tone } : null,
    placeholder: !live,
    sections: [
      sec("Rule", [
        f("rule_id", "rule id", key, "blue/gate/rules.py", "mono"),
        f("severity", "Severity", `${def.severity} · ${sev}`, "blue/gate/rules.py → RuleHit.severity"),
        f("policy", "Decision policy", def.severity === 3 ? "any hit blocks" : def.severity === 2 ? "LLM judge, else escalate" : "escalate in enforce, allow in shadow", "blue/gate/engine.py"),
        f("mode", "Controller mode", live ? mode : undefined, "controller.changed → to"),
      ]),
      sec("Verdicts this episode", [
        f("fired", "Times fired", live ? mine.length : undefined, "event gate.verdict → rules_fired", "int"),
        f("blocks", "Blocks", live ? blocks.length : undefined, "gate.verdict → verdict = block", "int"),
        f("escalations", "Escalations", live ? esc.length : undefined, "gate.verdict → verdict = escalate", "int"),
        f("blocked_amount", "Dollars stopped", live ? sum(blocks, (v) => v.amount ?? 0) : undefined, "gate.verdict → amount", "money"),
        f("confidence", "Mean confidence", live && conf.length ? conf.reduce((n, v) => n + (v.confidence as number), 0) / conf.length : undefined, "gate.verdict → confidence", "percent"),
        f("last_reason", "Latest reason", lastV?.reason, "gate.verdict → reason"),
      ]),
      sec("Scorecard", [
        f("true_blocks", "True blocks", undefined, "GET /fe/episodes/{ep}/verdicts/rules (origin = red)", "int"),
        f("false_blocks", "False positives", undefined, "GET /fe/episodes/{ep}/verdicts/rules (origin = sim)", "int"),
      ]),
    ],
  };
}

// ---- green: clients -----------------------------------------------------------------------------------------------

function greenDetails(id: string, s: UIState, c: Catalogs, live: boolean): AgentDetails {
  const idx = GREEN_ROSTER.findIndex((g) => g.id === id);
  const spec = ROSTER_BY_ID[id];
  const v = c.vendors?.[idx];
  const targeted = Object.values(s.attacks).filter((a) => greenIdFor(a.attack_id) === id);
  const frozen = v ? v.id in s.frozenVendors || v.status === "frozen" : Object.keys(s.frozenVendors).some((vid) => greenIdFor(vid) === id);

  return {
    id, team: "green", role: TEAM_META.green.singular,
    title: v?.name ?? spec.name,
    caption: v ? `vendor · ${v.id}` : `client slot · ${String(idx + 1).padStart(2, "0")}`,
    story: v ? `${v.category ?? "Vendor"} counterparty of Coastal Supply Co.` : spec.blurb,
    status: frozen ? { label: "frozen", tone: "bad" } : live ? { label: v?.status ?? "active", tone: "ok" } : null,
    placeholder: !v && !live,
    sections: [
      sec("Counterparty", [
        f("name", "Name", v?.name, "GET /fe/episodes/{ep}/vendors → name"),
        f("category", "Category", v?.category, "GET /fe/episodes/{ep}/vendors → category"),
        f("ein", "EIN", undefined, "GET /entities/vendor/{id} → ein (masked)", "mono"),
        f("bank", "Bank account", undefined, "GET /entities/vendor/{id} → bank_account (masked)", "mono"),
        f("created", "Created (day)", v?.created_day, "GET /fe/episodes/{ep}/vendors → created_day", "int"),
      ]),
      sec("Books", [
        f("risk", "Risk score", v?.risk_score, "GET /fe/episodes/{ep}/vendors → risk_score", "int"),
        f("paid", "Lifetime paid", v?.lifetime_paid, "GET /fe/episodes/{ep}/vendors → lifetime_paid", "money"),
        f("invoices", "Invoices", v?.invoice_count, "GET /fe/episodes/{ep}/vendors → invoice_count", "int"),
        f("blocked", "Blocked invoices", v?.blocked_count, "GET /fe/episodes/{ep}/vendors → blocked_count", "int"),
      ]),
      sec("Exposure this episode", [
        f("targeted", "Attacks aimed here", live ? targeted.length : undefined, "event attack.launched", "int"),
        f("at_risk", "Dollars at risk", live ? sum(targeted, (a) => a.target_amount) : undefined, "attack.launched → target_amount", "money"),
        f("lost", "Dollars lost", live ? sum(targeted, (a) => a.amount_extracted) : undefined, "attack.outcome → amount_extracted", "money"),
      ]),
    ],
  };
}

// ---- helpers ------------------------------------------------------------------------------------------------------

const sum = <T,>(xs: T[], fn: (x: T) => number) => xs.reduce((n, x) => n + (fn(x) || 0), 0);

function applyOverrides(d: AgentDetails, o?: AgentDetailOverrides[string]): AgentDetails {
  if (!o) return d;
  const { fields, ...top } = o;
  const merged: AgentDetails = { ...d, ...top };
  if (fields) {
    merged.sections = d.sections.map((s) => ({ ...s, fields: s.fields.map((x) => (x.key in fields ? { ...x, value: fields[x.key] } : x)) }));
    merged.placeholder = false;
  }
  return merged;
}

export function formatValue(fld: DetailField): string | null {
  const v = fld.value;
  if (v == null || v === "") return null;
  if (typeof v === "number") {
    if (fld.kind === "money") return `$${Math.round(v).toLocaleString()}`;
    if (fld.kind === "percent") return `${Math.round(v * 100)}%`;
    return v.toLocaleString();
  }
  return String(v);
}
