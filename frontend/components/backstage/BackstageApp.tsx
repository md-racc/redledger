"use client";
import { useCallback, useEffect, useState } from "react";
import { RawConsole } from "./RawConsole";
import type { TeamKey } from "./raw";
import { TeamDashboard } from "./dash/TeamDashboard";

/**
 * One backstage page. Kept as its own client module so the (server) route files stay thin.
 * Red and blue get the technical dashboard; `?raw=1` (or `R`) shows the raw console instead, the evidence view. Green, battlefield and
 * the hub stay raw.
 */
export function BackstageApp({ team }: { team: TeamKey | "hub" }) {
  const dash = team === "red" || team === "blue";
  // read after mount: the route is static, and the query string only exists in the browser
  const [raw, setRaw] = useState<boolean | null>(null);
  useEffect(() => {
    try { setRaw(new URLSearchParams(window.location.search).get("raw") === "1"); } catch { setRaw(false); }
  }, []);

  const toggle = useCallback(() => {
    setRaw((r) => {
      const next = !r;
      try {
        const u = new URL(window.location.href);
        if (next) u.searchParams.set("raw", "1"); else u.searchParams.delete("raw");
        window.history.replaceState(window.history.state, "", u);
      } catch { /* the view still switches */ }
      return next;
    });
  }, []);

  useEffect(() => {
    if (!dash) return;
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "r" || e.key === "R") toggle();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [dash, toggle]);

  if (!dash) return <RawConsole team={team} />;
  if (raw === null) return <div className="bd-dash" />;
  if (raw) {
    return (
      <>
        <button className="bd-raw-back" onClick={toggle} title="back to the dashboard (key R)">dashboard (R)</button>
        <RawConsole team={team} />
      </>
    );
  }
  return <TeamDashboard team={team} onRaw={toggle} />;
}
