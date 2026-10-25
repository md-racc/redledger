"use client";
// "Show me the data": a small toggle that opens the JSON a card was built from. The arena is a story told over real events, and every card
// should be able to hand over the evidence. Plain text, never markup. Owner: Dev R.

const MAX = 3200;

export function Raw({ data, label = "raw" }: { data: unknown; label?: string }) {
  let text: string;
  try { text = JSON.stringify(data, null, 1) ?? "null"; } catch { text = "(not printable)"; }
  const cut = text.length > MAX;
  return (
    <details className="raw-toggle">
      <summary title="The data this card is built from">{label}</summary>
      <pre>{cut ? `${text.slice(0, MAX)}\n… (${text.length - MAX} more characters)` : text}</pre>
    </details>
  );
}
