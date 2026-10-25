// Where what is on screen comes from. Owner: Dev R.
//
// A judge should never have to guess whether the numbers are live or a recording, or which agents are real. This says it in one badge and
// one short line, from what the frontend actually knows: the feed's source, whether the show is playing, the episode id, and each agent's
// /health (`dry_run`, `model`). It claims nothing the backend did not report: with no health answer the agents are "unknown".
import type { Backend } from "./useFeed";
import type { FeedSource } from "./store";

export type Badge = "LIVE" | "RECORDED" | "REPLAY" | "SHOW" | "IDLE";
export type AgentMode = "live" | "keyless" | "down" | "unknown";

export interface AgentProvenance { name: "red" | "green" | "blue"; mode: AgentMode; model?: string }
export interface Provenance {
  badge: Badge;
  /** what the badge means, for a tooltip */
  meaning: string;
  agents: AgentProvenance[];
  /** "red live (gpt-5.4-mini) · green keyless · blue keyless" */
  agentsLine: string;
  episode: string | null;
}

const MEANING: Record<Badge, string> = {
  LIVE: "These events are coming from a running battlefield right now.",
  RECORDED: "These events are a recording played back; no agent is running for them.",
  REPLAY: "A recorded episode being re-emitted by the battlefield's replay route.",
  SHOW: "The 90-second show is playing. It runs from a recording unless every agent is keyless.",
  IDLE: "Nothing is running yet.",
};

export function provenance(input: { backend: Backend; source: FeedSource; inShow: boolean; episodeId: string | null }): Provenance {
  const { backend, source, inShow, episodeId } = input;
  let badge: Badge;
  if (episodeId?.startsWith("replay_")) badge = "REPLAY";
  else if (source === "live") badge = inShow ? "SHOW" : "LIVE";
  else if (source === "mock") badge = inShow ? "SHOW" : "RECORDED";
  else badge = "IDLE";
  // the show over a live feed is "SHOW" too, but then it is real events: say which in the meaning
  const meaning = badge === "SHOW" && source === "live" ? "The 90-second show is playing on live episodes (every agent is keyless)." : MEANING[badge];

  const agents = (["red", "green", "blue"] as const).map((name): AgentProvenance => {
    const h = backend.agents?.[name];
    if (backend.state !== "live" || !h) return { name, mode: "unknown" };
    if (h.ok === false) return { name, mode: "down" };
    return { name, mode: h.dry_run ? "keyless" : "live", ...(h.dry_run ? {} : h.model ? { model: h.model } : {}) };
  });
  const agentsLine = agents.map((a) => `${a.name} ${a.mode}${a.model ? ` (${a.model})` : ""}`).join(" · ");
  return { badge, meaning, agents, agentsLine, episode: episodeId };
}
