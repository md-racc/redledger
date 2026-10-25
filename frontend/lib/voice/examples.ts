// "Try saying": a few ready sentences, one per language, so a judge who is not sure what to say (or has no microphone) can see
// what the box takes in one click. Each one is checked against the matcher in examples.test.ts, so the scheme named here is the
// scheme the console will pick. Owner: Dev R.
import type { BuiltInScheme } from "./intent";

export interface Example {
  /** what the chip says, in its own language */
  label: string;
  text: string;
  scheme: BuiltInScheme;
}

export const EXAMPLES: Example[] = [
  { label: "English", text: "Invent a fake vendor, send an invoice for work nobody did, and get it paid.", scheme: "ghost_vendor" },
  { label: "Español", text: "Cambia la cuenta bancaria de un proveedor justo antes de un pago grande.", scheme: "bank_swap" },
  { label: "Deutsch", text: "Teile die Rechnung in mehrere Rechnungen unter dem Schwellenwert auf.", scheme: "threshold_split" },
  { label: "हिन्दी", text: "एक फर्जी कर्मचारी बनाओ और उसे हर महीने वेतन दिलाओ।", scheme: "ghost_employee" },
];
