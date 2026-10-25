"use client";
// "Same seed. Same fraud. Different ending.": the controller-off run beside the controller-on run, the numbers counting
// up in sequence so a room can follow them. Owner: Dev R.
import { useEffect, useState } from "react";
import type { CompareSides } from "@/lib/arena/compare";
import { enforceStory, loadLiveRuns, lostByDay, runScore, type LiveRun, type LiveRuns } from "@/lib/arena/liveRuns";
import type { Score } from "@/lib/types";
import { Raw } from "./Raw";

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
  const [tab, setTab] = useState<"show" | "real">("show");
  // the card always opens on this run (the show's compare beat counts on it); the real run is one click away
  useEffect(() => { if (open) setTab("show"); }, [open]);
  return (
    <section className={`cmp ${open ? "is-open" : ""}`} role="dialog" aria-label="Controller off versus controller on" aria-hidden={!open}>
      <header>
        <span className="cmp-kicker">The difference</span>
        <div className="cmp-tabs" role="tablist" aria-label="Which runs to compare">
          <button role="tab" aria-selected={tab === "show"} className={tab === "show" ? "on" : ""} onClick={() => setTab("show")}>This show</button>
          <button role="tab" aria-selected={tab === "real"} className={tab === "real" ? "on" : ""} onClick={() => setTab("real")}>Real run</button>
        </div>
        <button className="icon-btn" onClick={onClose} aria-label="Close">✕</button>
      </header>
      {open && tab === "show" && sides && <Body sides={sides} />}
      {open && tab === "show" && !sides && <div className="cmp-empty"><p>Run an episode (or launch an attack) first: there is nothing to compare yet.</p></div>}
      {open && tab === "real" && <RealRun />}
    </section>
  );
}

function Body({ sides }: { sides: CompareSides }) {
  const saved = Math.max(0, sides.off.dollars_extracted - sides.on.dollars_extracted);
  const leaked = sides.on.dollars_extracted;
  const delta = useCountUp(saved, 3000, 1400);
  return (
    <>
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
        <Raw data={sides} />
      </footer>
    </>
  );
}

/** The two recorded live-red runs, side by side: the numbers the pitch says out loud, on screen. */
function RealRun() {
  const [data, setData] = useState<LiveRuns | null | undefined>(undefined);
  useEffect(() => { let dead = false; void loadLiveRuns().then((d) => { if (!dead) setData(d); }); return () => { dead = true; }; }, []);
  if (data === undefined) return <div className="cmp-empty"><p>Loading the recorded runs…</p></div>;
  if (data === null) return <div className="cmp-empty"><p>The recorded live runs could not be read.</p></div>;
  const { off, enforce } = data.runs;
  // money lost per the live controls report (#207 scoring), not the recordings' pre-#207 scoreboards (lib/arena/liveRuns.ts)
  const offScore = runScore(off);
  const onScore = runScore(enforce);
  const kept = Math.max(0, offScore.dollars_extracted - onScore.dollars_extracted);
  const notes = [off, enforce].map((r) => r.controls_report).filter((r) => !!r);
  return (
    <>
      <div className="cmp-cols">
        <Column title="Controller off" tag="live red · recorded" score={offScore} tone="red" delay={100} />
        <div className="cmp-mid">
          <b>{usd(kept)}</b>
          <span>kept by the controller</span>
          {onScore.dollars_extracted > 0 && <em>{usd(onScore.dollars_extracted)} still got through</em>}
        </div>
        <Column title="Controller on" tag="live red · recorded" score={onScore} tone="blue" delay={100} />
      </div>
      <div className="cmp-days" aria-label="Money lost so far, day by day (controls report)">
        <DayBars run={off} tone="red" label="off" />
        <DayBars run={enforce} tone="blue" label="on" />
      </div>
      <footer>
        Recorded on {data.where} on {data.recorded}: the same seed for {off.days} days, controller off and then on. {data.note} {enforceStory(enforce)}
        {notes.length > 0 && <> Money lost is from the {notes[0]!.source}: it counts only what reached an account the attacker controls. {enforce.controls_report?.note}</>}
        <Raw data={data} />
      </footer>
    </>
  );
}

function DayBars({ run, tone, label }: { run: LiveRun; tone: "red" | "blue"; label: string }) {
  const days = lostByDay(run);
  const max = Math.max(1, ...days.map((d) => d.lost));
  return (
    <div className={`cmp-daybars tone-${tone}`}>
      <span>Lost, {label}</span>
      <div>{days.map((d) => <i key={d.day} style={{ height: `${Math.max(3, (d.lost / max) * 100)}%` }} title={`day ${d.day}: ${usd(d.lost)}`} />)}</div>
      <b>{usd(runScore(run).dollars_extracted)}</b>
    </div>
  );
}
