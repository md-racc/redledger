// Event director: turns the backend's event stream (contracts/events.md) into sim commands. Owner: Dev R.
//
//   episode.started / day.started   → everyone converges on the rotunda
//   attack.launched                 → the red agent for that scheme_id walks up to a client and works it
//   gate.verdict (block|escalate)   → the guard for rules_fired[0] flashes
//   attack.outcome                  → extracted: the money flows to the fraudster; blocked/flagged: a guard runs it down
//   flag.raised / vendor.frozen     → the flag guard pulses / a client freezes
//
// It only talks to `ArenaSim`, so the same code drives the live socket, the mock fixture and the demo loop.
import { blueIdForRule, greenIdFor, GREEN_ROSTER, guardForRule, RED_ROSTER, redIdForScheme } from "./roster";
import { focus } from "./focus";
import type { ArenaSim } from "./sim";
import type { AttackOutcome } from "./types";
import type { RLEvent } from "../types";
import { isFailSafe } from "../verdictCause";

/** Which gate rule most plausibly stops each scheme. Used when a block can't be tied to a verdict. */
export const SCHEME_RULE: Record<string, string> = {
  ghost_vendor: "vendor_age_lt_7d",
  bank_swap: "recent_bank_change",
  duplicate_invoice: "duplicate_invoice",
  threshold_split: "near_threshold",
  ghost_employee: "employee_bank_matches_vendor",
  expense_inflation: "recurring_drift",
  po_mismatch: "over_po_amount",
  amount_drift: "recurring_drift",
};

interface BlockNote { guardId: string; day: number }

export class Director {
  private verdictGuard = new Map<string, string>(); // verdict_id → guard id
  private escalationGuard = new Map<string, string>(); // escalation_id → guard id
  private blocks: BlockNote[] = [];
  private attackScheme = new Map<string, string>();
  private lastAllowAt = 0;

  constructor(private sim: ArenaSim, private now: () => number = () => performance.now()) {}

  handle(e: RLEvent): void {
    const p = e.payload as Record<string, any>;
    switch (e.type) {
      case "episode.started":
        this.sim.reset(); // a new episode (the show's rewind, or Run again) clears the previous one's scenes
        this.sim.converge();
        break;
      case "day.started":
        this.sim.converge();
        break;

      case "attack.launched": {
        const redId = redIdForScheme(p.scheme_id) ?? RED_ROSTER[Math.floor(hashIndex(p.attack_id, RED_ROSTER.length))].id;
        this.attackScheme.set(p.attack_id, p.scheme_id);
        this.sim.launchAttack({ attackId: p.attack_id, redId, greenId: greenIdFor(p.attack_id), amount: p.target_amount ?? null });
        break;
      }

      case "gate.verdict": {
        const rules: string[] = p.rules_fired ?? [];
        // a fail-safe verdict is no guard's catch: nobody flashes for it (lib/verdictCause.ts)
        const guard = rules.length && !isFailSafe(p) ? guardForRule(rules[0]) : null;
        if (guard && p.verdict_id) this.verdictGuard.set(p.verdict_id, guard);
        if (p.verdict === "block" && guard) {
          this.blocks.push({ guardId: guard, day: e.day });
          this.sim.pulse(guard, "blue", p.enforced === false ? "WOULD BLOCK" : "BLOCK");
        } else if (p.verdict === "escalate" && guard) {
          this.sim.pulse(guard, "amber", "REVIEW");
        } else if (p.verdict === "allow") {
          const t = this.now();
          if (t - this.lastAllowAt > 900 && p.entity_id) {
            this.lastAllowAt = t;
            this.sim.pulse(greenIdFor(String(p.entity_id)), "green");
          }
        }
        break;
      }

      case "escalation.opened": {
        const g = this.verdictGuard.get(p.verdict_id);
        if (g) { this.escalationGuard.set(p.escalation_id, g); focus.pinned.add(g); this.sim.pulse(g, "amber", "NEEDS A DECISION"); }
        break;
      }

      case "escalation.resolved": {
        const g = this.escalationGuard.get(p.escalation_id);
        if (g) {
          this.sim.pulse(g, p.decision === "approve" ? "red" : "blue", p.decision === "approve" ? "APPROVED" : p.decision === "timeout" ? "TIMED OUT" : "HUMAN BLOCK");
          setTimeout(() => focus.pinned.delete(g), 2200); // let the decision land before the rest of the arena lights up again
        }
        break;
      }

      case "flag.raised":
        this.sim.pulse(blueIdForRule("already_flagged_high")!, "blue", "FLAG");
        break;

      case "vendor.frozen":
        this.sim.setStatus(greenIdFor(String(p.vendor_id)), "frozen");
        this.sim.pulse(greenIdFor(String(p.vendor_id)), "blue", "FROZEN");
        break;
      case "vendor.unfrozen":
        this.sim.setStatus(greenIdFor(String(p.vendor_id)), "ok");
        break;

      case "attack.outcome": {
        const outcome = p.outcome as AttackOutcome;
        const scheme = this.attackScheme.get(p.attack_id) ?? p.scheme_id;
        const guardId = this.guardFor(scheme, e.day);
        if (!this.sim.scenes.some((s) => s.attackId === p.attack_id)) {
          // outcome for an attack we never saw launch (catch-up after a reconnect)
          const redId = redIdForScheme(scheme) ?? RED_ROSTER[0].id;
          this.sim.launchAttack({ attackId: p.attack_id, redId, greenId: greenIdFor(p.attack_id) });
        }
        this.sim.resolveAttack(p.attack_id, outcome, guardId, p.amount_extracted ?? null);
        break;
      }
      default:
        break;
    }
  }

  /** The guard that stopped this attack: the most recent block that day, else the rule built for the scheme. */
  private guardFor(scheme: string | undefined, day: number): string | null {
    for (let i = this.blocks.length - 1; i >= 0; i--) if (this.blocks[i].day === day) return this.blocks[i].guardId;
    return (scheme && blueIdForRule(SCHEME_RULE[scheme] ?? "")) || null;
  }
}

function hashIndex(s: string, n: number): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return h % n;
}

// ---- demo loop (no backend, no fixture) ----------------------------------------------------------------------

/** Synthetic fraud attempts so the arena is alive without any feed. Same sim calls the director makes. */
export class DemoDriver {
  private t = 4;
  private n = 0;
  constructor(private sim: ArenaSim, private rng: () => number) {}

  update(dt: number) {
    if (this.sim.phase !== "engaged") return;
    this.t -= dt;
    if (this.t > 0 || this.sim.scenes.length >= 2) return;
    this.t = 5.5 + this.rng() * 4;
    const red = RED_ROSTER[Math.floor(this.rng() * RED_ROSTER.length)];
    const green = GREEN_ROSTER[Math.floor(this.rng() * GREEN_ROSTER.length)];
    const roll = this.rng();
    const outcome: AttackOutcome = roll < 0.4 ? "extracted" : roll < 0.85 ? "blocked" : "flagged";
    const scheme = red.id.slice(4);
    const guardId = blueIdForRule(SCHEME_RULE[scheme] ?? "");
    const amount = Math.round(900 + this.rng() * 8200);
    this.sim.launchAttack({ attackId: `demo_${this.n++}`, redId: red.id, greenId: green.id, guardId, outcome, amount });
  }
}
