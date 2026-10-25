"use client";
// Skeleton page proving the data path: state from the reducer, fed by WS or fixture. Owner: Dev R.
// Everything visual is yours to replace. The data wiring below is the part worth keeping.
// On load it joins the run that is going (lib/arena/useActiveRun.ts: a running episode, or a running lineage's current generation),
// waits for one when nothing runs, and follows a lineage to its next generation. Only admins see the buttons that change the sim.
import { useEffect, useReducer, useState } from "react";
import { api } from "@/lib/api";
import { parseActiveRun } from "@/lib/arena/activeRun";
import { useActiveRun } from "@/lib/arena/useActiveRun";
import { loadFixture, replay } from "@/lib/mock";
import { attacksByDay, blockedVerdicts, initialState, openEscalations, reduce } from "@/lib/reducer";
import { useRole } from "@/lib/role";
import type { RLEvent, UIState } from "@/lib/types";
import { connect } from "@/lib/ws";

const MOCK = process.env.NEXT_PUBLIC_MOCK === "true";

type Action = RLEvent | { type: "__reset" };
const wrapped = (s: UIState, a: Action): UIState => (a.type === "__reset" ? initialState() : reduce(s, a as RLEvent));

export default function Page() {
  const [state, dispatch] = useReducer(wrapped, undefined, initialState);
  const [episodeId, setEpisodeId] = useState<string | null>(null);
  const admin = useRole() === "admin";
  const active = useActiveRun({ enabled: !MOCK });

  // the run on stage is the one to show; when it ends it stays on screen until the next one starts
  useEffect(() => { if (active.run) setEpisodeId(active.run.episodeId); }, [active.run]);

  useEffect(() => {
    if (MOCK) {
      let cancel = () => {};
      loadFixture().then((evs) => { cancel = replay(evs, dispatch); });
      return () => cancel();
    }
    if (!episodeId) return;
    dispatch({ type: "__reset" });
    return connect(episodeId, dispatch);
  }, [episodeId]);

  async function newEpisode(mode: "off" | "shadow" | "enforce") {
    const ep = await api.createEpisode({ controller_mode: mode, seed: 42, days: 5 });
    try {
      await api.start(ep.id);
      setEpisodeId(ep.id);
    } catch (e) {
      // another run is active: show that one instead
      const found = parseActiveRun(e);
      if (!found) throw e;
      if (found.episodeId) setEpisodeId(found.episodeId);
    } finally {
      active.refresh();
    }
  }

  const esc = openEscalations(state);
  return (
    <main className="p-6 space-y-6 font-mono text-sm">
      <header className="flex items-center gap-4">
        <h1 className="text-xl font-bold">Red Ledger</h1>
        <span>episode: {state.episodeId ?? "—"}</span>
        <span>day {state.currentDay}/{state.days}</span>
        <span>controller: {state.controllerMode}</span>
        {!MOCK && admin && (
          <>
            <button className="border px-2" onClick={() => newEpisode("off")}>new (off)</button>
            <button className="border px-2" onClick={() => newEpisode("enforce")}>new (enforce)</button>
            {state.episodeId && <button className="border px-2" onClick={() => api.setController(state.episodeId!, state.controllerMode === "enforce" ? "shadow" : "enforce")}>toggle</button>}
          </>
        )}
      </header>

      <section className="grid grid-cols-4 gap-4">
        <Stat label="stolen" value={`$${state.score.dollars_extracted.toLocaleString()}`} />
        <Stat label="blocked" value={`$${state.score.dollars_blocked.toLocaleString()}`} />
        <Stat label="false-positive cost" value={`$${state.score.false_positive_cost.toLocaleString()}`} />
        <Stat label="attacks caught" value={`${state.score.attacks_caught}/${state.score.attacks_launched}`} />
      </section>

      {esc.length > 0 && (
        <section className="border p-3">
          <h2 className="font-bold">Needs a human</h2>
          {esc.map((e) => (
            <div key={e.escalation_id} className="flex gap-3 items-center">
              <span>{e.action} ${e.amount?.toLocaleString()} — {e.reason}</span>
              {admin && <button className="border px-2" onClick={() => api.resolve(e.escalation_id, "approve")}>approve</button>}
              {admin && <button className="border px-2" onClick={() => api.resolve(e.escalation_id, "block")}>block</button>}
            </div>
          ))}
        </section>
      )}

      <section className="grid grid-cols-2 gap-6">
        <div>
          <h2 className="font-bold">Attacks</h2>
          {attacksByDay(state).map((a) => (
            <div key={a.attack_id} className="border-b py-1">
              d{a.day_launched} {a.display_name} ${a.target_amount.toLocaleString()} → <b>{a.outcome}</b>
              <div className="opacity-70">{a.story}</div>
            </div>
          ))}
        </div>
        <div>
          <h2 className="font-bold">Verdicts</h2>
          {blockedVerdicts(state).slice(-12).reverse().map((v) => (
            <div key={v.verdict_id} className="border-b py-1">
              d{v.day} <b>{v.verdict.toUpperCase()}</b> {v.action} {v.amount ? `$${v.amount.toLocaleString()}` : ""}
              <div className="opacity-70">{v.reason}</div>
            </div>
          ))}
        </div>
      </section>

      <section>
        <h2 className="font-bold">Agent thinking (current day)</h2>
        {(["red", "green", "blue"] as const).map((a) => (
          <pre key={a} className="whitespace-pre-wrap border p-2 my-1 max-h-40 overflow-auto"><b>{a}</b>: {state.thinking[`${a}:${state.currentDay}`] ?? ""}</pre>
        ))}
      </section>
    </main>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="border p-3">
      <div className="opacity-60">{label}</div>
      <div className="text-2xl">{value}</div>
    </div>
  );
}
