"use client";
// Backstage: the raw view of the run, for the other laptops. Owner: Dev R.
//
// Plain on purpose. It is not a dashboard: it is the evidence that the code is running right now. Live checks that pass or fail, the
// selections coming from the arena laptop, every API call the frontend makes to battlefield (from all laptops), the events of this
// team's agents as they arrive, and the JSON the read API returns. No navigation is drawn: the consoles are reached by address
// (/backstage/red, /green, /blue, /battlefield), by 1-4 on the keyboard, and A returns to the arena.
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import { blueIdForRule, ROSTER_BY_ID } from "@/lib/arena/roster";
import { clientId, useSync } from "@/lib/sync/client";
import { liveClients } from "@/lib/sync/hub";
import { RECORDING } from "@/lib/backstage/recording";
import { useRole } from "@/lib/role";
import type { ControllerMode } from "@/lib/types";
import { FAIL_SAFE_NOTE, FAIL_SAFE_TAG, failSafeLabel, isFailSafe } from "@/lib/verdictCause";
import { avgLatency, confusion, ruleBoard, ruleName, schemeName, thoughts, toolRows, verdictCounts } from "./derive";
import { concerns, demoPlan, eventLine, hhmmss, liveChecks, msgLine, TEAM_KEYS, teamEvents, trafficLine, type TeamKey } from "./raw";
import { useBackstage, type Want } from "./useBackstage";

const WANT: Record<TeamKey | "hub", Want[]> = { hub: [], red: [], green: ["snapshot", "apAging"], blue: ["verdicts", "confusion", "reports"], battlefield: ["timeline", "snapshot"] };
const MODES: ControllerMode[] = ["off", "shadow", "enforce"];

const Sec = ({ title, children }: { title: string; children: ReactNode }) => (
  <section>
    <h2>== {title} ==</h2>
    {children}
  </section>
);
const Line = ({ hl, children }: { hl?: boolean; children: ReactNode }) => <div className={hl ? "hl" : undefined}>{children}</div>;
const usd = (n: unknown) => `$${Math.round(Number(n) || 0).toLocaleString()}`;

