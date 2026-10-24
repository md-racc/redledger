// Focus: whoever is part of an interaction right now stays lit; everyone else is dimmed. ArenaWorld writes this every
// frame from the sim (fraud scenes, guards that just acted), the director pins an agent while a human decision is open, the
// figures and the spotlight read it. Plain data, never React state.
export const focus = {
  /** agents in an interaction this frame */
  ids: new Set<string>(),
  /** agents held in focus until released (an open escalation keeps its guard lit) */
  pinned: new Set<string>(),
  /** 0..1, eased: how strongly the rest of the arena is dimmed */
  level: 0,
  /** centre of the interaction, world space, and how far it spreads (m) */
  x: 0,
  y: 0,
  z: 0,
  radius: 8,
};
