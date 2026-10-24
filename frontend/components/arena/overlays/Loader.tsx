"use client";
import { useEffect, useState } from "react";
import { useArena } from "@/lib/arena/store";

/** Black title card with a progress hairline while the Palace streams in. */
export function Loader({ progress }: { progress: number }) {
  const stage = useArena((s) => s.stage);
  const model = useArena((s) => s.modelState);
  // three reports progress per file; blend with an easing clock so the bar never sits at zero while the glb decodes
  const [t, setT] = useState(0);
  useEffect(() => {
    if (stage !== "loading") return;
    const i = setInterval(() => setT((x) => x + 0.25), 250);
    return () => clearInterval(i);
  }, [stage]);
  const ease = 92 * (1 - Math.exp(-t / 7));
  const pct = stage === "loading" ? Math.round(Math.min(99, Math.max(progress, ease))) : 100;
  return (
    <div className={`loader ${stage === "loading" ? "" : "is-done"}`} aria-hidden={stage !== "loading"} role="status">
      <div className="loader-mark">
        <span className="loader-red">red</span>
        <span className="loader-ledger">ledger</span>
      </div>
      <div className="loader-bar"><i style={{ transform: `scaleX(${pct / 100})` }} /></div>
      <div className="loader-line">
        <span>{model === "fallback" ? "Palace model unavailable, building a stand-in" : "Loading the Palace of Fine Arts"}</span>
        <span>{String(pct).padStart(3, "0")}</span>
      </div>
    </div>
  );
}
