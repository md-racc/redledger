"use client";
// The panels of the red and blue dashboards. Presentational: they take derived rows (dash.ts, ../derive.ts) and print them. Owner: Dev R.
//
// Written for a projector a few metres away: 16px+ body, monospace for anything that is data (ids, amounts, tools, args, times),
// prose (thinking, reasons, stories) in a sans face, one accent per meaning. Nothing here prints `origin`.
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Markdown } from "@/components/arena/overlays/Markdown";
import { api } from "@/lib/api";
import type { Attack, UIState } from "@/lib/types";
import { daySummary, reportDays, reportText } from "@/lib/arena/report";
import { confusion as confusionOf, ruleBoard, ruleName } from "../derive";
import { hhmmss } from "../raw";
import {
  clip, compactJson, diffLines, fmtCountdown, fmtCredits, fmtMs, fmtSec, fmtUsd, generationEntries, playbookHistory, prettyJson, schemeCatalog, splitTool,
  turnElapsedSec, verdictStats, type EscRow, type LineageTimeline, type ToolCallRow, type TurnBlock, type VerdictRow,
} from "./dash";

// ---- frame ------------------------------------------------------------------------------------------------------------------

export function Panel({ title, meta, children, grow = 1, className }: { title: string; meta?: ReactNode; children: ReactNode; grow?: number; className?: string }) {
  return (
    <section className={`bd-panel${grow > 0 ? "" : " bd-panel-fixed"}${className ? ` ${className}` : ""}`} style={grow > 0 ? { flex: `${grow} 1 0` } : { flex: "0 0 auto" }}>
      <header className="bd-panel-h">
        <h2>{title}</h2>
        {meta != null && <div className="bd-panel-meta">{meta}</div>}
      </header>
      <div className="bd-panel-b">{children}</div>
    </section>
  );
}

export const Empty = ({ children }: { children: ReactNode }) => <div className="bd-empty">{children}</div>;
const Pill = ({ k, children }: { k: string; children: ReactNode }) => <span className={`bd-pill bd-pill-${k}`}>{children}</span>;

/** Text that is clipped to `n` characters until clicked. */
function Clip({ text, n, className }: { text: string; n: number; className?: string }) {
  const [open, setOpen] = useState(false);
  if (text.length <= n) return <span className={className}>{text}</span>;
  return (
    <span className={`${className ?? ""} bd-clip`} role="button" tabIndex={0} title={open ? "click to fold" : "click to show all"} onClick={() => setOpen((o) => !o)} onKeyDown={(e) => { if (e.key === "Enter") setOpen((o) => !o); }}>
      {open ? text : `${text.slice(0, n - 1)}…`}
      <span className="bd-more">{open ? " [less]" : " [more]"}</span>
    </span>
  );
}

// ---- thought stream ---------------------------------------------------------------------------------------------------------