export function RawConsole({ team }: { team: TeamKey | "hub" }) {
  const router = useRouter();
  // everything here is live (the laptop's id, the clock, the origin), so the server renders nothing and the browser does the lot
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  // red and blue replay the real live-red recording when no backend answers; `?replay=1` forces it (the backend, messy, on demand)
  const replay = typeof window !== "undefined" && /[?&]replay(=1|=true)?(&|$)/.test(window.location.search);
  const bs = useBackstage(WANT[team], { forceRecorded: replay, ...(team === "red" || team === "blue" ? { recording: RECORDING } : {}) });
  const sync = useSync(`backstage${team}`);
  const viewer = useRole() !== "admin"; // asks the server once; a viewer's console only watches (the operator controls below are for admins)
  const { state, events, episode, agg, now } = bs;
  const selected = sync.state.selected?.id ?? null;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const i = Number(e.key);
      if (i >= 1 && i <= TEAM_KEYS.length) router.push(`/backstage/${TEAM_KEYS[i - 1]}`);
      else if (e.key === "0") router.push("/backstage");
      else if (e.key === "a" || e.key === "A" || e.key === "Escape") router.push("/");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [router]);

  const checks = useMemo(
    () => liveChecks({ mode: bs.mode, healthMs: bs.healthMs, agents: bs.health?.agents ?? null, replaying: bs.recording, answer: bs.answer, eventsInLastMinute: bs.rate, lastEventAt: bs.lastEventAt, feed: bs.feed, episodeStatus: episode?.status ?? null, eventsHeld: events.length, verdicts: state.verdicts.length, now, sync: { link: sync.link, quietMs: sync.quietMs, state: sync.state }, trafficCount: sync.traffic.length, viewer }),
    [viewer, bs.mode, bs.healthMs, bs.health, bs.recording, bs.answer, bs.rate, bs.lastEventAt, bs.feed, episode?.status, events.length, state.verdicts.length, now, sync.link, sync.quietMs, sync.state, sync.traffic.length],
  );
  const clients = liveClients(sync.state, now);
  const shown = team === "hub" ? [] : teamEvents(team, events).slice(-24).reverse();
  const actions = sync.msgs.filter((m) => m.kind !== "hello").slice(-9).reverse();
  const sel = selected ? ROSTER_BY_ID[selected] : null;
  // the consoles' own polling would drown the log: show the demo laptop's calls and every operator call, count the rest
  const polls = sync.traffic.filter((t) => t.method === "GET" && t.client.startsWith("backstage"));
  const calls = sync.traffic.filter((t) => !(t.method === "GET" && t.client.startsWith("backstage")));
  const mine = sel && team !== "hub" && team !== "battlefield" && sel.team === team;

  if (!mounted) return <div className="raw"><pre>redledger backstage</pre></div>;
  return (
    <div className="raw">
      <pre>
        {`redledger backstage :: ${team === "hub" ? "hub" : team.toUpperCase()}     laptop ${clientId()}     ${hhmmss(now)}\n`}
        {`backend    ${bs.mode === "live" ? `LIVE  health ${bs.healthMs ?? "?"}ms` : bs.mode === "connecting" ? (bs.answer ? `REFUSED  ${bs.answer}` : "connecting") : bs.recording ? "REPLAY of the recorded live-red run (recordings)" : "NO ANSWER (recorded loop)"}\n`}
        {`following  ${episode ? `${episode.id}  ${bs.pinned ? "[pinned]" : "[newest]"}  mode=${episode.controller_mode}  status=${episode.status}  day ${Math.min(episode.current_day, episode.days)}/${episode.days}` : "(no episode yet)"}\n`}
        {`events     ${events.length} held, ${bs.rate}/min${bs.feed ? ` via ${bs.feed.via === "polling" ? "REST (socket blocked)" : bs.feed.via}` : ""}      relay ${sync.link}, ${clients.length} laptop(s): ${clients.map((c) => `${c.id}`).join(" ") || "-"}`}
      </pre>
      {bs.mode === "live" && bs.episodes.length > 1 && (
        <div>
          follow:{" "}
          <select value={bs.pinned ?? ""} onChange={(e) => bs.pin(e.target.value || null)} aria-label="Episode to follow">
            <option value="">newest</option>
            {bs.episodes.slice(0, 15).map((e) => <option key={e.id} value={e.id}>{e.id} {e.controller_mode} {e.status}</option>)}
          </select>
        </div>
      )}

      <Sec title="LIVE CHECKS">
        {checks.map((c) => (
          <Line key={c.label}>
            {c.adminOnly
              ? <span className="dim">{`[ -- ] ${c.label.padEnd(50, ".")} — ${c.detail}`}</span>
              : <><span className={c.ok === true ? "ok" : c.ok === false ? "bad" : "dim"}>[{c.ok === true ? " OK " : c.ok === false ? "FAIL" : " -- "}]</span> {c.label.padEnd(50, ".")} <span className="dim">{c.detail}</span></>}
          </Line>
        ))}
      </Sec>

      <Sec title="DEMO SCREEN (what the arena laptop is doing)">
        <pre>
          {`selected    ${sync.state.selected ? `${sync.state.selected.id}  "${sync.state.selected.name}"  (${sync.state.selected.team})` : "-"}\n`}
          {`view        stage=${sync.state.stage ?? "-"}  card=${sync.state.panel ?? "-"}  show=${sync.state.show ? `${sync.state.show.status}${sync.state.show.beat ? `/${sync.state.show.beat}` : ""}` : "-"}\n`}
          {`controller  ${sync.state.controller ?? "-"}      last act ${sync.state.act ? `${sync.state.act.act}${sync.state.act.live ? " (live)" : " (recorded)"}` : "-"}`}
        </pre>
        {mine && sel && <Line hl>{`>> selected on the demo screen, this team: ${sel.id} ${sel.name}: ${sel.blurb}`}</Line>}
        {sel && !mine && team !== "hub" && team !== "battlefield" && <div className="dim">(the demo screen has a {sel.team} agent selected: {sel.name})</div>}
        {actions.length === 0 ? <div className="dim">nothing yet from the arena</div> : actions.map((m) => <div key={m.seq}>{msgLine(m)}</div>)}
      </Sec>

      <Sec title="API TRAFFIC (frontend proxy -> battlefield, every laptop)">
        {calls.length === 0 ? <div className="dim">no calls yet</div> : calls.slice(-14).reverse().map((t) => <div key={t.seq} className={t.status >= 400 ? "bad" : undefined}>{trafficLine(t)}</div>)}
        <div className="dim">+ {polls.length} polling GETs from the consoles themselves (hidden)</div>
      </Sec>

      {team !== "hub" && (
        <Sec title={`${team.toUpperCase()} EVENTS (raw, newest first)`}>
          {shown.length === 0 ? <div className="dim">no events for this team yet</div> : shown.map((e) => <Line key={`${e.id}-${e.type}`} hl={concerns(e, selected)}>{eventLine(e)}</Line>)}
        </Sec>
      )}

      {team === "red" && <RedState bs={bs} selected={selected} />}
      {team === "green" && <GreenState bs={bs} />}
      {team === "blue" && <BlueState bs={bs} selected={selected} />}
      {team === "battlefield" && <BattlefieldState bs={bs} />}

      {team === "hub" && (
        <Sec title="CONSOLES">
          <pre>{`one laptop per address, typed by hand (nothing links to them):\n\n${TEAM_KEYS.map((k, i) => `  ${i + 1}  ${typeof window === "undefined" ? "" : window.location.origin}/backstage/${k}`).join("\n")}\n\nkeys: 1-4 switch, A back to the arena. Each console follows the newest episode on its own.`}</pre>
        </Sec>
      )}

      {team !== "hub" && (
        <Sec title="RAW READ API (JSON as the backend returned it)">
          {Object.keys(agg).length === 0 ? <div className="dim">nothing read yet{bs.mode === "live" ? "" : " (needs a backend)"}</div> : Object.entries(agg).map(([k, v]) => (
            <details key={k} open={k === "snapshot"}>
              <summary>{k}</summary>
              <pre>{JSON.stringify(Array.isArray(v) ? v.slice(0, 4) : v, null, 1).slice(0, 2200)}</pre>
            </details>
          ))}
        </Sec>
      )}
    </div>
  );
}

