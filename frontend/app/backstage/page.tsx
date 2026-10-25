import { headers } from "next/headers";
import { notFound } from "next/navigation";
import { BackstageApp } from "@/components/backstage/BackstageApp";
import { backstageGate } from "@/lib/backstage/gate";

export const dynamic = "force-dynamic";

export default async function Page() {
  if (backstageGate(await headers()) === "hidden") notFound();
  return <BackstageApp team="hub" />;
}
