"use client";
// Loads the controls assessment for one run and shows it, or the state it is in. Owner: Dev Ad (crunch).
//   NEXT_PUBLIC_MOCK=true  the recorded demo (public/mocks/controls-report.json), whatever the run id
//   viewer, run going      the proxy answers 403 "available when the run ends": say so, and look again every 20 s
//   admin, run going       the draft, refreshed every 30 s
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { companyName } from "@/lib/company";
import { MOCK_MODELS, agentModels, isNotFinalAnswer, reportFilename } from "@/lib/report/summary";
import type { AgentModel, ControlsReport } from "@/lib/report/types";
import { ReportDocument } from "./ReportDocument";

const MOCK = process.env.NEXT_PUBLIC_MOCK === "true";
const PENDING_RETRY_MS = 20_000;
const DRAFT_REFRESH_MS = 30_000;

type State =
  | { kind: "loading" }
  | { kind: "ready"; report: ControlsReport; models: AgentModel[]; company: string }
  | { kind: "pending" }
  | { kind: "missing" }
  | { kind: "error"; message: string };

export function ReportView({ ep }: { ep: string }) {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    const ctl = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const again = (ms: number) => {
      timer = setTimeout(() => void load(), ms);
    };
    async function load() {
      try {
        if (MOCK) {
          const res = await fetch("/mocks/controls-report.json", { signal: ctl.signal });
          if (!res.ok) throw new Error(`mock fixture: ${res.status}`);
          setState({ kind: "ready", report: (await res.json()) as ControlsReport, models: MOCK_MODELS, company: companyName() });
          return;
        }
        // the run's snapshot names the company (battlefield seed/company.py); without it the report falls back to lib/company
        const [report, health, snap] = await Promise.all([
          api.fe.controls(ep, ctl.signal),
          api.health(ctl.signal).catch(() => null),
          api.fe.snapshot(ep).catch(() => null),
        ]);
        setState({ kind: "ready", report, models: agentModels(health), company: companyName(snap) });
        if (!report.final) again(DRAFT_REFRESH_MS);
      } catch (err) {
        if (ctl.signal.aborted) return;
        if (err instanceof ApiError && isNotFinalAnswer(err.status, err.body)) {
          setState({ kind: "pending" });
          again(PENDING_RETRY_MS);
        } else if (err instanceof ApiError && err.status === 404) {
          setState({ kind: "missing" });
        } else {
          setState({ kind: "error", message: err instanceof ApiError ? `battlefield answered ${err.status}` : "the report could not be loaded" });
        }
      }
    }
    void load();
    return () => {
      ctl.abort();
      if (timer) clearTimeout(timer);
    };
  }, [ep]);

  const download = useCallback(() => {
    if (state.kind !== "ready") return;
    const blob = new Blob([JSON.stringify(state.report, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = reportFilename(state.report);
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }, [state]);

  return (
    <main className="rr">
      <nav className="rr-toolbar rr-noprint" aria-label="Report actions">
        <Link href="/" className="rr-back">
          ← Back to the arena
        </Link>
        <span className="rr-toolbar-title">
          Controls assessment{MOCK ? " (mock data: the recorded demo run)" : ""}
        </span>
        <span className="rr-actions">
          <button type="button" onClick={download} disabled={state.kind !== "ready"}>
            Download JSON
          </button>
          <button type="button" onClick={() => window.print()} disabled={state.kind !== "ready"}>
            Print / Save PDF
          </button>
        </span>
      </nav>
      {state.kind === "ready" && <ReportDocument report={state.report} models={state.models} company={state.company} />}
      {state.kind === "loading" && <Notice title="Loading the assessment…" />}
      {state.kind === "pending" && (
        <Notice title="Available when the run ends">
          The controls assessment for run <code>{ep}</code> is published once the run has finished: until then it would reveal which items are the
          attacker&apos;s while the agents are still working. This page checks again every 20 seconds.
        </Notice>
      )}
      {state.kind === "missing" && (
        <Notice title="No such run">
          There is no run <code>{ep}</code> on this stack.
        </Notice>
      )}
      {state.kind === "error" && <Notice title="The assessment could not be loaded">Try again in a moment ({state.message}).</Notice>}
    </main>
  );
}

function Notice({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <article className="rr-paper rr-notice" role="status">
      <p className="rr-kicker">Red Ledger · Controls Assessment</p>
      <h1>{title}</h1>
      {children && <p>{children}</p>}
    </article>
  );
}
