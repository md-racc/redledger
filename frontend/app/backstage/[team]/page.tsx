import { notFound } from "next/navigation";
import { BackstageApp } from "@/components/backstage/BackstageApp";

const TEAMS = ["red", "green", "blue", "battlefield"] as const;
type Team = (typeof TEAMS)[number];

export function generateStaticParams() {
  return TEAMS.map((team) => ({ team }));
}

export default async function Page({ params }: { params: Promise<{ team: string }> }) {
  const { team } = await params;
  if (!(TEAMS as readonly string[]).includes(team)) notFound();
  return <BackstageApp team={team as Team} />;
}