function ThinkingBox({ text, live }: { text: string; live: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  useEffect(() => {
    const el = ref.current;
    if (el && live && stick.current) el.scrollTop = el.scrollHeight;
  }, [text, live]);
  return (
    <div ref={ref} className={`bd-think${live ? " bd-think-live" : ""}`} onScroll={(e) => { const el = e.currentTarget; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40; }}>
      {text}
      {live && <span className="bd-caret" aria-hidden>▌</span>}
    </div>
  );
}

const turnLabel = (b: TurnBlock) => `day ${b.day} · turn ${b.n}${b.implicit ? " (outside a turn)" : ""}`;

function TurnStatus({ b, now }: { b: TurnBlock; now: number }) {
  const el = turnElapsedSec(b, now);
  return (
    <span className="bd-mono bd-turn-stat">
      {!b.ended ? <Pill k="run">running {fmtSec(el)}</Pill> : b.ok === false ? <Pill k="bad">failed</Pill> : <Pill k="ok">ok</Pill>}
      {b.ended && <span> {fmtSec(el)}</span>}
      {b.credits != null && <span> · {fmtCredits(b.credits)} cr</span>}
    </span>
  );
}

export function ThoughtStream({ turns, now, emptyText }: { turns: TurnBlock[]; now: number; emptyText: string }) {
  const withText = turns.filter((t) => t.thinking.trim() || !t.ended);
  if (!withText.length) return <Empty>{emptyText}</Empty>;
  const shown = withText.slice(-30).reverse();
  return (
    <div className="bd-thoughts">
      {shown.map((b, i) => {
        const live = i === 0 && !b.ended;
        const head = (
          <div className="bd-turn-h">
            <span className="bd-mono">{turnLabel(b)}</span>
            <span className="bd-dim bd-mono">{hhmmss(b.startTs ?? undefined)}</span>
            <TurnStatus b={b} now={now} />
          </div>
        );
        if (i === 0) {
          return (
            <article key={b.key} className="bd-turn bd-turn-newest">
              {head}
              {b.thinking.trim() ? <ThinkingBox text={b.thinking} live={live} /> : <Empty>{live ? "thinking…" : "no thinking in this turn"}</Empty>}
              {b.summary && <div className="bd-turn-sum"><span className="bd-dim">summary </span>{b.summary}</div>}
            </article>
          );
        }
        return (
          <details key={b.key} className="bd-turn">
            <summary>{head}<div className="bd-preview">{clip(b.thinking.replace(/\s+/g, " ").trim(), 150) || "(no thinking)"}</div></summary>
            <div className="bd-think">{b.thinking}</div>
            {b.summary && <div className="bd-turn-sum"><span className="bd-dim">summary </span>{b.summary}</div>}
          </details>
        );
      })}
    </div>
  );
}

// ---- tool-call timeline -------------------------------------------------------------------------------------------------------

function ToolLine({ t, now }: { t: ToolCallRow; now: number }) {
  const [open, setOpen] = useState(false);
  const { ns, name } = splitTool(t.tool);
  const waiting = t.ok === undefined;
  const age = waiting ? now - Date.parse(t.callTs) : null;
  return (
    <div className={`bd-tool${t.ok === false ? " bd-tool-bad" : ""}`}>
      <div className="bd-tool-h" role="button" tabIndex={0} onClick={() => setOpen((o) => !o)} onKeyDown={(e) => { if (e.key === "Enter") setOpen((o) => !o); }} title="click for the full arguments and result">
        <span className="bd-mono bd-dim">{hhmmss(t.callTs)}</span>
        {waiting ? <Pill k="run">…</Pill> : t.ok ? <Pill k="ok">ok</Pill> : <Pill k="bad">fail</Pill>}
        <span className="bd-mono bd-tool-name"><span className="bd-dim">{ns}</span>{name}</span>
        <span className="bd-mono bd-lat">{waiting ? (age != null && age >= 0 ? `${fmtMs(age)}…` : "…") : fmtMs(t.latencyMs)}</span>
      </div>
      {open ? (
        <>
          <pre className="bd-mono bd-args">{prettyJson(t.args)}</pre>
          {t.summary && <div className="bd-mono bd-res">{t.summary}</div>}
          {t.tool_use_id && <div className="bd-mono bd-dim bd-small">tool_use_id {t.tool_use_id}</div>}
        </>
      ) : (
        <>
          {t.args !== undefined && <div className="bd-mono bd-args1">{compactJson(t.args, 140)}</div>}
          {t.summary && <div className="bd-mono bd-res">→ {clip(t.summary, 160)}</div>}
        </>
      )}
    </div>
  );
}

export function ToolTimeline({ turns, now, emptyText }: { turns: TurnBlock[]; now: number; emptyText: string }) {
  if (!turns.length) return <Empty>{emptyText}</Empty>;
  return (
    <div className="bd-timeline">
      {turns.slice(-14).reverse().map((b) => (
        <div key={b.key} className={`bd-tl-turn${b.ended ? "" : " bd-tl-live"}`}>
          <div className="bd-tl-mark">
            <span className="bd-mono">{b.ended ? "turn.ended" : "turn.started"}</span>
            <span className="bd-mono">{turnLabel(b)}</span>
            <TurnStatus b={b} now={now} />
          </div>
          {b.summary && <div className="bd-tl-sum">{b.summary}</div>}
          {[...b.tools].reverse().map((t) => <ToolLine key={t.key} t={t} now={now} />)}
          {b.notes.map((n, i) => <div key={i} className="bd-note bd-mono">{hhmmss(n.ts)} {n.text}</div>)}
          {!b.tools.length && !b.notes.length && <div className="bd-dim bd-small">{b.ended ? "no tool calls this turn" : "no tool call yet"}</div>}
          {!b.implicit && <div className="bd-tl-mark bd-tl-start"><span className="bd-mono bd-dim">turn.started {hhmmss(b.startTs ?? undefined)}</span></div>}
        </div>
      ))}
    </div>
  );
}

// ---- red: attacks + catalog ---------------------------------------------------------------------------------------------------

const OUTCOME_KIND: Record<string, string> = { pending: "run", extracted: "bad", partial: "warn", blocked: "ok", flagged: "ok", failed: "dim" };

export function AttackList({ attacks, score }: { attacks: Attack[]; score: UIState["score"] }) {
  return (
    <>
      <div className="bd-stats bd-mono">
        <span>launched <b>{score.attacks_launched}</b></span>
        <span>extracted <b className="bd-c-bad">{fmtUsd(score.dollars_extracted)}</b></span>
        <span>caught <b className="bd-c-ok">{score.attacks_caught}</b></span>
        <span>blocked <b>{fmtUsd(score.dollars_blocked)}</b></span>
        <span>detect latency <b>{score.detection_latency_days == null ? "-" : `${score.detection_latency_days.toFixed(1)}d`}</b></span>
      </div>
      {attacks.length === 0 ? <Empty>no attack launched yet</Empty> : attacks.map((a) => (
        <article key={a.attack_id} className={`bd-attack bd-attack-${a.outcome}`}>
          <div className="bd-row">
            <span className="bd-mono bd-dim">d{a.day_launched}</span>
            <b className="bd-att-name">{a.display_name || a.scheme_id}</b>
            <span className="bd-mono bd-dim">{a.scheme_id}</span>
            <span className="bd-grow" />
            <Pill k={OUTCOME_KIND[a.outcome] ?? "dim"}>{a.outcome}</Pill>
          </div>
          {a.story && <div className="bd-prose"><Clip text={a.story} n={220} /></div>}
          <div className="bd-mono bd-kv">
            <span>target {fmtUsd(a.target_amount)}</span>
            <span>extracted <b className={a.amount_extracted > 0 ? "bd-c-bad" : undefined}>{fmtUsd(a.amount_extracted)}</b></span>
            <span>{a.detected_day != null ? `detected d${a.detected_day} (+${a.detected_day - a.day_launched}d)` : a.outcome === "pending" ? "resolves at day end" : "not detected"}</span>
            <span className="bd-dim">{a.attack_id}</span>
          </div>
        </article>
      ))}
    </>
  );
}

export function SchemeCatalog({ attacks }: { attacks: Attack[] }) {
  const rows = schemeCatalog(attacks);
  return (
    <table className="bd-tbl">
      <thead><tr><th>scheme</th><th className="bd-r">used</th><th className="bd-r">caught</th><th className="bd-r">extracted</th></tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.id} className={r.used ? undefined : "bd-unused"} title={r.blurb}>
            <td>
              <span>{r.name}</span>{r.evolved && <Pill k="evo">evolved</Pill>}
              <div className="bd-mono bd-dim bd-small">{r.id}{r.lastOutcome && <> · last <span className={`bd-o-${OUTCOME_KIND[r.lastOutcome] ?? "dim"}`}>{r.lastOutcome}</span></>}</div>
            </td>
            <td className="bd-r bd-mono">{r.used || "·"}</td>
            <td className="bd-r bd-mono">{r.used ? r.caught : "·"}</td>
            <td className="bd-r bd-mono">{r.used ? fmtUsd(r.extracted) : "·"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ---- evolution ----------------------------------------------------------------------------------------------------------------

export function Evolution({ agent, lineageId, timeline, generation, error }: { agent: "red" | "blue"; lineageId: string | null; timeline: LineageTimeline | null; generation: { generation: number; versions: Record<string, number> } | null; error: string | null }) {
  if (!lineageId) return <div className="bd-dim">single episode, no lineage: {agent}&apos;s playbook does not evolve in this run</div>;
  const versions = playbookHistory(timeline, agent);
  const gens = generationEntries(timeline);
  const inUse = generation?.versions?.[agent];
  return (
    <>
      <div className="bd-mono bd-kv">
        <span>lineage <b>{lineageId}</b></span>
        {generation && <span>generation <b>{generation.generation}</b></span>}
        {inUse != null && <span>{agent} playbook <b>v{inUse}</b></span>}
        {timeline?.status && <span className="bd-dim">{timeline.status}{timeline.partial ? " (partial)" : ""}</span>}
      </div>
      {error && <div className="bd-c-warn bd-small">{error}</div>}
      {!timeline && !error && <Empty>reading the lineage timeline…</Empty>}
      {timeline && versions.length === 0 && <Empty>no playbook versions for {agent} yet</Empty>}
      {versions.map((v) => {
        const lines = diffLines(v.diff);
        return (
          <article key={`${v.version}-${v.generation}`} className={`bd-pb${inUse === v.version ? " bd-pb-cur" : ""}`}>
            <div className="bd-row bd-mono">
              <b>v{v.version}</b>
              {v.parent_version != null && <span className="bd-dim">← v{v.parent_version}</span>}
              <span>gen {v.generation}</span>
              {v.day != null && <span>day {v.day}</span>}
              <Pill k={v.source === "reflect" ? "evo" : v.source === "seed" ? "dim" : "run"}>{v.source}</Pill>
              {inUse === v.version && <Pill k="ok">in use</Pill>}
            </div>
            {v.rationale && <div className="bd-prose">&ldquo;{v.rationale}&rdquo;</div>}
            {lines.length > 0 && (
              <div className="bd-diff bd-mono">
                {lines.map((l, i) => <div key={i} className={l.op === "+" ? "bd-d-add" : l.op === "~" ? "bd-d-chg" : "bd-d-del"}>{l.op} {l.key}: {clip(l.text, 160)}</div>)}
              </div>
            )}
          </article>
        );
      })}
      {gens.length > 0 && (
        <table className="bd-tbl bd-small-tbl">
          <thead><tr><th>gen</th><th className="bd-r">extracted</th><th className="bd-r">blocked</th><th className="bd-r">caught</th><th className="bd-r">fp cost</th></tr></thead>
          <tbody>
            {gens.map((g) => (
              <tr key={g.generation} className={generation?.generation === g.generation ? "bd-cur" : undefined}>
                <td className="bd-mono">{g.generation}{g.demo ? " demo" : ""}</td>
                <td className="bd-r bd-mono">{fmtUsd(g.score?.dollars_extracted ?? 0)}</td>
                <td className="bd-r bd-mono">{fmtUsd(g.score?.dollars_blocked ?? 0)}</td>
                <td className="bd-r bd-mono">{g.score?.attacks_caught ?? 0}/{g.score?.attacks_launched ?? 0}</td>
                <td className="bd-r bd-mono">{fmtUsd(g.score?.false_positive_cost ?? 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

// ---- blue: verdicts ---------------------------------------------------------------------------------------------------------

const KIND_LABEL: Record<VerdictRow["kind"], string> = { block: "BLOCK", escalate: "ESCALATE", noted: "ALLOW · NOTED", allow: "ALLOW" };

export function VerdictStats({ rows }: { rows: VerdictRow[] }) {
  const s = verdictStats(rows);
  return (
    <div className="bd-stats bd-mono">
      <span>verdicts <b>{s.total}</b></span>
      <span className="bd-c-bad">block <b>{s.counts.block}</b></span>
      <span className="bd-c-warn">escalate <b>{s.counts.escalate}</b></span>
      <span className="bd-c-note">noted <b>{s.counts.noted}</b></span>
      <span className="bd-c-ok">allow <b>{s.counts.allow}</b></span>
      {s.shadow > 0 && <span>shadow <b>{s.shadow}</b></span>}
      <span>latency avg <b>{fmtMs(s.avgMs)}</b> p95 <b>{fmtMs(s.p95Ms)}</b></span>
    </div>
  );
}

export function VerdictStream({ rows, emptyText }: { rows: VerdictRow[]; emptyText: string }) {
  if (!rows.length) return <Empty>{emptyText}</Empty>;
  return (
    <div className="bd-verdicts">
      {rows.slice(0, 80).map((v) => {
        const tail = (
          <>
            <span>{v.agent || "?"}</span>
            {v.entityId && <span>{v.entityType ? `${v.entityType} ` : ""}{v.entityId}</span>}
            {v.confidence != null && <span>conf {v.confidence.toFixed(2)}</span>}
            {v.latencyMs != null && <span>{fmtMs(v.latencyMs)}</span>}
            {!v.enforced && <span className="bd-c-warn">shadow: not enforced</span>}
            {v.cause && <span className={v.cause === "gate_unavailable" ? "bd-c-bad" : "bd-c-warn"}>cause {v.cause}</span>}
          </>
        );
        if (v.kind === "allow") {
          return (
            <div key={v.key} className="bd-vd bd-vd-allow">
              <span className="bd-vd-tag">ALLOW</span>
              <span className="bd-mono bd-vd-line">{v.action} <span className="bd-dim">· {v.entityId || "-"}{v.latencyMs != null ? ` · ${fmtMs(v.latencyMs)}` : ""}{v.enforced ? "" : " · shadow"}</span></span>
              <span className="bd-mono">{v.amount != null ? fmtUsd(v.amount) : ""}</span>
              <span className="bd-mono bd-dim">d{v.day} {hhmmss(v.ts)}</span>
            </div>
          );
        }
        return (
          <article key={v.key} className={`bd-vd bd-vd-${v.kind}`}>
            <div className="bd-row">
              <span className="bd-vd-tag">{KIND_LABEL[v.kind]}</span>
              <span className="bd-mono bd-vd-action">{v.action}</span>
              <span className="bd-mono bd-vd-amt">{v.amount != null ? fmtUsd(v.amount) : ""}</span>
              <span className="bd-grow" />
              <span className="bd-mono bd-dim">d{v.day} {hhmmss(v.ts)}</span>
            </div>
            {v.rules.length > 0 && <div className="bd-chips">{v.rules.map((r) => <span key={r} className="bd-chip" title={r}>{ruleName(r)} <span className="bd-mono bd-dim">{r}</span></span>)}</div>}
            {v.reason && <div className="bd-prose">{v.reason}</div>}
            <div className="bd-mono bd-kv bd-dim">{tail}</div>
          </article>
        );
      })}
    </div>
  );
}

export function Escalations({ rows, admin, live }: { rows: EscRow[]; admin: boolean; live: boolean }) {
  const [msg, setMsg] = useState<string>("");
  const open = rows.filter((r) => r.status === "open");
  const done = rows.filter((r) => r.status !== "open").slice(0, 6);
  const resolve = async (id: string, d: "approve" | "block") => {
    try { await api.resolve(id, d); setMsg(`${hhmmss(Date.now())} ${d} ${id}: sent`); } catch (e) { setMsg(`${hhmmss(Date.now())} ${d} ${id}: ${String(e instanceof Error ? e.message : e).slice(0, 120)}`); }
  };
  return (
    <>
      {open.length === 0 && <div className="bd-dim">no escalation waiting on a human</div>}
      {open.map((e) => (
        <article key={e.id} className="bd-esc">
          <div className="bd-row">
            <span className="bd-vd-tag">WAITING ON A HUMAN</span>
            <span className="bd-mono">{e.action}</span>
            <span className="bd-mono bd-vd-amt">{e.amount != null ? fmtUsd(e.amount) : ""}</span>
            <span className="bd-grow" />
            <span className={`bd-mono bd-countdown${e.remainingSec != null && e.remainingSec < 30 ? " bd-c-bad" : ""}`}>{e.remainingSec == null ? "-" : e.remainingSec <= 0 ? "expired" : fmtCountdown(e.remainingSec)}</span>
          </div>
          <div className="bd-prose">{e.reason}</div>
          <div className="bd-row bd-mono bd-dim">
            <span>{e.id}</span>{e.entityId && <span>{e.entityId}</span>}{e.cause && <span>cause {e.cause}</span>}
            <span className="bd-grow" />
            {admin && live ? (
              <>
                <button className="bd-btn bd-btn-ok" onClick={() => void resolve(e.id, "approve")}>approve</button>
                <button className="bd-btn bd-btn-bad" onClick={() => void resolve(e.id, "block")}>block</button>
              </>
            ) : <span>{admin ? "needs a backend to resolve" : "an admin resolves this"}</span>}
          </div>
        </article>
      ))}
      {msg && <div className="bd-mono bd-small bd-dim">{msg}</div>}
      {done.map((e) => (
        <div key={e.id} className="bd-mono bd-esc-done">
          <Pill k={e.status === "approve" ? "ok" : e.status === "block" ? "bad" : "dim"}>{e.status}</Pill> {e.action} {e.amount != null ? fmtUsd(e.amount) : ""} <span className="bd-dim">by {e.by || "-"} · {e.id}</span>
        </div>
      ))}
    </>
  );
}

export function RuleBoard({ verdicts }: { verdicts: UIState["verdicts"] }) {
  const rows = ruleBoard(verdicts);
  if (!rows.length) return <Empty>no rule has fired yet</Empty>;
  const max = Math.max(...rows.map((r) => r.total));
  return (
    <table className="bd-tbl">
      <thead><tr><th>rule</th><th className="bd-r">fires</th><th className="bd-r">block</th><th className="bd-r">esc</th><th className="bd-r">allow</th></tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.rule}>
            <td>
              <span>{ruleName(r.rule)}</span> <span className="bd-mono bd-dim bd-small">{r.rule}</span>
              <div className="bd-bar"><span className="bd-bar-b" style={{ width: `${(r.block / max) * 100}%` }} /><span className="bd-bar-e" style={{ width: `${(r.escalate / max) * 100}%` }} /><span className="bd-bar-a" style={{ width: `${(r.allow / max) * 100}%` }} /></div>
            </td>
            <td className="bd-r bd-mono"><b>{r.total}</b></td>
            <td className="bd-r bd-mono bd-c-bad">{r.block || "·"}</td>
            <td className="bd-r bd-mono bd-c-warn">{r.escalate || "·"}</td>
            <td className="bd-r bd-mono">{r.allow || "·"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function Confusion({ admin, live, rows }: { admin: boolean; live: boolean; rows: any[] | undefined }) {
  if (!admin) return <div className="bd-dim">admins only: it needs the ground truth, which viewers never receive</div>;
  if (!live) return <div className="bd-dim">needs a backend (the recording carries no ground truth)</div>;
  const c = confusionOf(rows);
  if (!c) return <div className="bd-dim">no verdicts scored yet</div>;
  return (
    <table className="bd-tbl bd-cm bd-mono">
      <thead><tr><th /><th className="bd-r">fraud</th><th className="bd-r">legit</th></tr></thead>
      <tbody>
        <tr><th>stopped</th><td className="bd-r bd-c-ok"><b>{c.trueBlock}</b></td><td className="bd-r bd-c-warn">{c.falseBlock}</td></tr>
        <tr><th>allowed</th><td className="bd-r bd-c-bad"><b>{c.missed}</b></td><td className="bd-r">{c.trueAllow}</td></tr>
      </tbody>
    </table>
  );
}

export function FlagsFreezes({ state }: { state: UIState }) {
  const flags = state.flags.slice(-10).reverse();
  const frozen = Object.entries(state.frozenVendors);
  return (
    <>
      {flags.length === 0 && frozen.length === 0 && <Empty>no flag raised, no vendor frozen</Empty>}
      {frozen.map(([id, reason]) => (
        <div key={id} className="bd-flag">
          <Pill k="bad">frozen</Pill> <span className="bd-mono">{id}</span> {reason && <span className="bd-prose-inline">{reason}</span>}
        </div>
      ))}
      {flags.map((f) => (
        <div key={f.flag_id} className="bd-flag">
          <Pill k={f.severity === "high" ? "bad" : f.severity === "medium" ? "warn" : "dim"}>{f.severity}</Pill>{" "}
          <span className="bd-mono bd-dim">d{f.day} {f.entity_type} {f.entity_id}</span>
          <div className="bd-prose">{f.reason}</div>
        </div>
      ))}
    </>
  );
}

export function DayReport({ state, live }: { state: UIState; live: boolean }) {
  const days = reportDays(state);
  const [pick, setPick] = useState<number | null>(null);
  const [texts, setTexts] = useState<Record<string, string | null>>({});
  const [err, setErr] = useState<string | null>(null);
  const day = pick != null && days.some((d) => d.day === pick) ? pick : days[days.length - 1]?.day ?? null;
  const row = days.find((d) => d.day === day) ?? null;
  const id = row?.report_id ?? null;
  const have = id != null && id in texts;
  useEffect(() => {
    if (!live || !id || have) return;
    let dead = false;
    setErr(null);
    api.fe.report(id).then((r) => { if (!dead) setTexts((t) => ({ ...t, [id]: reportText(r) })); }).catch((e) => { if (!dead) setErr(String(e instanceof Error ? e.message : e).slice(0, 120)); });
    return () => { dead = true; };
  }, [live, id, have]);
  if (!row || day == null) return <Empty>no end-of-day report yet (blue posts one after its audit)</Empty>;
  const text = live ? texts[row.report_id] : daySummary(state, day);
  return (
    <>
      <div className="bd-row bd-tabs">
        {days.map((d) => <button key={d.day} className={`bd-tab${d.day === day ? " bd-tab-on" : ""}`} onClick={() => setPick(d.day)}>day {d.day}</button>)}
        <span className="bd-grow" />
        <span className="bd-mono bd-dim bd-small">{row.report_id}</span>
      </div>
      {!live && <div className="bd-c-warn bd-small">no backend: a summary built from the day&apos;s events, not blue&apos;s report</div>}
      {err && <div className="bd-c-bad bd-small">GET /reports/{row.report_id}: {err}</div>}
      {text ? <div className="bd-report"><Markdown text={text} /></div> : !err && <Empty>{live && !(row.report_id in texts) ? "reading the report…" : "the report has no text"}</Empty>}
    </>
  );
}
