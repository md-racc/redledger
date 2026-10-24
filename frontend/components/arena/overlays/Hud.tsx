"use client";
// Heads-up display for the arena stage: episode state, the converge trigger, controller mode, the money scoreboard
// and a roster of every agent (also the keyboard route to the dossier).
import { useState } from "react";
import { api } from "@/lib/api";
import { rosterOf, TEAM_META, TEAMS } from "@/lib/arena/roster";
import { useArena } from "@/lib/arena/store";
import type { Feed } from "@/lib/arena/useFeed";
import type { ControllerMode } from "@/lib/types";

const money = (n: number) => `$${Math.round(n).toLocaleString()}`;
const MODES: ControllerMode[] = ["off", "shadow", "enforce"];

export function Hud({ feed }: { feed: Feed }) {
  const stage = useArena((s) => s.stage);
  const simPhase = useArena((s) => s.simPhase);
  const model = useArena((s) => s.modelState);
  const selected = useArena((s) => s.selectedId);
  const select = useArena((s) => s.select);
  const actions = useArena((s) => s.actions);
  const cinematic = useArena((s) => s.cinematic);
  const setCinematic = useArena((s) => s.setCinematic);
  const [roster, setRoster] = useState(false);
  const { state, source } = feed;
  const arenaFormed = simPhase === "engaged" || simPhase === "converging";

  const sourceLabel = source === "live" ? "LIVE" : source === "mock" ? "REPLAY" : "STANDBY";

  return (
    <div className={`hud ${stage === "arena" ? "is-on" : ""}`} aria-hidden={stage !== "arena"}>
      <header className="hud-top">
        <div className="hud-brand">
          <span><b>red</b>ledger</span>
          <span className={`hud-chip src-${source}`}><i />{sourceLabel}</span>
          {state.episodeId && <span className="hud-chip">day {state.currentDay}/{state.days}</span>}
        </div>
        <div className="hud-actions">
          <button className="btn ghost" onClick={() => setCinematic(!cinematic)} aria-pressed={cinematic} title="The camera frames each fraud attempt as it plays out">Auto-cam <kbd>{cinematic ? "on" : "off"}</kbd></button>
          <button className="btn ghost" onClick={() => setRoster((v) => !v)} aria-expanded={roster}>Roster <kbd>{roster ? "–" : "+"}</kbd></button>
          <button className="btn ghost" onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}>Back to tour <kbd>↑</kbd></button>
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

      <section className="hud-controls">
        <button className="btn primary" onClick={() => void feed.run(state.controllerMode === "off" ? "enforce" : state.controllerMode)} disabled={feed.running}>
          <i className="dot" />{feed.running ? "Episode running" : state.episodeId ? "Run again" : "Run episode"}
        </button>
        <button className="btn" onClick={() => (arenaFormed ? actions.disperse() : actions.converge())}>
          {arenaFormed ? "Send them back" : "Send agents in"}
        </button>
        <div className="seg" role="group" aria-label="Controller mode">
          {MODES.map((m) => (
            <button key={m} className={state.controllerMode === m ? "on" : ""} onClick={() => void feed.setController(m).catch(() => {})}>{m}</button>
          ))}
        </div>
        <p className="hud-note">{feed.note}{model === "fallback" ? " · stand-in palace" : ""}</p>
      </section>

      <EscalationBar feed={feed} />
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

/** Open escalations are a human decision (README §3): approve or block right from the arena. */
function EscalationBar({ feed }: { feed: Feed }) {
  const open = Object.values(feed.state.escalations).filter((e) => e.status === "open");
  if (!open.length) return null;
  const e = open[0];
  return (
    <div className="escalation" role="alert">
      <span className="escalation-tag">Needs a human</span>
      <p>{e.action} {e.amount ? money(e.amount) : ""} · {e.reason}</p>
      <button className="btn" onClick={() => void api.resolve(e.escalation_id, "approve").catch(() => {})}>Approve</button>
      <button className="btn primary" onClick={() => void api.resolve(e.escalation_id, "block").catch(() => {})}>Block</button>
    </div>
  );
}
