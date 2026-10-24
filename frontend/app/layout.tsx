import type { Metadata, Viewport } from "next";
import { Bodoni_Moda, Cinzel, Jost } from "next/font/google";
import "./globals.css";
import "./arena.css";

// Three faces, each with one job. Cinzel: Roman inscription capitals for the name, labels and buttons. Bodoni Moda: the figures
// (money, days) and the big chapter titles. Jost: the text you read, a geometric sans in the Futura family from the same
// Italian-modernist years as the palace architecture.
const caps = Cinzel({ weight: ["400", "500", "600", "700"], subsets: ["latin"], variable: "--font-caps", display: "swap" });
const figures = Bodoni_Moda({ style: ["normal", "italic"], subsets: ["latin"], variable: "--font-figures", display: "swap" });
const text = Jost({ weight: ["300", "400", "500", "600"], subsets: ["latin"], variable: "--font-text", display: "swap" });

export const metadata: Metadata = { title: "redledger", description: "Adversarial sandbox for autonomous finance" };
export const viewport: Viewport = { themeColor: "#0b0a08", width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${caps.variable} ${figures.variable} ${text.variable}`}>
      <body>{children}</body>
    </html>
  );
}
