"use client";
// Heads-up display for the arena stage: episode state, the show and converge triggers, controller mode, the money
// scoreboard, the attack console, a roster of every agent (also the keyboard route to the dossier) and the escalation
// that needs a human.
import { useEffect, useRef, useState } from "react";
import { explainEscalation } from "@/lib/arena/escalation";
import { rosterOf, TEAM_META, TEAMS } from "@/lib/arena/roster";
import { provenance } from "@/lib/arena/provenance";
import { useArena } from "@/lib/arena/store";
import type { Feed } from "@/lib/arena/useFeed";
import type { ControllerMode } from "@/lib/types";
import type { ShowController } from "../useShow";
import type { PitchController } from "../usePitch";
import { canApprove, SIDE_SCREENS } from "@/lib/arena/pitch";
import { Doors } from "./Doors";
import { Raw } from "./Raw";
import { ThreatConsole } from "./ThreatConsole";
import { isAdmin, useRole } from "@/lib/role";

const money = (n: number) => `$${Math.round(n).toLocaleString()}`;
const MODES: ControllerMode[] = ["off", "shadow", "enforce"];

export function Hud({ feed, show, pitch }: { feed: Feed; show: ShowController; pitch?: PitchController }) {
  const stage = useArena((s) => s.stage);
  const simPhase = useArena((s) => s.simPhase);
  const model = useArena((s) => s.modelState);
  const selected = useArena((s) => s.selectedId);
  const select = useArena((s) => s.select);
  const actions = useArena((s) => s.actions);
  const cinematic = useArena((s) => s.cinematic);
  const setCinematic = useArena((s) => s.setCinematic);
  const panel = useArena((s) => s.panel);
  const setPanel = useArena((s) => s.setPanel);
  const [roster, setRoster] = useState(false);
  const clicks = useRef<number[]>([]);
  // three quick clicks on the brand open the backstage hub (the same as pressing B)
  const brandClick = () => {
    const now = performance.now();
    clicks.current = [...clicks.current.filter((t) => now - t < 700), now];
    if (clicks.current.length >= 3) { clicks.current = []; if (isAdmin()) window.open("/backstage", "_blank", "noopener"); }
  };
  const [threat, setThreat] = useState(false);
  const { state, source } = feed;
  // viewers watch: everything that changes the sim is disabled for them (the proxy refuses it anyway; lib/admin.ts)
  const admin = useRole() === "admin";
  const arenaFormed = simPhase === "engaged" || simPhase === "converging";
  const inShow = show.status === "playing" || show.status === "paused";
  const inPitch = !!pitch && pitch.phase !== "off";

  // the show hands over: the attack console opens so the first thing a visitor can do is fire something
  useEffect(() => { if (show.status === "done") setThreat(true); }, [show.status]);
  useEffect(() => { if (inShow) { setThreat(false); setRoster(false); } }, [inShow]);

  const { backend } = feed;
  const apiLabel = backend.state === "live" ? (backend.keyless ? "open · agents keyless" : "open") : backend.state === "offline" ? "closed" : "calling";
  const prov = provenance({ backend, source, inShow, episodeId: state.episodeId, recording: feed.recording });

  return (
    <div className={`hud ${stage === "arena" ? "is-on" : ""} ${inShow ? "in-show" : ""} ${inPitch ? "in-pitch" : ""}`} aria-hidden={stage !== "arena"}>
      <header className="hud-top">
        <div className="hud-brand">
          <span className="brand" onClick={brandClick}><b>red</b>ledger</span>
          <span className="stat" title="The battlefield behind the /api/bf proxy"><i className={`led led-${backend.state}`} />Ledger <b>{apiLabel}</b></span>
          <span className={`stat badge-${prov.badge.toLowerCase()}`} title={prov.meaning}>Source <b>{prov.badge}</b>{prov.recordedOn && <> · {prov.recordedOn}</>}</span>
          <span className="stat stat-agents" title={`Each agent's own /health. live = a real model is running it, keyless = canned turns. ${prov.agentsLine}${prov.episode ? ` · ${prov.episode}` : ""}`}>Agents <b>{prov.agentsLine}</b></span>
          {state.episodeId && <span className="stat">Day <b>{state.currentDay}/{state.days}</b></span>}
          <span className={`stat mode-${state.controllerMode}`}>Controller <b>{state.controllerMode}</b></span>
        </div>
        <div className="hud-actions">
          {pitch && (admin || inPitch) && <button className={`btn ghost ${inPitch ? "armed" : ""}`} onClick={inPitch ? pitch.stop : pitch.start} title="Pitch mode: a live episode on this screen, narrated from its real events (P; Esc leaves)">{inPitch ? "■ Leave pitch" : "● Live pitch"} <kbd>{inPitch ? "Esc" : "P"}</kbd></button>}
          <button className="btn ghost" onClick={show.start} title="The whole site in 90 seconds (S)">▶ 90s show <kbd>S</kbd></button>
          <button className="btn ghost" onClick={() => setCinematic(!cinematic)} aria-pressed={cinematic} title="The camera frames each fraud attempt as it plays out">Auto-cam <kbd>{cinematic ? "on" : "off"}</kbd></button>
          <button className="btn ghost" onClick={() => setRoster((v) => !v)} aria-expanded={roster}>Roster <kbd>{roster ? "–" : "+"}</kbd></button>
          <button className="btn ghost" onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}>Tour <kbd>↑</kbd></button>
        </div>
      </header>

      {roster && (
        <aside className="roster" aria-label="Agent roster">
          {TEAMS.map((team) => (
            <section key={team} className={`roster-group tag-${team}`}>
              <h3>{TEAM_META[team].label}<span>{rosterOf(team).length}</span></h3>
              <ul>
                {rosterOf(team).map((a) => (
                  <li key={a.id}>
                    <button className={selected === a.id ? "on" : ""} onClick={() => select(selected === a.id ? null : a.id)}>{a.name}</button>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </aside>
      )}

      <section className="hud-score" aria-label="Scoreboard">
        <Tile label="Stolen" value={money(state.score.dollars_extracted)} tone="red" />
        <Tile label="Blocked" value={money(state.score.dollars_blocked)} tone="blue" />
        <Tile label="False-positive cost" value={money(state.score.false_positive_cost)} tone="amber" />
        <Tile label="Caught" value={`${state.score.attacks_caught}/${state.score.attacks_launched}`} tone="green" />
      </section>

      <ThreatConsole open={threat && !inShow && admin} mode={state.controllerMode} onClose={() => setThreat(false)} onLaunch={feed.launchAttack} />

      <section className="hud-controls">
        <button className="btn primary" onClick={() => void feed.run(state.controllerMode === "off" ? "enforce" : state.controllerMode)} disabled={feed.running || !admin}>
          {feed.running && <i className="dot" />}{feed.running ? "Running" : state.episodeId ? "Run again" : "Run episode"}
        </button>
        <button className={`btn ${threat ? "armed" : ""}`} onClick={() => setThreat((v) => !v)} aria-expanded={threat} disabled={!admin}>Launch attack</button>
        <button className="btn" onClick={() => setPanel(panel === "compare" ? null : "compare")}>Compare</button>
        <button className="btn" onClick={() => setPanel(panel === "evolve" ? null : "evolve")}>Evolution</button>
        <button className="btn" onClick={() => setPanel(panel === "report" ? null : "report")}>Report</button>
        <button className="btn" onClick={() => setPanel(panel === "lenders" ? null : "lenders")} title="What the big lenders have said about AI agents in their accounts, with sources (L)">Lenders</button>
        <button className="btn" onClick={() => (arenaFormed ? actions.disperse() : actions.converge())}>
          {arenaFormed ? "Send them back" : "Send agents in"}
        </button>
        <div className="seg" role="group" aria-label="Controller mode">
          {MODES.map((m) => (
            <button key={m} className={state.controllerMode === m ? "on" : ""} onClick={() => void feed.setController(m).catch(() => {})} disabled={!admin}>{m}</button>
          ))}
        </div>
        <p className="hud-note">{feed.note}{model === "fallback" ? " · stand-in palace" : ""}</p>
      </section>

      {/* the side screens on stage, named for the audience; an admin's screen only, like the doors (the consoles stay hidden from viewers) */}
      {inPitch && admin && (
        <p className="hud-screens" title="The other screens on stage: red's and blue's own consoles">
          {SIDE_SCREENS.map((d, i) => <span key={d}>{i > 0 && " · "}{d}</span>)}
        </p>
      )}

      <EscalationBar feed={feed} pitch={inPitch} />
      <Doors show={stage === "arena" && !inShow} />
    </div>
  );
}

function Tile({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div className={`tile tone-${tone}`}>
      <span>{label}</span>
      <b>{value}</b>
    </div>
  );
}

/** Open escalations are a human decision (README §3): approve or block right from the arena, against the clock. */
function EscalationBar({ feed, pitch = false }: { feed: Feed; pitch?: boolean }) {
  const admin = useRole() === "admin";
  const open = Object.values(feed.state.escalations).filter((e) => e.status === "open");
  const e = open[0];
  const [left, setLeft] = useState(0);
  const [total, setTotal] = useState(1);
  // the clock runs to whichever comes first: the battlefield's own expiry, or the auto-block (the show's, pitch mode's 40 s)
  const auto = e ? feed.deadlines[e.escalation_id] : undefined;
  useEffect(() => {
    if (!e) return;
    const expires = new Date(e.expires_at).getTime();
    const due = Math.min(Number.isFinite(expires) ? expires : Infinity, auto ?? Infinity);
    const startedAt = Date.now();
    setTotal(Math.max(1, Math.ceil((due - startedAt) / 1000)));
    const tick = () => setLeft(Math.max(0, Math.ceil((due - Date.now()) / 1000)));
    tick();
    const t = setInterval(tick, 250);
    return () => clearInterval(t);
  }, [e, auto]);
  if (!e) return null;
  // the backend's action id and reason are for developers: say what is about to happen, why it stopped, and what each button does
  const x = explainEscalation(e, feed.state.verdicts.find((v) => v.verdict_id === e.verdict_id));
  // a real recording played back: its outcomes are what happened, so the only honest button is Block
  const approvable = canApprove({ recording: feed.recording, source: feed.source });
  return (
    <div className={`escalation ${pitch ? "is-pitch" : ""} ${x.failSafe ? "is-failsafe" : ""}`} role="alert" style={{ ["--left" as string]: String(Math.min(1, left / total)) }}>
      {pitch && <i className="escalation-meter" aria-hidden />}
      <div className="escalation-head">
        <span className="escalation-tag">{x.failSafe ? "Fail-safe · your decision" : "Your decision"}</span>
        <span className="escalation-clock" title="If nobody decides before it runs out, the payment is blocked"><b>{left}</b> s left</span>
      </div>
      <h3>{x.title}</h3>
      <p className="escalation-what">{x.what}</p>
      <div className="escalation-why">
        <h4>{x.failSafe ? "Why it is held" : "Why the controller stopped it"}</h4>
        <ul>{x.why.map((w) => <li key={w}>{w}</li>)}</ul>
      </div>
      <div className="escalation-act">
        {approvable && <button className="esc-btn approve" disabled={!admin} onClick={() => void feed.resolveEscalation(e.escalation_id, "approve").catch(() => {})}><b>{x.approve.label}</b><span>{x.approve.result}</span></button>}
        <button className="esc-btn block" disabled={!admin} onClick={() => void feed.resolveEscalation(e.escalation_id, "block").catch(() => {})}><b>{x.block.label}</b><span>{x.block.result}</span></button>
      </div>
      <p className="escalation-foot">{approvable ? "" : "A recording: what happened next on prod stays as it was, so it can only be blocked. "}{pitch && !admin && approvable ? "The presenter decides. " : ""}If nobody decides before the clock runs out, it is blocked.</p>
      <Raw data={{ escalation: e, verdict: feed.state.verdicts.find((v) => v.verdict_id === e.verdict_id) ?? null }} />
    </div>
  );
}
