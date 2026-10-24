// Shared types for the 3D arena. Owner: Dev R. Pure data, no three.js imports.

export type Team = "red" | "blue" | "green";

/** What an agent is doing right now; drives animation and which path it follows. */
export type AgentMode =
  | "idle" // standing at its spawn point on the perimeter
  | "travel" // pathfinding from spawn to its slot in the arena
  | "hold" // parked in its slot at the centre
  | "approach" // red walking up to its target
  | "pitch" // red working its target (the fraud attempt is live)
  | "dash" // blue sprinting to intercept
  | "caught" // red neutralised by a guard
  | "return"; // walking back to the slot

export type AgentStatus = "ok" | "caught" | "drained" | "frozen";

/** Static description of one agent. The roster is the join point between the 3D scene and the backend. */
export interface AgentSpec {
  /** `${team}:${key}`; stable across sessions. red key = scheme_id, blue key = rule id, green key = slot. */
  id: string;
  team: Team;
  /** index within the team, used for layout */
  index: number;
  /** short human label, shown on hover and in the modal header */
  name: string;
  /** one-sentence default description (replaced by backend text when it arrives) */
  blurb: string;
}

export type ArenaPhase = "idle" | "converging" | "engaged" | "dispersing";

export type AttackOutcome = "pending" | "extracted" | "partial" | "blocked" | "flagged" | "failed";

/** One value row in the agent modal. `value` undefined renders as a placeholder that names its data source. */
export interface DetailField {
  key: string;
  label: string;
  value?: string | number | null;
  /** where the value comes from; shown while the value is missing, e.g. "GET /fe/episodes/{ep}/attacks" */
  source: string;
  kind?: "text" | "money" | "mono" | "int" | "percent";
}

export interface DetailSection {
  title: string;
  fields: DetailField[];
}

export interface AgentDetails {
  id: string;
  team: Team;
  /** e.g. "Fraudster" | "Guard" | "Client" */
  role: string;
  title: string;
  /** one-line mono caption under the title */
  caption: string;
  /** serif pull-quote (red: scheme story, blue: rule detail, green: client note) */
  story?: string | null;
  /** coloured status pill */
  status?: { label: string; tone: "ok" | "warn" | "bad" | "idle" } | null;
  sections: DetailSection[];
  /** true when no backend data has been merged yet (every field is a placeholder) */
  placeholder: boolean;
}

/** Anything the host app can pass in to fill the modal. Keyed by agent id, deep-merged over derived data. */
export type AgentDetailOverrides = Record<string, Partial<Omit<AgentDetails, "id" | "team" | "sections">> & { fields?: Record<string, DetailField["value"]> }>;
