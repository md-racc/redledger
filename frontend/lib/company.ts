// The synthetic company every run plays out on. The source is battlefield's seed/company.py (COMPANY); a live run carries it
// as the snapshot's company.name (GET /fe/episodes/{ep}/snapshot). This is the fallback for mock mode and for screens that
// have no snapshot. Fictional, like its vendors.
export const COMPANY = {
  name: "Meridian Components",
  /** what it is, as a noun phrase after "a" / "an" */
  kind: "electronics components distributor",
} as const;

/** The company's name from a snapshot when there is one, else the fallback. */
export function companyName(snapshot?: { company?: { name?: string | null } | null } | null): string {
  const n = snapshot?.company?.name?.trim();
  return n || COMPANY.name;
}
