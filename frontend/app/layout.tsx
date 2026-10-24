import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = { title: "Red Ledger", description: "Adversarial sandbox for autonomous finance" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
