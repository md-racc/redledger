import type { Metadata } from "next";
import "./backstage.css";
import "./dashboard.css";

// Not linked from anywhere public; the consoles are for the other laptops on stage.
export const metadata: Metadata = { title: "redledger · backstage", robots: { index: false, follow: false } };

export default function BackstageLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
