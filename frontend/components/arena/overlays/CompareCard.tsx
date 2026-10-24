"use client";
// "Same seed. Same fraud. Different ending.": the controller-off run beside the controller-on run, the numbers counting
// up in sequence so a room can follow them. Owner: Dev R.
import { useEffect, useState } from "react";
import type { CompareSides } from "@/lib/arena/compare";
import type { Score } from "@/lib/types";

const usd = (n: number) => `$${Math.round(n).toLocaleString()}`;
const ease = (k: number) => 1 - Math.pow(1 - k, 3);

/** 0 → `target` over `ms`, after `delay`. */
function useCountUp(target: number, delay: number, ms = 1200): number {
  const [v, setV] = useState(0);
  useEffect(() => {
    let raf = 0;
    const t0 = performance.now() + delay;
    const step = (now: number) => {
      const k = Math.min(1, Math.max(0, (now - t0) / ms));
      setV(target * ease(k));
      if (k < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [target, delay, ms]);
  return v;
}

function Num({ label, value, tone, delay, fmt = usd }: { label: string; value: number; tone: string; delay: number; fmt?: (n: number) => string }) {
  const v = useCountUp(value, delay);
  return (
    <div className={`cmp-num tone-${tone}`}>
      <span>{label}</span>
      <b>{fmt(v)}</b>
    </div>
  );
}

function Column({ title, tag, score, tone, delay }: { title: string; tag?: string; score: Score; tone: "red" | "blue"; delay: number }) {
  return (
    <article className={`cmp-col is-${tone}`} style={{ animationDelay: `${delay}ms` }}>
      <h4>{title}{tag && <small>{tag}</small>}</h4>
      <Num label="Stolen" value={score.dollars_extracted} tone="red" delay={delay + 250} />
      <Num label="Blocked" value={score.dollars_blocked} tone="blue" delay={delay + 450} />
      <Num label="False-positive cost" value={score.false_positive_cost} tone="amber" delay={delay + 650} />
      <Num label="Caught" value={score.attacks_caught} tone="green" delay={delay + 850} fmt={(n) => `${Math.round(n)}/${score.attacks_launched}`} />
    </article>
  );
}

export function CompareCard({ sides, open, onClose }: { sides: CompareSides | null; open: boolean; onClose: () => void }) {
  return (
    <section className={`cmp ${open ? "is-open" : ""}`} role="dialog" aria-label="Controller off versus controller on" aria-hidden={!open}>
      {open && sides && <Body sides={sides} onClose={onClose} />}
      {open && !sides && (
        <div className="cmp-empty">
          <button className="icon-btn" onClick={onClose} aria-label="Close">✕</button>
          <p>Run an episode (or launch an attack) first: there is nothing to compare yet.</p>
        </div>
      )}
    </section>
  );
}

function Body({ sides, onClose }: { sides: CompareSides; onClose: () => void }) {
  const saved = Math.max(0, sides.off.dollars_extracted - sides.on.dollars_extracted);
  const leaked = sides.on.dollars_extracted;
  const delta = useCountUp(saved, 3000, 1400);
  return (
    <>
      <header>
        <span className="cmp-kicker">The difference</span>
        <button className="icon-btn" onClick={onClose} aria-label="Close">✕</button>
      </header>
      <div className="cmp-cols">
        <Column title="Controller off" tag={sides.offProjected ? "projected" : undefined} score={sides.off} tone="red" delay={200} />
        <div className="cmp-mid" style={{ animationDelay: "2800ms" }}>
          <b>{usd(delta)}</b>
          <span>kept by the controller</span>
          {leaked > 0 && <em>{usd(leaked)} still got through</em>}
        </div>
        <Column title={`Controller ${sides.onMode === "enforce" ? "on" : sides.onMode}`} tag={sides.live ? "running" : undefined} score={sides.on} tone="blue" delay={1600} />
      </div>
      <footer>
        Same seed, same attacks.{sides.offProjected ? " The controller-off side is projected: every attempt in this run, with nothing gating it." : ""}
      </footer>
    </>
  );
}
