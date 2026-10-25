"use client";
// "Then they learn": the lineage report (docs/ARCHITECTURE.md, Evolution) as a strip of generations. Each generation shows what red tried, what
// blue's rules caught, and what each agent rewrote in its playbook afterwards. Driven by the show's clock, or all at once in
// free play. Pulses the agents a note is about in the arena. Owner: Dev R (Ad since 2026-10-25).
// Which lineage: `?lineage=<id>`, else the pinned showcase lineage, else the newest finished one (lib/arena/lineage.ts).
import { useEffect, useRef, useState } from "react";
import { evoLead, plainRationale, ruleWords, schemeTakes, takeLabel } from "@/lib/arena/evoSummary";
import { money } from "@/lib/arena/headlines";
import { blueControlsAfter, cardLineage, evolvedIn, loadLineageReport, notesAfter, prettyId, visibleGenerations, type EvoAgent, type GenReport, type LineageReport, type LoadedLineage } from "@/lib/arena/lineage";
import { subscribeShowClock } from "@/lib/arena/showClock";
import { useArena } from "@/lib/arena/store";
import { Raw } from "./Raw";

const pretty = prettyId;
const TONE: Record<EvoAgent, "red" | "blue" | "green"> = { red: "red", blue: "blue", green: "green" };
const clamp01 = (x: number) => Math.min(1, Math.max(0, x));

/**
 * `initial`: a report already in hand (tests, a host that fetched it): shown at once, not fetched.
 * The card opens in the simple view (the numbers, what red tried, what each agent changed, in plain words); "Show detail" adds the
 * rule statistics, the playbook diffs and the controls that went quiet, for whoever wants the evidence.
 */
export function EvolutionCard({ open, driven, preferLive, onClose, initial, initialDetail = false }: { open: boolean; driven: boolean; preferLive: boolean; onClose: () => void; initial?: LoadedLineage; initialDetail?: boolean }) {
  const [got, setGot] = useState<{ l: LoadedLineage; live: boolean } | null>(initial ? { l: initial, live: preferLive } : null);
  const [detail, setDetail] = useState(initialDetail);
  const loaded = got?.l ?? null;
  const [p, setP] = useState(1);
  const pulsed = useRef(new Set<string>());
  const cols = useRef<HTMLDivElement>(null);
  const pulse = useArena((s) => s.actions.pulse);

  useEffect(() => {
    // load once per backend state: a backend that comes up after the sample was shown replaces it with the live lineage
    if (!open || (got && got.live === preferLive)) return;
    let dead = false;
    void loadLineageReport(preferLive, cardLineage()).then((l) => { if (!dead) setGot({ l, live: preferLive }); });
    return () => { dead = true; };
  }, [open, got, preferLive]);

  // the show's clock steps through the generations; free play shows them all
  useEffect(() => {
    if (!open) { pulsed.current.clear(); return; }
    if (!driven) { setP(1); return; }
    setP(0);
    return subscribeShowClock((c) => setP((old) => (Math.abs(old - c.evolve) > 0.004 ? c.evolve : old)));
  }, [open, driven]);

  const report = loaded?.report;
  const { shown: gens, hidden } = visibleGenerations(report?.generations ?? []);
  const n = Math.max(1, gens.length);
  const lead = evoLead(gens);
  const reveal = (i: number) => (driven ? clamp01(p * n - i) : 1);
  const current = driven ? Math.min(n - 1, Math.floor(p * n)) : -1;

  // on a narrow screen the columns scroll sideways: keep the one the show is on in view
  useEffect(() => {
    if (current >= 0) cols.current?.children[current]?.scrollIntoView({ inline: "start", block: "nearest", behavior: "smooth" });
  }, [current]);

  // when a generation's after-action notes appear, point at the agents they are about
  useEffect(() => {
    if (!open || !report) return;
    gens.forEach((g, i) => {
      if (reveal(i) < 0.55 || pulsed.current.has(`g${g.generation}`)) return;
      pulsed.current.add(`g${g.generation}`);
      notesAfter(report, g.generation).forEach((note, k) => note.focus.forEach((id) => setTimeout(() => pulse(id, TONE[note.agent] === "red" ? "red" : "blue", "EVOLVED"), 300 * k)));
    });
  });

  return (
    <section className={`evo ${open ? "is-open" : ""}`} data-detail={detail ? "on" : "off"} role="dialog" aria-label="Evolution across generations" aria-hidden={!open}>
      <header>
        <span className="cmp-kicker">Evolution{report ? ` · ${report.lineage.name || report.lineage.id}` : ""}</span>
        {loaded && <span className="evo-src" title={loaded.note}>{loaded.source === "live" ? "live lineage" : "synthetic sample"}</span>}
        {report && <button className="evo-toggle" onClick={() => setDetail((d) => !d)} aria-pressed={detail}>{detail ? "Simple view" : "Show detail"}</button>}
        <button className="icon-btn" onClick={onClose} aria-label="Close">✕</button>
      </header>
      {open && !report && <p className="evo-wait">Loading the lineage…</p>}
      {open && report && (
        <div className="evo-lead">
          <p>Each column is one generation: a full run on the same company. After each one, red and blue rewrite their own playbooks, so read left to right.</p>
          {lead && <p><b className="tone-red">{lead.red}</b> <b className="tone-blue">{lead.blue}</b></p>}
          {loaded?.note && <p className="evo-quiet">{loaded.note}</p>}
          {hidden > 0 && <p className="evo-quiet">{report.generations.length} generations: showing generation {gens[0].generation} and the last {gens.length - 1} ({hidden} in between hidden)</p>}
        </div>
      )}
      {open && report && (
        <div ref={cols} className="evo-cols" style={{ gridTemplateColumns: `repeat(${n}, minmax(0, 1fr))` }}>
          {gens.map((g, i) => <Generation key={g.generation} g={g} report={report} k={reveal(i)} max={maxMoney(gens)} detail={detail} />)}
        </div>
      )}
      {open && report && <footer>{detail && <>Between generations each agent gets a debrief and updates its playbook: red re-weights what paid, blue switches on the controls it has pre-written. Nobody sees another agent&apos;s playbook, only its behaviour.</>}<Raw data={{ source: loaded?.source, note: loaded?.note, lineage: report.lineage, generations: gens.map((g) => ({ generation: g.generation, episode_id: g.episode_id, status: g.status, score: g.score })) }} /></footer>}
    </section>
  );
}