// ---- per team: what the events add up to ------------------------------------------------------------------------------

type BS = ReturnType<typeof useBackstage>;

function RedState({ bs, selected }: { bs: BS; selected: string | null }) {
  const s = bs.state;
  const attacks = Object.values(s.attacks).sort((a, b) => b.day_launched - a.day_launched);
  const think = thoughts(s, "red", 3);
  const tools = toolRows(s, "red", 8);
  return (
    <Sec title="RED STATE (folded from the events)">
      <pre>{`launched ${s.score.attacks_launched}   extracted ${usd(s.score.dollars_extracted)}   caught ${s.score.attacks_caught}   detection latency ${s.score.detection_latency_days ?? "-"}d`}</pre>
      {attacks.map((a) => (
        <Line key={a.attack_id} hl={selected === `red:${a.scheme_id}`}>{`d${a.day_launched} ${schemeName(a.scheme_id).padEnd(20)} target ${usd(a.target_amount).padStart(8)}  ${a.outcome.padEnd(9)} taken ${usd(a.amount_extracted).padStart(8)}  ${a.attack_id}`}</Line>
      ))}
      {think.map((t) => <div key={t.key} className="dim">{`thinking d${t.day}: ${t.text.slice(0, 240)}`}</div>)}
      {tools.map((t) => <div key={t.id} className="dim">{`tool d${t.day} ${t.tool} ${t.ok === undefined ? "running" : t.ok ? "ok" : "failed"} ${t.summary.slice(0, 120)}`}</div>)}
    </Sec>
  );
}

