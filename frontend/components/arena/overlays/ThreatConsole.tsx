"use client";
// "Launch an attack": the judge picks a fraud scheme and the arena plays it. On a live backend this is
// POST /episodes/{id}/attack (red runs it on its next turn); offline it is simulated from the mock agents' rules. Owner: Dev R.
import { useState } from "react";
import { SCHEME_PROFILE } from "@/lib/arena/localAttack";
import { money } from "@/lib/arena/headlines";
import { BLUE_RULES, RED_SCHEMES } from "@/lib/arena/roster";
import type { ControllerMode } from "@/lib/types";

const HINT: Record<ControllerMode, string> = {
  off: "No controller: it will get away.",
  shadow: "Shadow mode: the gate will flag it but not stop it.",
  enforce: "Enforce mode: watch the guards.",
};

export function ThreatConsole({ open, mode, onClose, onLaunch }: { open: boolean; mode: ControllerMode; onClose: () => void; onLaunch: (scheme: string) => Promise<void> }) {
  const [last, setLast] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const ruleName = (k: string) => BLUE_RULES.find((r) => r.key === k)?.name ?? k;

  return (
    <section className={`threat ${open ? "is-open" : ""}`} aria-label="Launch an attack" aria-hidden={!open}>
      <header>
        <div>
          <h3>Launch an attack</h3>
          <p>{HINT[mode]}</p>
        </div>
        <button className="icon-btn" onClick={onClose} aria-label="Close">✕</button>
      </header>
      <ul>
        {RED_SCHEMES.map((s) => {
          const prof = SCHEME_PROFILE[s.key];
          return (
            <li key={s.key}>
              <button
                className={last === s.key ? "on" : ""}
                tabIndex={open ? 0 : -1}
                onClick={() => { setErr(null); setLast(s.key); onLaunch(s.key).catch((e: unknown) => setErr(String(e instanceof Error ? e.message : e).slice(0, 120))); }}
                title={s.blurb}
              >
                <b>{s.name}</b>
                <span>{prof ? `${money(s.key === "threshold_split" ? 14400 : prof.amount)} · stopped by ${ruleName(prof.rules[0])}` : s.blurb}</span>
              </button>
            </li>
          );
        })}
      </ul>
      {err && <p className="threat-err">{err}</p>}
    </section>
  );
}
