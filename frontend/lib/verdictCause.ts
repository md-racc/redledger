// Why the gate returned a verdict: one of blue's controls, or battlefield's fail-safe. Owner: Dev R.
//
// contracts/events.md: `gate.verdict` and `escalation.opened` carry `cause?: "control" | "gate_unavailable"`.
// `gate_unavailable` means blue timed out or failed and battlefield applied its default (escalate in enforce, allow in
// shadow; an unanswered escalation then times out as a block). That is not a catch, so it must never read as one.
// Events recorded before `cause` existed are classified the way battlefield derives it: the fallback fires `gate_timeout`
// (battlefield/app/gate/gatekeeper.py).

export type VerdictCause = "control" | "gate_unavailable";

/** the rule id battlefield puts on its fallback verdict */
export const FAIL_SAFE_RULE = "gate_timeout";

export function verdictCause(p: { cause?: unknown; rules_fired?: unknown } | null | undefined): VerdictCause {
  if (!p) return "control";
  if (p.cause === "gate_unavailable" || p.cause === "control") return p.cause;
  return Array.isArray(p.rules_fired) && p.rules_fired.includes(FAIL_SAFE_RULE) ? "gate_unavailable" : "control";
}

export const isFailSafe = (p: { cause?: unknown; rules_fired?: unknown } | null | undefined): boolean => verdictCause(p) === "gate_unavailable";

/** The headline for a fail-safe verdict or escalation: "Blocked by fail-safe: controller unreachable". */
export function failSafeLabel(verdict: unknown): string {
  const how = verdict === "allow" ? "Allowed" : verdict === "escalate" ? "Held" : "Blocked";
  return `${how} by fail-safe: controller unreachable`;
}

/** One line under the label, saying plainly that this is not a detection. */
export const FAIL_SAFE_NOTE = "Blue's gate did not answer in time, so the ledger applied its default. Not a catch.";

/** The short tag a feed card or console line carries for a fail-safe verdict. */
export const FAIL_SAFE_TAG = "FAIL-SAFE";