function GreenState({ bs }: { bs: BS }) {
  const s = bs.state;
  const snap = bs.agg.snapshot;
  const mine = s.verdicts.filter((v) => v.agent === "green");
  const counts = verdictCounts(mine);
  const open = Object.values(s.escalations).filter((e) => e.status === "open");
  const think = thoughts(s, "green", 3);
  const tools = toolRows(s, "green", 8);
  return (
    <Sec title="GREEN STATE">
      <pre>{`AP open ${snap ? `${snap.ap?.open?.n} invoices ${usd(snap.ap?.open?.total)}` : "-"}   overdue ${snap ? `${snap.ap?.overdue?.n} ${usd(snap.ap?.overdue?.total)}` : "-"}   cash ${snap ? usd(snap.company?.cash_position) : "-"}\nprocessed ${s.score.legit_processed}   attempts gated ${counts.total}  (allow ${counts.allow}  block ${counts.block}  review ${counts.escalate})   false-positive cost ${usd(s.score.false_positive_cost)}`}</pre>
      {open.map((e) => <div key={e.escalation_id} className="warn">{`WAITING ON A HUMAN: ${e.action} ${usd(e.amount)}  ${e.reason}`}</div>)}
      {mine.slice(-10).reverse().map((v) => <div key={v.verdict_id} className={isFailSafe(v) ? "dim" : undefined}>{`d${v.day} ${v.verdict.padEnd(8)} ${v.action.padEnd(22)} ${usd(v.amount).padStart(8)}  ${isFailSafe(v) ? failSafeLabel(v.verdict) : v.rules_fired.map(ruleName).join(" + ") || v.reason}`}</div>)}
      {think.map((t) => <div key={t.key} className="dim">{`thinking d${t.day}: ${t.text.slice(0, 240)}`}</div>)}
      {tools.map((t) => <div key={t.id} className="dim">{`tool d${t.day} ${t.tool} ${t.ok === undefined ? "running" : t.ok ? "ok" : "cancelled"} ${t.summary.slice(0, 120)}`}</div>)}
    </Sec>
  );
}

