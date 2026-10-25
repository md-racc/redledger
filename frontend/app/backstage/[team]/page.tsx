import type { Metadata } from "next";
import { headers } from "next/headers";
import { notFound } from "next/navigation";
import { BackstageApp } from "@/components/backstage/BackstageApp";
import { doorTeam } from "@/lib/backstage/alias";
import { backstageGate } from "@/lib/backstage/gate";

const TEAMS = ["red", "green", "blue", "battlefield"] as const;
type Team = (typeof TEAMS)[number];

// Rendered per request: on the hidden doors (red.<site>, blue.<site>) who is asking decides whether this page exists (lib/backstage/gate.ts).
export const dynamic = "force-dynamic";

// On a door the tab says only which door it is (`red.redledger`), not what the page is.
export async function generateMetadata(): Promise<Metadata> {
  const door = doorTeam((await headers()).get("host"));
  return door ? { title: `${door}.redledger` } : {};
}

export default async function Page({ params }: { params: Promise<{ team: string }> }) {
  const { team } = await params;
  if (!(TEAMS as readonly string[]).includes(team)) notFound();
  if (backstageGate(await headers()) === "hidden") notFound();
  return <BackstageApp team={team as Team} />;
}
