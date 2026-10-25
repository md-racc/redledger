"use client";
// Two barely-there diamonds that open the hidden consoles (red.<site>, blue.<site>; lib/backstage/alias.ts). Rendered for an admin only: for
// anyone else there is no element, no label, no link, nothing in the page to find. Nearly invisible until the pointer is on them. Owner: Dev R.
import { doorUrl, type DoorTeam } from "@/lib/backstage/alias";
import { useRole } from "@/lib/role";

export function Doors({ show }: { show: boolean }) {
  const admin = useRole() === "admin";
  if (!admin || !show) return null;
  const open = (team: DoorTeam) => window.open(doorUrl(window.location, team), "_blank", "noopener");
  return (
    <div className="doors">
      <button type="button" className="door door-red" onClick={() => open("red")} title="red." aria-label="red. console" />
      <button type="button" className="door door-blue" onClick={() => open("blue")} title="blue." aria-label="blue. console" />
    </div>
  );
}