const maxMoney = (gens: GenReport[]) => Math.max(1, ...gens.flatMap((g) => [g.score.dollars_extracted, g.score.dollars_blocked]));

function Generation({ g, report, k, max, detail }: { g: GenReport; report: LineageReport; k: number; max: number; detail: boolean }) {
  const notes = notesAfter(report, g.generation);
  // per-scheme amounts reconciled with the headline (lib/arena/evoSummary.ts): the chips never add up to more than "Stolen"
  const takes = schemeTakes(g);
  /** blue's controls that caught red in this generation, in words (the simple view's one line about blue) */
  const caught = g.blue_rules.filter((r) => r.on_red > 0).map((r) => ruleWords(r.rule_id));
  const evolved = evolvedIn(report, g.generation);
  const controls = blueControlsAfter(report, g.generation);
  const versions = (a: EvoAgent) => Math.max(0, ...(report.playbooks[a] ?? []).filter((v) => v.generation <= g.generation).map((v) => v.version));
  return (
    <article className="evo-col" style={{ opacity: 0.18 + 0.82 * clamp01(k * 4), transform: `translateY(${(1 - clamp01(k * 4)) * 14}px)` }}>
      <h4><span>Gen {g.generation}</span><small>{g.demo ? "this run" : `seed ${g.seed} · ${g.days} days`}</small></h4>
      {g.demo ? (
        <p className="evo-demo">
          The run you just watched starts here: agents arrive carrying their evolved playbooks
          {detail && <span> red v{versions("red")} · blue v{versions("blue")} · green v{versions("green")}</span>}
        </p>
      ) : (
        <>
          <div className="evo-bars">
            <Bar label="Stolen" value={g.score.dollars_extracted} max={max} tone="red" k={k} />
            <Bar label="Blocked" value={g.score.dollars_blocked} max={max} tone="blue" k={k} />
          </div>
          <h5 className="evo-sub">{detail ? "Red tried · blue's controls" : "Red tried"}</h5>
          <ul className="evo-chips">
            {takes.map((t) => {
              const result = takeLabel(t);
              return <li key={t.id} className={t.stolen > 0 ? "win" : "lose"}>{t.id.startsWith("evolved:") && <i>NEW</i>}{pretty(t.id)}<em>{detail ? `${t.launched}× · ${result}` : result}</em></li>;
            })}
            {detail && g.blue_rules.map((r) => <li key={r.rule_id} className="rule" title={r.rule_id}>{r.rule_id.startsWith("learned:") && <i>LEARNED</i>}{ruleWords(r.rule_id)}<em>{r.on_red ? "caught" : "fired"} {r.fired}×{r.precision != null ? ` · precision ${r.precision.toFixed(2)}` : ""}{r.recall != null ? ` · recall ${r.recall.toFixed(2)}` : ""}</em></li>)}
          </ul>
          {!detail && caught.length > 0 && <p className="evo-caught">Blue caught red with: {caught.join(", ")}</p>}
          <h5 className="evo-sub">Then they rewrote their playbooks</h5>
          <div className="evo-notes" style={{ opacity: clamp01((k - 0.45) * 4) }}>
            {notes.length === 0 && <p className="evo-quiet">No playbook changes.</p>}
            {notes.map((nt) => (
              <p key={nt.agent + nt.version} className={`note tone-${TONE[nt.agent]}`} title={detail ? nt.rationale : undefined}>
                <b>{nt.agent}{detail && ` v${nt.version}`}</b>
                <span>{plainRationale(nt.agent, nt.rationale, g.score.dollars_extracted)}</span>
                {detail && <small>{nt.chips.slice(0, 3).join("  ·  ")}</small>}
              </p>
            ))}
            {evolved.map((e) => <p key={e.scheme_id} className="note tone-red"><b>new scheme</b><span>{pretty(e.scheme_id)}, evolved from {pretty(e.parent)}</span></p>)}
            {controls.on.length > 0 && <p className="note tone-blue"><b>{controls.basis === "playbook" ? "controls switched on" : "rules first fired"}</b><span>{controls.on.map(ruleWords).join(", ")}</span></p>}
            {controls.off.length > 0 && <p className="note tone-blue"><b>controls switched off</b><span>{controls.off.map(ruleWords).join(", ")}</span></p>}
            {detail && controls.quiet.length > 0 && <p className="note tone-blue"><b>not fired after this generation</b><span>{controls.quiet.map(ruleWords).join(", ")}</span></p>}
          </div>
        </>
      )}
    </article>
  );
}

function Bar({ label, value, max, tone, k }: { label: string; value: number; max: number; tone: string; k: number }) {
  return (
    <div className={`evo-bar tone-${tone}`}>
      <span>{label}</span>
      <div><i style={{ width: `${(value / max) * 100 * clamp01(k * 3)}%` }} /></div>
      <b>{money(value) || "$0"}</b>
    </div>
  );
}
