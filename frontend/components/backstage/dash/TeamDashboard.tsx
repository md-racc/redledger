"use client";
// The red and blue technical dashboards: a window into what one agent is actually doing in the run on stage. Owner: Dev R.
//
// Served at /backstage/red and /backstage/blue, and at `/` on red.<domain> / blue.<domain> (middleware.ts). Same data as the raw
// console (useBackstage: joins the active run, socket from event 0, the recorded loop when no backend answers), laid out as
// instrumentation panels a projector can carry. `R` (or the header button) switches to the raw console, which stays the evidence view.
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { provenance } from "@/lib/arena/provenance";
import { useRole } from "@/lib/role";
import { attacksNewestFirst } from "../derive";
import { hhmmss, TEAM_KEYS } from "../raw";
import { useBackstage, type Want } from "../useBackstage";
import { agentTurns, asTimeline, creditsOf, escalationRows, fmtCredits, generationOf, lineageIdOf, verdictRows, withLatency, type LineageTimeline } from "./dash";
import { AttackList, Confusion, DayReport, Escalations, Evolution, FlagsFreezes, Panel, RuleBoard, SchemeCatalog, ThoughtStream, ToolTimeline, VerdictStats, VerdictStream } from "./panels";

export type DashTeam = "red" | "blue";

const ROLE_LINE: Record<DashTeam, string> = {
  red: "red-team agent: commits fraud against the synthetic company through the Ledger API",
  blue: "controller agent: gates every money-moving action, audits the books, posts the day's report",
};

/** The lineage timeline (playbook versions + diffs), read again when a playbook.updated arrives and every 20 s. */
function useLineageTimeline(lineageId: string | null, live: boolean, bump: number): { timeline: LineageTimeline | null; error: string | null } {
  const [timeline, setTimeline] = useState<LineageTimeline | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setTimeline(null);
    setError(null);
  }, [lineageId]);
  useEffect(() => {
    if (!lineageId || !live) return;
    let dead = false;
    const read = () => api.fe.lineageTimeline(lineageId)
      .then((raw) => { if (!dead) { setTimeline(asTimeline(raw, lineageId)); setError(null); } })
      .catch((e) => { if (!dead) setError(`GET /fe/lineages/${lineageId}/timeline: ${String(e instanceof Error ? e.message : e).slice(0, 100)}`); });
    void read();
    const t = setInterval(read, 20_000);
    return () => { dead = true; clearInterval(t); };
  }, [lineageId, live, bump]);
  return { timeline, error };
}

