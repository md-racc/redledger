"use client";
// The "redledger" lockup over the intro flight: a condensed display face split to both edges of the frame with the
// Palace between the halves, letters rising out of a mask, then sliding off as the visitor starts to scroll.
import { useEffect, useRef } from "react";
import { useArena } from "@/lib/arena/store";
import { subscribeTimeline, timeline } from "@/lib/arena/timeline";

const Letters = ({ text, base }: { text: string; base: number }) => (
  <>
    {[...text].map((c, i) => (
      <span className="ch" key={i} style={{ ["--d" as string]: `${base + i * 0.07}s` }}>{c}</span>
    ))}
  </>
);

export function TitleOverlay() {
  const stage = useArena((s) => s.stage);
  const skip = useArena((s) => s.setSkipIntro);
  const root = useRef<HTMLElement>(null);
  const redWord = useRef<HTMLSpanElement>(null);
  const ledgerWord = useRef<HTMLSpanElement>(null);

  // "red" is shorter than "ledger", so the gap between them is left of the screen centre. Publish where it is so the camera
  // can land the Palace exactly in it.
  useEffect(() => {
    const measure = () => {
      const r = redWord.current, l = ledgerWord.current;
      if (!r || !l) return;
      timeline.gapX = window.innerWidth <= 760 ? 0.5 : (r.offsetLeft + r.offsetWidth + l.offsetLeft) / 2 / window.innerWidth;
    };
    measure();
    void document.fonts?.ready.then(measure);
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);

  useEffect(
    () =>
      subscribeTimeline((t) => {
        const el = root.current;
        if (!el) return;
        // exits over the first slice of scroll; the hint pill arrives near the end of the flight
        const exit = Math.min(1, t.scroll / 0.1);
        el.style.setProperty("--exit", exit.toFixed(3));
        el.style.setProperty("--hint", String(Math.min(1, Math.max(0, (t.intro - 0.78) / 0.18)) * (1 - exit)));
      }),
    [],
  );

  const playing = stage !== "loading";
  return (
    <section ref={root} className={`title ${playing ? "is-playing" : ""} ${stage === "arena" ? "is-gone" : ""}`} aria-label="redledger">
      <h1 className="title-word" aria-label="redledger">
        <span className="word word-red" aria-hidden ref={redWord}><Letters text="red" base={0.5} /></span>
        <span className="word word-ledger" aria-hidden ref={ledgerWord}><Letters text="ledger" base={0.85} /></span>
      </h1>
      <p className="title-kicker">Adversarial sandbox for autonomous finance</p>
      <p className="title-serif">Three agents. One ledger.<br />A rotunda to fight over.</p>
      <button
        className="pill"
        onClick={() => {
          if (stage === "intro") skip(true);
          else window.scrollTo({ top: window.innerHeight * 1.4, behavior: "smooth" });
        }}
      >
        <span>{stage === "intro" ? "Skip intro" : "Discover"}</span>
        <i className="pill-dot" aria-hidden>↓</i>
      </button>
    </section>
  );
}
