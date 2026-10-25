"use client";
// "Why lenders care": what five large US lenders have said in public this month about outside AI agents in customer accounts, each line
// with its source. Reads lib/arena/lenders.ts (docs/EVIDENCE.md, "Lenders on the record", has the same table with the caveats). Owner: Dev R.
import { ALSO, AS_OF, AXIOS, DISCLAIMER, HEADLINE, LENDERS, TIE, type Source } from "@/lib/arena/lenders";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export const when = (iso: string): string => {
  const [y, m, d] = iso.split("-").map(Number);
  return `${MONTHS[(m ?? 1) - 1]} ${d}, ${y}`;
};

function Src({ s }: { s: Source }) {
  return (
    <li>
      <a href={s.url} target="_blank" rel="noopener noreferrer">{s.outlet}</a>
      <span>{[s.by, when(s.date)].filter(Boolean).join(", ")}</span>
    </li>
  );
}

export function LendersCard({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <section className={`lnd ${open ? "is-open" : ""}`} role="dialog" aria-label="What the largest lenders have said about AI agents in their accounts" aria-hidden={!open}>
      <header>
        <span className="cmp-kicker">Why lenders care</span>
        <span className="evo-src">as of {when(AS_OF)}</span>
        <button className="icon-btn" onClick={onClose} aria-label="Close">✕</button>
      </header>
      <p className="lnd-intro">
        {HEADLINE} <a href={AXIOS.url} target="_blank" rel="noopener noreferrer">Axios, {AXIOS.by}, {when(AXIOS.date)}</a>
      </p>
      <div className="lnd-cols">
        {LENDERS.map((l) => (
          <article key={l.id} className="lnd-col" data-lender={l.id}>
            <h4>{l.name}</h4>
            <p className="lnd-chip">{l.chip}</p>
            <p>{l.says}</p>
            <p className="lnd-not">{l.notClaimed}</p>
            <ul className="lnd-src">{l.sources.map((s) => <Src key={s.url} s={s} />)}</ul>
          </article>
        ))}
      </div>
      <footer>
        <p>
          <b>Also on the record:</b>{" "}
          {ALSO.map((a, i) => (
            <span key={a.name}>{i > 0 && " "}{a.name}: {a.says} (<a href={a.source.url} target="_blank" rel="noopener noreferrer">{a.source.outlet}, {when(a.source.date)}</a>)</span>
          ))}
        </p>
        <p>{TIE}</p>
        <p className="lnd-disc">{DISCLAIMER}</p>
      </footer>
    </section>
  );
}