function BlueState({ bs, selected }: { bs: BS; selected: string | null }) {
  const s = bs.state;
  const counts = verdictCounts(s.verdicts);
  const rules = ruleBoard(s.verdicts);
  const open = Object.values(s.escalations).filter((e) => e.status === "open");
  const cm = confusion(bs.agg.confusion);
  const lat = avgLatency(bs.agg.verdicts);
  const think = thoughts(s, "blue", 3);
  const admin = useRole() === "admin";
  return (
    <Sec title="BLUE STATE">
      <pre>{`verdicts ${counts.total}  allow ${counts.allow}  block ${counts.block}  review ${counts.escalate}   flags ${s.flags.length}   frozen ${Object.keys(s.frozenVendors).length}   gate latency ${lat == null ? "-" : `${Math.round(lat)}ms`}\nconfusion ${cm ? `true-block ${cm.trueBlock}  false-block ${cm.falseBlock}  missed ${cm.missed}  true-allow ${cm.trueAllow}` : (admin ? "- (needs /fe/verdicts/confusion)" : "- (admins only: it needs the ground truth)")}`}</pre>
      {open.map((e) => (
        <div key={e.escalation_id} className="warn">
          {`OPEN ESCALATION ${e.escalation_id}: ${e.action} ${usd(e.amount)}  ${isFailSafe(e) ? failSafeLabel("escalate") : e.reason}  `}
          {admin && <><button onClick={() => void api.resolve(e.escalation_id, "approve").catch(() => {})}>approve</button> <button onClick={() => void api.resolve(e.escalation_id, "block").catch(() => {})}>block</button></>}
        </div>
      ))}
      <div className="dim">latest verdicts, newest first, each with its reason:</div>
      {s.verdicts.length === 0 && <div className="dim">  none yet</div>}
      {s.verdicts.slice(-8).reverse().map((v) => {
        const hit = !!selected && (v.rules_fired ?? []).some((r) => (blueIdForRule(r) ?? `blue:${r}`) === selected);
        if (isFailSafe(v)) {
          // blue did not answer; the ledger's default decided. Muted, and never read as a rule's catch.
          return (
            <div key={v.verdict_id} className="dim">
              <Line hl={false}>{`d${v.day} ${FAIL_SAFE_TAG.padEnd(9)} ${v.action.padEnd(20)} ${usd(v.amount).padStart(8)}  ${failSafeLabel(v.verdict)}`}</Line>
              <Line hl={false}>{`   ${FAIL_SAFE_NOTE}`}</Line>
            </div>
          );
        }
        return (
          <div key={v.verdict_id}>
            <Line hl={hit}>{`d${v.day} ${v.verdict.toUpperCase().padEnd(8)} ${v.action.padEnd(20)} ${usd(v.amount).padStart(8)}  ${(v.rules_fired ?? []).map(ruleName).join(" + ") || "no rule fired"}`}</Line>
            <Line hl={hit}>{`   "${v.reason}"`}</Line>
          </div>
        );
      })}
      <div className="dim">rules fired:</div>
      {rules.map((r) => <Line key={r.rule} hl={!!selected && (blueIdForRule(r.rule) ?? `blue:${r.rule}`) === selected}>{`  ${ruleName(r.rule).padEnd(20)} ${r.rule.padEnd(32)} total ${String(r.total).padStart(3)}  block ${String(r.block).padStart(3)}  review ${String(r.escalate).padStart(3)}`}</Line>)}
      {s.flags.slice(-5).reverse().map((f) => <div key={f.flag_id}>{`flag d${f.day} ${f.severity} ${f.entity_type}: ${f.reason}`}</div>)}
      {think.map((t) => <div key={t.key} className="dim">{`thinking d${t.day}: ${t.text.slice(0, 240)}`}</div>)}
    </Sec>
  );
}

