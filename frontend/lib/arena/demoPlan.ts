// The judging-hour demo plan for every episode an admin starts from the arena or the backstage console. Pure, tested. Owner: Dev R.
import type { ControllerMode } from "@/lib/types";

/** The judging-hour demo plan: red's scheme pinned per day to ones that move the scoreboard on screen (an escalation,
 *  blocked invoices, an expense that slips through). Unplanned, red mostly repeats duplicate invoices that never resolve.
 *  Red still runs live; a judge's attack still takes over its next turn. */
export const DEMO_PLAN_CYCLE = ["bank_swap", "threshold_split", "ghost_vendor", "ghost_employee", "expense_inflation", "po_mismatch"] as const;
export function demoPlan(days: number): { day: number; scheme_id: string }[] {
  const n = Math.max(0, Math.min(365, Math.floor(days)));
  return Array.from({ length: n }, (_, day) => ({ day, scheme_id: DEMO_PLAN_CYCLE[day % DEMO_PLAN_CYCLE.length]! }));
}

/** The arena's "Run again / Run episode": long enough to watch several schemes land live (about 6–10 minutes). */
export const RUN_DAYS = 12;
/** A judge-driven sandbox, created when an attack is launched with no run going; each attack steps one day. */
export const SANDBOX_DAYS = 30;

/** POST /episodes body for a run an admin starts from the arena: the demo plan pinned for every day. */
export const plannedEpisode = (controller_mode: ControllerMode, seed: number, days: number) =>
  ({ controller_mode, seed, days, attack_plan: demoPlan(days) });
