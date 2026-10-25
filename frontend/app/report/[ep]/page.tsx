// /report/<episode id>: the printable controls assessment for one run. Owner: Dev Ad (crunch).
// Data: GET /api/bf/fe/episodes/<ep>/controls (viewers get it once the run ends). Rendering: components/report.
import type { Metadata } from "next";
import { ReportView } from "@/components/report/ReportView";

type Props = { params: Promise<{ ep: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { ep } = await params;
  return { title: `Controls assessment · ${decodeURIComponent(ep)}`, robots: { index: false, follow: false } };
}

export default async function ReportPage({ params }: Props) {
  const { ep } = await params;
  return <ReportView ep={decodeURIComponent(ep)} />;
}