function BattlefieldState({ bs }: { bs: BS }) {
  const { health, episode, episodes } = bs;
  const id = episode?.id ?? "";
  const [msg, setMsg] = useState("");
  const [mode, setMode] = useState<ControllerMode>("enforce");
  const [seed, setSeed] = useState("42");
  const [days, setDays] = useState("4");
  const [planned, setPlanned] = useState(true);
  const [scheme, setScheme] = useState("ghost_vendor");
  const [schemes, setSchemes] = useState<{ id: string; display_name: string }[]>([]);
  const [replays, setReplays] = useState<string[]>([]);
  const [replay, setReplay] = useState("");
  const live = bs.mode === "live";
  const admin = useRole() === "admin";
  useEffect(() => {
    if (!live || !admin) return;
    api.schemes().then((x) => { setSchemes(x); if (x[0]) setScheme((c) => (x.some((s: any) => s.id === c) ? c : x[0].id)); }).catch(() => {});
    api.replays().then((r) => { setReplays(r); setReplay((c) => c || r[0] || ""); }).catch(() => {});
  }, [live, admin]);
  const act = async (label: string, fn: () => Promise<unknown>) => {
    try { await fn(); setMsg(`${hhmmss(Date.now())} ${label}: ok`); } catch (e) { setMsg(`${hhmmss(Date.now())} ${label}: ${String(e instanceof Error ? e.message : e).slice(0, 160)}`); }
  };
  return (
    <>
      <Sec title="SERVICES (GET /api/health)">
        {!health ? <div className="dim">no answer</div> : (
          <pre>{`postgres   ${health.db ? "connected" : "DOWN"}\n${Object.entries(health.agents as Record<string, any>).map(([k, a]) => `${k.padEnd(10)} ${a?.ok === false ? "DOWN" : "up  "}  model=${a?.model ?? "?"}  dry_run=${a?.dry_run ?? "?"}  droid_ok=${a?.droid_ok ?? "?"}`).join("\n")}`}</pre>
        )}
      </Sec>
      <Sec title="EPISODES">
        {episodes.length === 0 ? <div className="dim">none</div> : episodes.slice(0, 10).map((e) => (
          <div key={e.id}>{`${e.id.padEnd(28)} ${e.controller_mode.padEnd(8)} ${e.status.padEnd(9)} day ${Math.min(e.current_day, e.days)}/${e.days}  `}<button onClick={() => bs.pin(bs.pinned === e.id ? null : e.id)}>{bs.pinned === e.id ? "unpin" : "follow"}</button></div>
        ))}
      </Sec>
      {admin && <Sec title="CONTROL PLANE (operator calls: they go through the proxy and show up in API TRAFFIC)">
        {!live ? <div className="dim">needs a backend</div> : (
          <>
            <div>
              new episode:{" "}
              {MODES.map((m) => <label key={m}><input type="radio" name="mode" checked={mode === m} onChange={() => setMode(m)} /> {m} </label>)}
              seed <input value={seed} onChange={(e) => setSeed(e.target.value)} size={4} /> days <input value={days} onChange={(e) => setDays(e.target.value)} size={3} />{" "}<label title="pin red to schemes that show on screen each day (bank swap, split, ghost vendor, ghost employee, inflated expense, PO mismatch)"><input type="checkbox" checked={planned} onChange={(e) => setPlanned(e.target.checked)} /> demo plan</label>{" "}
              <button onClick={() => void act("POST /episodes", () => api.createEpisode({ controller_mode: mode, seed: Number(seed) || 42, days: Number(days) || 4, ...(planned ? { attack_plan: demoPlan(Number(days) || 4) } : {}) }))}>create</button>{" "}
              <button onClick={() => void act("create + start", async () => { const ep = await api.createEpisode({ controller_mode: mode, seed: Number(seed) || 42, days: Number(days) || 4, ...(planned ? { attack_plan: demoPlan(Number(days) || 4) } : {}) }); await api.start(ep.id); })}>create + start</button>
            </div>
            <div>
              this episode ({id || "none"}):{" "}
              <button disabled={!id} onClick={() => void act("start", () => api.start(id))}>start</button> <button disabled={!id} onClick={() => void act("pause", () => api.pause(id))}>pause</button> <button disabled={!id} onClick={() => void act("resume", () => api.resume(id))}>resume</button> <button disabled={!id} onClick={() => void act("step", () => api.step(id))}>step a day</button>{" "}
              controller: {MODES.map((m) => <button key={m} disabled={!id} onClick={() => void act(`controller ${m}`, () => api.setController(id, m))}>{m}</button>)}
            </div>
            <div>
              force attack:{" "}
              <select value={scheme} onChange={(e) => setScheme(e.target.value)}>{(schemes.length ? schemes : [{ id: "ghost_vendor", display_name: "ghost_vendor" }]).map((s) => <option key={s.id} value={s.id}>{s.id}</option>)}</select>{" "}
              <button disabled={!id} onClick={() => void act(`attack ${scheme}`, () => api.forceAttack(id, scheme))}>queue for the next red turn</button>{" "}
              replay: <select value={replay} onChange={(e) => setReplay(e.target.value)}>{replays.length === 0 && <option value="">none</option>}{replays.map((r) => <option key={r} value={r}>{r}</option>)}</select>{" "}
              <button disabled={!replay} onClick={() => void act(`replay ${replay}`, () => api.playReplay(replay, 4))}>play 4x</button>
            </div>
            <div className="dim">{msg || "-"}</div>
          </>
        )}
      </Sec>}
    </>
  );
}
