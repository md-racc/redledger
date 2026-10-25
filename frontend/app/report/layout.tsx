import type { Metadata, Viewport } from "next";
import "./report.css";

// The report is a document, not the arena: white paper, its own type, printable (report.css).
export const metadata: Metadata = { title: "Controls assessment" };
export const viewport: Viewport = { themeColor: "#ffffff" };

export default function ReportLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
