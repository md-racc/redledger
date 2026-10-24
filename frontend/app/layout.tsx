import type { Metadata, Viewport } from "next";
import { Anton, IBM_Plex_Serif, Instrument_Serif } from "next/font/google";
import "./globals.css";
import "./arena.css";

const display = Anton({ weight: "400", subsets: ["latin"], variable: "--font-display", display: "swap" });
const small = IBM_Plex_Serif({ weight: ["400", "500", "600"], subsets: ["latin"], variable: "--font-small", display: "swap" });
const serif = Instrument_Serif({ weight: "400", style: ["normal", "italic"], subsets: ["latin"], variable: "--font-serif", display: "swap" });

export const metadata: Metadata = { title: "redledger", description: "Adversarial sandbox for autonomous finance" };
export const viewport: Viewport = { themeColor: "#07090d", width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${display.variable} ${serif.variable} ${small.variable}`}>
      <body>{children}</body>
    </html>
  );
}
