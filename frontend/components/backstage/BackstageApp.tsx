"use client";
import { RawConsole } from "./RawConsole";
import type { TeamKey } from "./raw";

/** One backstage page. Kept as its own client module so the (server) route files stay thin. */
export function BackstageApp({ team }: { team: TeamKey | "hub" }) {
  return <RawConsole team={team} />;
}