export function TeamDashboard({ team, onRaw }: { team: DashTeam; onRaw: () => void }) {
  const router = useRouter();
  const role = useRole();
  const admin = role === "admin";
  // viewers get 403 for the confusion matrix (it needs the ground truth): never ask for it on their behalf
  // the verdicts read carries latency_ms for a battlefield whose events do not
  const want = useMemo<Want[]>(() => (team === "blue" ? (admin ? ["verdicts", "confusion"] : ["verdicts"]) : []), [team, admin]);
  const bs = useBackstage(want);
  const { state, events, episode, now, mode } = bs;
  const live = mode === "live";

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const i = Number(e.key);
      if (i >= 1 && i <= TEAM_KEYS.length) router.push(`/backstage/${TEAM_KEYS[i - 1]}`);
      else if (e.key === "0") router.push("/backstage");
      else if (e.key === "Escape") router.push("/");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [router]);

  const turns = useMemo(() => agentTurns(events, team), [events, team]);
  const credits = useMemo(() => creditsOf(events), [events]);
  const verdicts = useMemo(() => (team === "blue" ? withLatency(verdictRows(events), bs.agg.verdicts) : []), [events, team, bs.agg.verdicts]);
  const lineageId = useMemo(() => lineageIdOf(events, episode, bs.activeRun), [events, episode, bs.activeRun]);
  const generation = useMemo(() => generationOf(events), [events]);
  const pbBump = useMemo(() => events.filter((e) => e.type === "playbook.updated" || e.type === "generation.ended").length, [events]);
  const { timeline, error: tlError } = useLineageTimeline(lineageId, live, pbBump);

  const prov = provenance({
    backend: { state: live ? "live" : mode === "recorded" ? "offline" : "checking", agents: bs.health?.agents ?? null, keyless: false },
    source: live ? "live" : mode === "recorded" ? "mock" : "idle",
    inShow: false,
    episodeId: episode?.id ?? null,
  });
  const me = prov.agents.find((a) => a.name === team);
  const health = bs.health?.agents?.[team] as { model?: string; dry_run?: boolean; ok?: boolean } | undefined;
  const model = !live ? "-" : !health ? "unknown" : health.ok === false ? "DOWN" : health.dry_run ? "keyless (DRY_RUN)" : health.model ?? "?";
  const lastAge = bs.lastEventAt == null ? null : Math.max(0, Math.round((now - bs.lastEventAt) / 1000));
  const keyless = me?.mode === "keyless";
  const mineCredits = credits.byAgent[team] ?? 0;
  const noThink = mode === "recorded"
    ? `the recording has no agent.thinking for ${team} (it was made with keyless agents)`
    : keyless ? `${team} is keyless (DRY_RUN): canned turns carry no thinking` : `waiting for ${team}'s next turn`;
  const noTools = mode === "recorded"
    ? `the recording has no ${team} turns with tool calls`
    : keyless ? `${team} is keyless (DRY_RUN): no tool calls to show` : `no ${team} turn yet in this episode`;

  const header = (
    <header className="bd-dash-h">
      <div className="bd-dash-title">
        <span className={`bd-team-tag bd-team-${team}`}>{team.toUpperCase()}</span>
        <div>
          <h1>{team === "red" ? "Red agent" : "Blue agent"} <span className="bd-dim">· live instrumentation</span></h1>
          <div className="bd-dim bd-role-line">{ROLE_LINE[team]}</div>
        </div>
        <span className="bd-grow" />
        <span className="bd-mono bd-dim bd-clock">{hhmmss(now)}</span>
        <button className="bd-btn" onClick={onRaw} title="the raw console: every event and read, unformatted (key R)">raw console <span className="bd-dim">R</span></button>
      </div>
      <div className="bd-tiles">
        <div className={`bd-tile bd-prov bd-prov-${prov.badge.toLowerCase()}`} title={prov.meaning}>
          <span className="bd-t-l">source</span>
          <span className="bd-t-v"><span className="bd-dot" />{prov.badge}</span>
        </div>
        <div className="bd-tile bd-wide"><span className="bd-t-l">episode</span><span className="bd-t-v bd-mono">{episode?.id ?? "-"}</span></div>
        <div className="bd-tile"><span className="bd-t-l">day</span><span className="bd-t-v bd-mono">{episode ? `${Math.min(episode.current_day, episode.days)}/${episode.days}${state.finished || episode.status === "finished" ? " done" : ""}` : "-"}</span></div>
        <div className="bd-tile"><span className="bd-t-l">controller</span><span className={`bd-t-v bd-mono bd-mode-${state.controllerMode}`}>{(state.episodeId ? state.controllerMode : episode?.controller_mode ?? "-").toUpperCase()}</span></div>
        <div className="bd-tile bd-wide"><span className="bd-t-l">{team} model</span><span className="bd-t-v bd-mono">{model}</span></div>
        <div className="bd-tile" title="sum of turn.ended.factory_credits this run"><span className="bd-t-l">credits</span><span className="bd-t-v bd-mono">{credits.reported ? fmtCredits(mineCredits) : "-"}<span className="bd-dim bd-small"> {credits.reported ? `/ ${fmtCredits(credits.total)} run` : live ? "none reported" : ""}</span></span></div>
        <div className="bd-tile"><span className="bd-t-l">feed</span><span className="bd-t-v bd-mono">{events.length}<span className="bd-dim bd-small"> ev · {bs.rate}/min · {lastAge == null ? "no events" : `${lastAge}s ago`}</span></span></div>
        <div className="bd-tile"><span className="bd-t-l">battlefield</span><span className={`bd-t-v bd-mono ${live ? "bd-c-ok" : mode === "recorded" ? "bd-c-bad" : "bd-dim"}`}>{live ? `${bs.healthMs ?? "?"}ms` : mode === "recorded" ? "no answer" : "…"}</span></div>
      </div>
      {mode === "recorded" && <div className="bd-banner">[FAIL] battlefield unreachable: looping the recorded episode. Nothing on this screen is live.</div>}
    </header>
  );

  if (team === "red") {
    const attacks = attacksNewestFirst(state);
    return (
      <div className="bd-dash bd-dash-red">
        {header}
        <main className="bd-cols bd-cols-red">
          <div className="bd-col">
            <Panel title="Thought stream" meta={<span className="bd-mono">agent.thinking · {turns.length} turns</span>} grow={1}>
              <ThoughtStream turns={turns} now={now} emptyText={noThink} />
            </Panel>
          </div>
          <div className="bd-col">
            <Panel title="Tool calls" meta={<span className="bd-mono">agent.tool_call → agent.tool_result</span>} grow={1}>
              <ToolTimeline turns={turns} now={now} emptyText={noTools} />
            </Panel>
          </div>
          <div className="bd-col">
            <Panel title="Attacks" meta={<span className="bd-mono">attack.launched / attack.outcome</span>} grow={3}>
              <AttackList attacks={attacks} score={state.score} />
            </Panel>
            <Panel title="Scheme catalog" meta={<span className="bd-mono">{new Set(attacks.map((a) => a.scheme_id)).size} of 8 used</span>} grow={2}>
              <SchemeCatalog attacks={attacks} />
            </Panel>
            <Panel title="Evolution" meta={<span className="bd-mono">playbook versions</span>} grow={lineageId ? 2 : 0} className={lineageId ? undefined : "bd-panel-quiet"}>
              <Evolution agent="red" lineageId={lineageId} timeline={timeline} generation={generation} error={tlError} />
            </Panel>
          </div>
        </main>
      </div>
    );
  }

  const escs = escalationRows(state, now);
  const openEsc = escs.filter((e) => e.status === "open").length;
  return (
    <div className="bd-dash bd-dash-blue">
      {header}
      <main className="bd-cols bd-cols-blue">
        <div className="bd-col">
          <Panel title="Gate verdicts" meta={<span className="bd-mono">gate.verdict · newest first</span>} grow={3}>
            <VerdictStats rows={verdicts} />
            <VerdictStream rows={verdicts} emptyText={state.controllerMode === "off" && state.episodeId ? "controller is OFF: the gate is never consulted" : "no verdict yet"} />
          </Panel>
          <Panel title="Rule board" meta={<span className="bd-mono">rules_fired per verdict</span>} grow={2}>
            <RuleBoard verdicts={state.verdicts} />
          </Panel>
        </div>
        <div className="bd-col">
          <Panel title="Escalations" meta={<span className="bd-mono">{openEsc ? `${openEsc} open` : "escalation.opened / resolved"}</span>} grow={0} className={openEsc ? "bd-panel-alert" : undefined}>
            <Escalations rows={escs} admin={admin} live={live} />
          </Panel>
          <Panel title="Audit: thought stream" meta={<span className="bd-mono">blue&apos;s audit turn</span>} grow={3}>
            <ThoughtStream turns={turns} now={now} emptyText={noThink} />
          </Panel>
          <Panel title="Audit: tool calls" meta={<span className="bd-mono">agent.tool_call → agent.tool_result</span>} grow={3}>
            <ToolTimeline turns={turns} now={now} emptyText={noTools} />
          </Panel>
        </div>
        <div className="bd-col">
          <Panel title="Flags & freezes" meta={<span className="bd-mono">{state.flags.length} flags · {Object.keys(state.frozenVendors).length} frozen</span>} grow={2}>
            <FlagsFreezes state={state} />
          </Panel>
          <Panel title="End-of-day report" meta={<span className="bd-mono">report.posted</span>} grow={3}>
            <DayReport state={state} live={live} />
          </Panel>
          <Panel title="Confusion matrix" meta={<span className="bd-mono">{admin ? "admin" : "admins only"}</span>} grow={0}>
            <Confusion admin={admin} live={live} rows={bs.agg.confusion} />
          </Panel>
          <Panel title="Evolution" meta={<span className="bd-mono">playbook versions</span>} grow={lineageId ? 2 : 0} className={lineageId ? undefined : "bd-panel-quiet"}>
            <Evolution agent="blue" lineageId={lineageId} timeline={timeline} generation={generation} error={tlError} />
          </Panel>
        </div>
      </main>
    </div>
  );
}
