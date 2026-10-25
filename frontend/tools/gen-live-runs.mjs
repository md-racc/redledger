// Summarise the live-red recordings (docs/recordings, #136) into public/mocks/live-runs.json for the Compare card's "Real run" tab.
//   node tools/gen-live-runs.mjs
// Numbers only (final score, cumulative stolen/blocked per day, the attacks red launched): no agent text, no tool-call ids. Owner: Dev R.
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const rec = join(here, "../../docs/recordings");
const out = join(here, "../public/mocks/live-runs.json");

function summarize(file) {
  const ev = readFileSync(join(rec, file), "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l));
  const started = ev.find((e) => e.type === "episode.started");
  const ended = ev.find((e) => e.type === "episode.ended");
  const byDay = new Map();
  for (const e of ev) if (e.type === "score.updated") byDay.set(e.day, { day: e.day, extracted: e.payload.dollars_extracted, blocked: e.payload.dollars_blocked });
  const credits = ev.filter((e) => e.type === "turn.ended" && e.payload.agent === "red").reduce((s, e) => s + (e.payload.factory_credits ?? 0), 0);
  return {
    episode_id: started.episode_id,
    mode: started.payload.controller_mode,
    seed: started.payload.seed,
    days: started.payload.days,
    score: ended.payload.final_score,
    by_day: [...byDay.values()].sort((a, b) => a.day - b.day),
    attacks: ev.filter((e) => e.type === "attack.launched").map((e) => ({ day: e.day, scheme_id: e.payload.scheme_id, display_name: e.payload.display_name, target_amount: e.payload.target_amount })),
    escalations: { opened: ev.filter((e) => e.type === "escalation.opened").length, timed_out: ev.filter((e) => e.type === "escalation.resolved" && e.payload.decision === "timeout").length },
    red_credits: Math.round(credits),
  };
}

const doc = {
  recorded: "2026-10-24",
  where: "our production server",
  note: "Red was live on Factory's Droid SDK (gpt-5.4-mini). Green and blue ran keyless.",
  source: "docs/recordings (#136)",
  runs: { off: summarize("demo-off-live.jsonl"), enforce: summarize("demo-enforce-live.jsonl") },
};
writeFileSync(out, `${JSON.stringify(doc, null, 1)}\n`);
console.log(`wrote ${out}: off $${doc.runs.off.score.dollars_extracted}, enforce $${doc.runs.enforce.score.dollars_extracted}`);
