"use client";
// "Launch an attack": the judge picks a fraud scheme and the arena plays it. On a live backend this is
// POST /episodes/{id}/attack (red runs it on its next turn); offline it is simulated from the mock agents' rules. Owner: Dev R.
import { useEffect, useState } from "react";
import { SCHEME_PROFILE } from "@/lib/arena/localAttack";
import { money } from "@/lib/arena/headlines";
import { BLUE_RULES, RED_SCHEMES } from "@/lib/arena/roster";
import type { Spoken } from "@/lib/arena/useFeed";
import { EXAMPLES } from "@/lib/voice/examples";
import { BUILT_IN_SCHEMES, closestScheme, type BuiltInScheme } from "@/lib/voice/intent";
import { useRole } from "@/lib/role";
import type { ControllerMode } from "@/lib/types";
import { languageName, useVoice } from "../useVoice";

const HINT: Record<ControllerMode, string> = {
  off: "No controller: it will get away.",
  shadow: "Shadow mode: the gate will flag it but not stop it.",
  enforce: "Enforce mode: watch the guards.",
};

const schemeName = (k: string) => RED_SCHEMES.find((s) => s.key === k)?.name ?? k;
const clock = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

export function ThreatConsole({ open, mode, onClose, onLaunch }: { open: boolean; mode: ControllerMode; onClose: () => void; onLaunch: (scheme: string, spoken?: Spoken) => Promise<void> }) {
  const [last, setLast] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const ruleName = (k: string) => BLUE_RULES.find((r) => r.key === k)?.name ?? k;

  // "say it in your own words": speak or type any fraud scheme, in any language
  const voice = useVoice();
  // the microphone spends the owner's speech credits, so it is for the admin laptops only (the route refuses a viewer too; lib/admin.ts)
  const admin = useRole() === "admin";
  const guess = closestScheme(voice.text);
  const [pick, setPick] = useState<BuiltInScheme | null>(null);
  const scheme = pick ?? guess.scheme;
  const [sent, setSent] = useState(false);
  useEffect(() => { setPick(null); setSent(false); }, [voice.text]);
  useEffect(() => { if (!open && voice.phase === "listening") voice.reset(); }, [open, voice]);
  const busy = voice.phase === "listening" || voice.phase === "transcribing";
  const launchSpoken = () => {
    if (!admin || busy || sent || !voice.text.trim()) return;
    setErr(null);
    setSent(true);
    onLaunch(scheme, { text: voice.text, language: voice.language }).catch((e: unknown) => { setSent(false); setErr(String(e instanceof Error ? e.message : e).slice(0, 120)); });
  };

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
      <div className="speak">
        <h4>Or say it in your own words, in any language</h4>
        <div className="speak-row">
          <button
            className={`btn ${voice.phase === "listening" ? "armed" : ""}`}
            tabIndex={open ? 0 : -1}
            disabled={!admin || voice.phase === "transcribing"}
            onClick={() => (voice.phase === "listening" ? void voice.stop() : void voice.start())}
          >
            {voice.phase === "listening" ? <><i className="dot" />Stop · {clock(voice.seconds)}</> : voice.phase === "transcribing" ? "Listening to what you said…" : "Speak a scheme"}
          </button>
          {voice.phase === "listening" && <span className="speak-level" aria-hidden><i style={{ width: `${Math.min(100, voice.level * 160)}%` }} /></span>}
          {voice.phase === "listening" && <span className="speak-lang">Speak, then pause. It stops by itself.</span>}
          {voice.language && voice.phase === "ready" && <span className="speak-lang">Heard: {languageName(voice.language)}{voice.probability != null ? ` · ${Math.round(voice.probability * 100)}%` : ""}</span>}
        </div>
        {!admin && <p className="speak-note">Only the admin laptops can speak or launch a scheme.</p>}
        {admin && voice.configured === false && <p className="speak-note">Voice is not set up on this server, so type the scheme instead.</p>}
        {voice.error && <p className="threat-err">{voice.error}</p>}
        <textarea
          className="speak-text"
          rows={2}
          value={voice.text}
          tabIndex={open ? 0 : -1}
          disabled={busy}
          maxLength={500}
          placeholder="Describe a fraud: “change a vendor's bank details right before a big payment”… in any language"
          onChange={(e) => voice.type(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); launchSpoken(); } }}
          aria-label="Describe a fraud scheme"
        />
        {!voice.text.trim() && !busy && (
          <p className="speak-try">
            Try:{" "}
            {EXAMPLES.map((x) => (
              <button key={x.label} type="button" tabIndex={open ? 0 : -1} title={x.text} onClick={() => voice.type(x.text)}>{x.label}</button>
            ))}
          </p>
        )}
        {voice.text.trim() && (
          <p className="speak-match">
            Red reads your exact words to set the amount and details. The scheme that runs is the closest of its eight:{" "}
            <select value={scheme} onChange={(e) => setPick(e.target.value as BuiltInScheme)} tabIndex={open ? 0 : -1} aria-label="Closest built-in scheme">
              {BUILT_IN_SCHEMES.map((k) => <option key={k} value={k}>{schemeName(k)}</option>)}
            </select>
            {!guess.confident && !pick && " (no clear match: pick one)"}
          </p>
        )}
        {voice.text.trim() && (
          <div className="speak-act">
            <button className="btn primary" tabIndex={open ? 0 : -1} disabled={!admin || busy || sent} onClick={launchSpoken}>{sent ? "Launched" : "Launch it"}</button>
            <button className="btn ghost" tabIndex={open ? 0 : -1} disabled={busy} onClick={voice.reset}>Clear</button>
          </div>
        )}
      </div>
      {err && <p className="threat-err">{err}</p>}
    </section>
  );
}
