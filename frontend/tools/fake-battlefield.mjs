// A stand-in for battlefield, for frontend work without Docker or Postgres. Owner: Dev R.
//
//   node tools/fake-battlefield.mjs            listens on :8000 (BF_PORT), operator token "change-me-operator" (OPERATOR_TOKEN)
//   node tools/dev-live.mjs                    the same, plus `next dev` already pointed at it
//
// It speaks the documented contract (contracts/ledger-api.yaml, contracts/events.md, frontend/FRONTEND-API.md): episodes
// you create, start, step and toggle; judge-picked attacks; escalations that hold the day until a human decides; ws
// tickets and the /api/ws event stream with after_id catch-up; lineages. The events are the recorded episode
// (public/mocks/sample.jsonl) re-run per day according to the controller mode, the way the mock agents behave, so what it
// serves is realistic but it is NOT the real gate. Use the real stack (`make mock-agents`) whenever you can.
import { createHash, randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { createServer } from "node:http";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.BF_PORT ?? 8000);
const TOKEN = process.env.OPERATOR_TOKEN ?? "change-me-operator";
const DAY_PAUSE_MS = Number(process.env.DAY_PAUSE_MS ?? 2500);
const ESC_TIMEOUT_MS = Number(process.env.ESCALATION_TIMEOUT_MS ?? 90_000);
const LATENCY = Number(process.env.AGENT_LATENCY_MS ?? 120); // per simulated agent turn

const fixture = readFileSync(join(here, "../public/mocks/sample.jsonl"), "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l));
const lineageReport = JSON.parse(readFileSync(join(here, "../public/mocks/lineage-report.json"), "utf8"));
const controlsReport = JSON.parse(readFileSync(join(here, "../public/mocks/controls-report.json"), "utf8")); // the recorded demo's numbers, whatever ran here
const FIX_DAYS = 4;

const SCHEMES = [
  { id: "ghost_vendor", display_name: "Ghost Vendor", story: "A brand-new vendor appears and immediately invoices for services never delivered." },
  { id: "duplicate_invoice", display_name: "Duplicate Invoice", story: "A paid invoice is resubmitted with a new number and the amount off by a few cents." },
  { id: "bank_swap", display_name: "Bank Account Swap", story: "A real vendor's bank details are 'updated' right before a large invoice is paid." },
  { id: "threshold_split", display_name: "Threshold Splitting", story: "One large job is billed as several invoices just under the auto-approval line." },
];
const PROFILE = {
  ghost_vendor: { amount: 4920, action: "invoices.approve", rules: ["vendor_age_lt_7d", "near_threshold"] },
  duplicate_invoice: { amount: 4004.24, action: "invoices.approve", rules: ["duplicate_amount_match"] },
  bank_swap: { amount: 8400, action: "vendor_changes.approve", rules: ["bank_change_requested", "bank_change_with_open_invoices"] },
  threshold_split: { amount: 4800, action: "invoices.approve", rules: ["near_threshold"], review: true },
};

// ---- state ---------------------------------------------------------------------------------------------------------

let nextEventId = 1000;
const inputs = []; // POST /api/inputs: messages left for an agent's next turn (the stand-in only keeps them; no agent reads them)
const episodes = new Map();
const escalations = new Map();
const tickets = new Map();
const sockets = new Set(); // { socket, episode, after }

const ts = () => new Date().toISOString();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const zero = () => ({ dollars_extracted: 0, dollars_blocked: 0, false_positive_cost: 0, detection_latency_days: null, attacks_launched: 0, attacks_caught: 0, legit_blocked: 0, legit_processed: 0 });

function emit(ep, type, day, agent, payload) {
  const e = { id: ++nextEventId, ts: ts(), episode_id: ep.id, day, type, agent, payload };
  ep.events.push(e);
  for (const s of sockets) if (s.episode === ep.id || s.episode === "*") send(s.socket, e);
  return e;
}

// ---- one business day ----------------------------------------------------------------------------------------------

function recordedDay(day) {
  const d = day % FIX_DAYS;
  const cycle = Math.floor(day / FIX_DAYS);
  const keep = new Set(["attack.launched", "gate.verdict", "flag.raised", "vendor.frozen", "report.posted", "attack.outcome", "ledger.mutation"]);
  const out = fixture.filter((e) => e.day === d && keep.has(e.type));
  // attack outcomes can land a day later than their launch: pull in the ones that belong to this day's launch
  const launched = new Set(out.filter((e) => e.type === "attack.launched").map((e) => e.payload.attack_id));
  const later = fixture.filter((e) => e.type === "attack.outcome" && e.day === d + 1 && launched.has(e.payload.attack_id));
  const dayStart = fixture.find((e) => e.type === "day.started" && e.day === d)?.payload ?? { day: d, legit_injected: {} };
  const rename = (e) => (cycle ? JSON.parse(JSON.stringify(e).replace(/(atk_[a-z0-9]+|vrd_[a-z0-9]+)/g, `$1_c${cycle}`)) : structuredClone(e));
  const mine = [...out.filter((e) => e.type !== "attack.outcome"), ...out.filter((e) => e.type === "attack.outcome" && launched.has(e.payload.attack_id)), ...later];
  return { dayStart, events: mine.map(rename) };
}

function forcedDay(ep, scheme, day) {
  const def = SCHEMES.find((s) => s.id === scheme) ?? SCHEMES[0];
  const p = PROFILE[def.id] ?? PROFILE.ghost_vendor;
  const total = def.id === "threshold_split" ? 14400 : p.amount;
  const attackId = `atk_forced_${ep.id.slice(-4)}_${day}`;
  const verdictId = `vrd_forced_${ep.id.slice(-4)}_${day}`;
  const mk = (type, payload, agent = "battlefield") => ({ type, agent, day, payload });
  const events = [mk("attack.launched", { attack_id: attackId, scheme_id: def.id, display_name: def.display_name, story: def.story, target_amount: total })];
  if (ep.controller_mode !== "off") {
    const verdict = p.review && ep.controller_mode === "enforce" ? "escalate" : "block";
    events.push(mk("gate.verdict", { verdict_id: verdictId, agent: "green", action: p.action, entity_type: "invoice", entity_id: attackId, amount: p.amount, verdict, reason: `${verdict === "escalate" ? "Needs human review" : "Blocked"}: ${p.rules.join(", ")}.`, confidence: 0.9, rules_fired: p.rules, enforced: ep.controller_mode === "enforce" }, "blue"));
  }
  events.push(mk("attack.outcome", { attack_id: attackId, scheme_id: def.id, outcome: "blocked", amount_extracted: 0, detected_day: day }));
  return { dayStart: { day, legit_injected: { invoices: 6, purchase_orders: 3, expenses: 2, bank_lines: 2 } }, events };
}

async function runDay(ep) {
  const day = ep.current_day;
  const forced = ep.forced;
  ep.forced = null;
  const { dayStart, events } = forced ? forcedDay(ep, forced, day) : recordedDay(day);
  emit(ep, "day.started", day, "battlefield", dayStart);
  const turn = async (agent, work) => {
    emit(ep, "turn.started", day, "battlefield", { agent });
    await sleep(LATENCY);
    await work?.();
    emit(ep, "turn.ended", day, "battlefield", { agent, ok: true, summary: `[fake] ${agent} turn`, duration_sec: LATENCY / 1000 });
  };
  const targets = new Map();
  const outcomes = [];
  let escalatedOnce = false;

  await turn("red", async () => {
    for (const e of events.filter((x) => x.type === "attack.launched")) {
      emit(ep, "agent.thinking", day, "red", { text: `Day ${day}. Reviewing the books for an opening. Going with: ${e.payload.display_name}.` });
      emit(ep, e.type, day, e.agent, e.payload);
      ep.score.attacks_launched += 1;
      targets.set(e.payload.attack_id, e.payload.target_amount);
    }
  });

  await turn("green", async () => {
    for (const e of events.filter((x) => x.type === "gate.verdict" || x.type === "ledger.mutation")) {
      if (e.type === "ledger.mutation") { emit(ep, e.type, day, e.agent, e.payload); continue; }
      if (ep.controller_mode === "off") continue; // the gate is never consulted
      const p = { ...e.payload, enforced: ep.controller_mode === "enforce" };
      const review = !escalatedOnce && ep.controller_mode === "enforce" && p.verdict === "block" && (p.rules_fired ?? []).includes("near_threshold") && p.amount > 0 && day >= 2;
      if (review) {
        escalatedOnce = true;
        p.verdict = "escalate";
        p.reason = `Needs human review: ${(p.rules_fired ?? []).join(", ")}.`;
        emit(ep, "gate.verdict", day, "blue", p);
        const decision = await holdEscalation(ep, day, p);
        if (decision === "approve") { ep.approved.add(p.entity_id ?? "x"); ep.approvedAmount += p.amount; }
      } else {
        emit(ep, "gate.verdict", day, "blue", p);
      }
    }
  });

  await turn("blue", async () => {
    if (ep.controller_mode === "off") return;
    for (const e of events.filter((x) => x.type === "flag.raised" || x.type === "vendor.frozen" || x.type === "report.posted")) emit(ep, e.type, day, e.agent, e.payload);
  });

  for (const e of events.filter((x) => x.type === "attack.outcome")) {
    const target = targets.get(e.payload.attack_id) ?? 0;
    let payload = { ...e.payload };
    if (ep.controller_mode !== "enforce") payload = { ...payload, outcome: "extracted", amount_extracted: target, detected_day: null };
    else if (ep.approvedAmount > 0 && ep.approvedFor !== e.payload.attack_id && ep.approved.size) { payload = { ...payload, outcome: "partial", amount_extracted: ep.approvedAmount, detected_day: day }; ep.approvedFor = e.payload.attack_id; }
    outcomes.push({ e, payload, target });
    emit(ep, "attack.outcome", day, "battlefield", payload);
    if (payload.outcome === "extracted" || payload.outcome === "partial") ep.score.dollars_extracted += payload.amount_extracted;
    if (ep.controller_mode === "enforce") { ep.score.dollars_blocked += target - (payload.amount_extracted ?? 0); if (payload.outcome !== "extracted") ep.score.attacks_caught += 1; }
  }
  ep.score.legit_processed += 130 + day * 3;
  emit(ep, "score.updated", day, "battlefield", { ...ep.score });
  emit(ep, "day.ended", day, "battlefield", { day });
  ep.current_day = day + 1;
  if (ep.current_day >= ep.days) {
    ep.status = "finished";
    emit(ep, "episode.ended", ep.current_day, "battlefield", { final_score: { ...ep.score } });
  }
  return { day, score: { ...ep.score } };
}

/** Open an escalation and hold until a human decides (or it times out into a block). */
function holdEscalation(ep, day, verdict) {
  const id = `esc_${randomUUID().slice(0, 8)}`;
  const row = { id, episode_id: ep.id, verdict_id: verdict.verdict_id, status: "open", action: verdict.action, amount: verdict.amount, reason: verdict.reason, entity_type: verdict.entity_type, entity_id: verdict.entity_id, opened_at: ts(), expires_at: new Date(Date.now() + ESC_TIMEOUT_MS).toISOString() };
  escalations.set(id, row);
  emit(ep, "escalation.opened", day, "battlefield", { escalation_id: id, verdict_id: verdict.verdict_id, action: verdict.action, entity_type: verdict.entity_type, entity_id: verdict.entity_id, amount: verdict.amount, reason: verdict.reason, expires_at: row.expires_at });
  return new Promise((resolve) => {
    row.resolve = (decision, by) => {
      if (row.status !== "open") return false;
      clearTimeout(timer);
      row.status = decision === "approve" ? "approved" : decision === "timeout" ? "timeout" : "blocked";
      emit(ep, "escalation.resolved", day, by === "system" ? "battlefield" : "human", { escalation_id: id, decision, by });
      resolve(decision);
      return true;
    };
    const timer = setTimeout(() => row.resolve("timeout", "system"), ESC_TIMEOUT_MS);
  });
}

async function loopEpisode(ep) {
  ep.task = true;
  while (ep.status === "running" && ep.current_day < ep.days) {
    await ep.dayLock;
    ep.dayLock = runDay(ep).catch(() => {});
    await ep.dayLock;
    await sleep(DAY_PAUSE_MS);
  }
  ep.task = false;
}


// ---- /api/fe views, derived from the events ----------------------------------------------------------------------------

function feView(ep, what, sub, url) {
  const ev = ep.events;
  const by = (t) => ev.filter((e) => e.type === t);
  if (what === "snapshot") {
    const open = ep.status === "finished" ? 0 : 14 - ep.current_day;
    return { episode: pub(ep), company: { name: "Coastal Supply Co.", cash_position: 412033.12 - ep.score.dollars_extracted, employees_active: 40, vendors: { active: 61, frozen: by("vendor.frozen").length, new_this_episode: by("attack.launched").length }, paid_last_day: 18822.4 }, ap: { open: { n: open, total: open * 4380.5 }, overdue: { n: 2, total: 4100 } }, controls: { mode: ep.controller_mode, open_escalations: [...escalations.values()].filter((x) => x.episode_id === ep.id && x.status === "open").length }, exposure: { red_dollars_in_flight: 0 }, score: ep.score };
  }
  if (what === "timeline") {
    const days = [...new Set(by("day.ended").map((e) => e.day))];
    return days.map((d) => {
      const sc = [...by("score.updated")].filter((e) => e.day === d).pop()?.payload ?? zero();
      const vs = by("gate.verdict").filter((e) => e.day === d);
      return { day: d, extracted_cumulative: sc.dollars_extracted, blocked_cumulative: sc.dollars_blocked, attacks_launched: by("attack.launched").filter((e) => e.day === d).length, verdict_allow: vs.filter((e) => e.payload.verdict === "allow").length, verdict_block: vs.filter((e) => e.payload.verdict === "block").length, verdict_escalate: vs.filter((e) => e.payload.verdict === "escalate").length, flags_raised: by("flag.raised").filter((e) => e.day === d).length };
    });
  }
  if (what === "ap_aging") return [{ bucket: "current", n: 9, total: 38200 }, { bucket: "1-30", n: 4, total: 15840.5 }, { bucket: "31-60", n: 2, total: 4100 }, { bucket: "60+", n: 1, total: 980 }];
  if (what === "verdicts" && sub === "confusion") {
    const vs = by("gate.verdict").map((e) => e.payload);
    const red = vs.filter((v) => v.entity_type === "invoice" && v.amount >= 4000);
    return [{ verdict: "block", origin: "red", n: red.filter((v) => v.verdict !== "allow").length, dollars: 0 }, { verdict: "allow", origin: "sim", n: vs.filter((v) => v.verdict === "allow").length, dollars: 0 }, { verdict: "block", origin: "sim", n: 0, dollars: 0 }, { verdict: "allow", origin: "red", n: ep.controller_mode === "enforce" ? 0 : red.length, dollars: 0 }];
  }
  if (what === "verdicts") return by("gate.verdict").slice(-Number(url.searchParams.get("limit") ?? 100)).map((e, i) => ({ ...e.payload, day: e.day, latency_ms: 38 + ((i * 53) % 190), entity_origin: null }));
  if (what === "reports") return by("report.posted").map((e) => ({ id: e.payload.report_id, day: e.day, preview: `Day ${e.day} controller report` }));
  if (what === "controls") return { ...controlsReport, episode: { ...controlsReport.episode, ...pub(ep) }, final: ep.status === "finished" || ep.status === "failed" };
  if (what === "escalations") return [...escalations.values()].filter((x) => x.episode_id === ep.id).map(({ resolve, ...x }) => x);
  return [];
}

// ---- http ----------------------------------------------------------------------------------------------------------

const json = (res, status, body) => {
  res.writeHead(status, { "content-type": "application/json", "cache-control": "no-store" });
  res.end(JSON.stringify(body));
};
const readBody = (req) => new Promise((resolve) => { let b = ""; req.on("data", (c) => (b += c)); req.on("end", () => { try { resolve(b ? JSON.parse(b) : {}); } catch { resolve({}); } }); });
const pub = (ep) => ({ id: ep.id, seed: ep.seed, controller_mode: ep.controller_mode, days: ep.days, status: ep.status, current_day: ep.current_day, attack_plan: null, lineage_id: null, generation: null, created_at: ep.created_at });

const lineageRow = () => ({
  id: lineageReport.lineage.id, name: lineageReport.lineage.name, status: "finished", base_seed: 42, current_generation: 3,
  generations: lineageReport.generations.map((g) => ({ generation: g.generation, episode_id: g.episode_id, seed: g.seed, status: g.status, score: g.score })),
  playbook_versions: { red: 3, green: 0, blue: 1 },
});

async function route(req, res) {
  const url = new URL(req.url, "http://x");
  const path = url.pathname;
  if (!path.startsWith("/api/")) return json(res, 404, { detail: "not found" });
  if (req.headers.authorization !== `Bearer ${TOKEN}`) return json(res, 401, { detail: "bad token" });
  const m = req.method;
  const seg = path.slice(5).split("/");

  if (m === "GET" && path === "/api/health") {
    const a = (name) => ({ ok: true, agent: name, model: "fake", droid_ok: false, dry_run: true });
    return json(res, 200, { ok: true, db: true, agents: { red: a("red"), green: a("green"), blue: a("blue") } });
  }
  if (m === "GET" && path === "/api/schemes") return json(res, 200, SCHEMES);
  if (m === "POST" && path === "/api/ws/ticket") {
    const body = await readBody(req);
    const ticket = randomUUID();
    tickets.set(ticket, { episode: body.episode_id ?? "*", exp: Date.now() + 60_000 });
    return json(res, 200, { ticket, expires_at: new Date(Date.now() + 60_000).toISOString() });
  }
  if (m === "POST" && path === "/api/episodes") {
    const b = await readBody(req);
    if (!["off", "shadow", "enforce"].includes(b.controller_mode ?? "shadow")) return json(res, 422, { detail: "controller_mode must be off|shadow|enforce" });
    const ep = { id: `ep_${randomUUID().slice(0, 12)}`, seed: b.seed ?? 1, controller_mode: b.controller_mode ?? "shadow", days: b.days ?? 10, status: "created", current_day: 0, created_at: ts(), events: [], score: zero(), forced: null, task: false, dayLock: Promise.resolve(), approved: new Set(), approvedAmount: 0, approvedFor: null };
    episodes.set(ep.id, ep);
    return json(res, 201, pub(ep));
  }
  if (m === "GET" && path === "/api/episodes") return json(res, 200, [...episodes.values()].map(pub).reverse());
  if (m === "POST" && path === "/api/inputs") {
    const b = await readBody(req);
    if (!episodes.get(b.episode_id) || !["red", "green", "blue"].includes(b.target)) return json(res, 422, { detail: "bad input" });
    const row = { id: inputs.length + 1, episode_id: b.episode_id, target: b.target, source: b.source ?? "operator", payload: b.payload ?? {}, created_at: ts() };
    inputs.push(row);
    return json(res, 201, row);
  }
  if (m === "GET" && path === "/api/inputs") return json(res, 200, inputs.filter((i) => !url.searchParams.get("episode_id") || i.episode_id === url.searchParams.get("episode_id")));
  if (m === "GET" && path === "/api/lineages") return json(res, 200, [lineageRow()]);
  if (m === "GET" && path === "/api/escalations") {
    const ep = url.searchParams.get("episode_id");
    const st = url.searchParams.get("status") ?? "open";
    return json(res, 200, [...escalations.values()].filter((e) => (!ep || e.episode_id === ep) && (st === "all" || e.status === st)).map(({ resolve, ...e }) => e));
  }
  if (m === "POST" && seg[0] === "escalations" && seg[2] === "resolve") {
    const b = await readBody(req);
    const row = escalations.get(seg[1]);
    if (!row || !["approve", "block"].includes(b.decision)) return json(res, row ? 422 : 409, { detail: "already resolved or unknown" });
    return row.resolve(b.decision, b.by ?? "judge") ? json(res, 200, { ok: true }) : json(res, 409, { detail: "already resolved or unknown" });
  }
  if (m === "GET" && path === "/api/events") {
    const ep = episodes.get(url.searchParams.get("episode_id"));
    const after = Number(url.searchParams.get("after_id") ?? 0);
    return json(res, 200, (ep?.events ?? []).filter((e) => e.id > after));
  }
  if (m === "GET" && seg[0] === "fe" && seg[1] === "lineages") return json(res, 200, seg[3] === "timeline" ? { entries: [] } : lineageReport);
  if (m === "GET" && seg[0] === "fe" && seg[1] === "compare") {
    const a = episodes.get(url.searchParams.get("a")), b = episodes.get(url.searchParams.get("b"));
    if (!a || !b) return json(res, 404, { detail: "episode not found" });
    const d = (k) => Math.round((b.score[k] - a.score[k]) * 100) / 100;
    return json(res, 200, { a: { episode: pub(a), score: a.score }, b: { episode: pub(b), score: b.score }, delta: { dollars_extracted: d("dollars_extracted"), dollars_blocked: d("dollars_blocked"), false_positive_cost: d("false_positive_cost") } });
  }
  if (seg[0] === "fe" && seg[1] === "episodes" && seg[2]) {
    const ep = episodes.get(seg[2]);
    if (!ep) return json(res, 404, { detail: "episode not found" });
    return json(res, 200, feView(ep, seg[3], seg[4], url));
  }
  if (m === "GET" && seg[0] === "reports" && seg[1]) {
    for (const ep of episodes.values()) {
      const e = ep.events.find((x) => x.type === "report.posted" && x.payload.report_id === seg[1]);
      if (e) return json(res, 200, { id: seg[1], day: e.day, markdown: `# Day ${e.day} controller report\n\n- Vendors flagged: ${ep.events.filter((x) => x.type === "flag.raised" && x.day === e.day).length}\n- Invoices still pending: ${3 + (e.day % 3)}\n- Verdicts today: ${ep.events.filter((x) => x.type === "gate.verdict" && x.day === e.day).length}\n` });
    }
    return json(res, 404, { detail: "report not found" });
  }
  if (m === "GET" && path === "/api/replays") return json(res, 200, ["sample-enforce-4d"]);
  if (m === "POST" && seg[0] === "replays" && seg[2] === "play") {
    const b = await readBody(req);
    const ep = { id: `replay_sample-enforce-4d_${randomUUID().slice(0, 8)}`, seed: 42, controller_mode: "enforce", days: 4, status: "running", current_day: 0, created_at: ts(), events: [], score: zero(), forced: null, task: false, dayLock: Promise.resolve(), approved: new Set(), approvedAmount: 0, approvedFor: null };
    episodes.set(ep.id, ep);
    const speed = Number(b.speed) > 0 ? Number(b.speed) : 4;
    void (async () => {
      let prev = null;
      for (const e of fixture) {
        const t = new Date(e.ts).getTime();
        if (prev) await sleep(Math.min(3000, Math.max(0, (t - prev) / speed)));
        prev = t;
        emit(ep, e.type, e.day, e.agent, e.payload);
      }
      ep.status = "finished";
    })();
    return json(res, 202, { ok: true, episode_id: ep.id, events: fixture.length });
  }
  if (seg[0] === "fe" && seg[1] === "episodes" && seg[3] === "vendors") return json(res, 200, []);

  if (seg[0] === "episodes" && seg[1]) {
    const ep = episodes.get(seg[1]);
    if (!ep) return json(res, 404, { detail: "episode not found" });
    // contracts #123: one active run per battlefield. Starting, resuming or stepping another episode while one is running is a 409
    // that names the active one (replays never count).
    if (m === "POST" && ["start", "resume", "step"].includes(seg[2])) {
      const other = [...episodes.values()].find((x) => x.id !== ep.id && !x.id.startsWith("replay_") && (x.status === "running" || x.stepping));
      if (other) return json(res, 409, { error: "another run is active", episode_id: other.id, lineage_id: null });
    }
    if (m === "GET" && !seg[2]) return json(res, 200, pub(ep));
    if (m === "GET" && seg[2] === "score") return json(res, 200, ep.score);
    if (m === "POST" && seg[2] === "start") {
      if (ep.status === "created" || ep.status === "paused") {
        if (!ep.events.some((e) => e.type === "episode.started")) emit(ep, "episode.started", 0, "battlefield", { controller_mode: ep.controller_mode, days: ep.days, seed: ep.seed });
        ep.status = "running";
        if (!ep.task) void loopEpisode(ep);
      }
      return json(res, 202, { ok: true });
    }
    if (m === "POST" && seg[2] === "pause") { ep.status = "paused"; emit(ep, "episode.paused", ep.current_day, "battlefield", {}); return json(res, 200, { ok: true }); }
    if (m === "POST" && seg[2] === "resume") { ep.status = "running"; emit(ep, "episode.resumed", ep.current_day, "battlefield", {}); if (!ep.task) void loopEpisode(ep); return json(res, 200, { ok: true }); }
    if (m === "POST" && seg[2] === "step") {
      if (ep.status === "running") return json(res, 409, { detail: "episode is running; pause first" });
      if (ep.status === "created") { ep.status = "paused"; emit(ep, "episode.started", 0, "battlefield", { controller_mode: ep.controller_mode, days: ep.days, seed: ep.seed }); }
      if (ep.current_day >= ep.days) return json(res, 200, { done: true });
      await ep.dayLock;
      ep.stepping = true;
      ep.dayLock = runDay(ep);
      try { return json(res, 200, await ep.dayLock); } finally { ep.stepping = false; }
    }
    if (m === "PATCH" && seg[2] === "controller") {
      const b = await readBody(req);
      if (!["off", "shadow", "enforce"].includes(b.mode)) return json(res, 422, { detail: "bad mode" });
      const from = ep.controller_mode;
      ep.controller_mode = b.mode;
      emit(ep, "controller.changed", ep.current_day, "human", { from, to: b.mode });
      return json(res, 200, { ok: true, mode: b.mode });
    }
    if (m === "POST" && seg[2] === "attack") { const b = await readBody(req); ep.forced = b.scheme_id; return json(res, 202, { ok: true, queued_for: "next red turn" }); }
  }
  return json(res, 404, { detail: "not found" });
}

// ---- websocket (just enough of RFC 6455: server → client text frames) ---------------------------------------------------

function frame(text) {
  const body = Buffer.from(text);
  const n = body.length;
  const head = n < 126 ? Buffer.from([0x81, n]) : n < 65536 ? Buffer.from([0x81, 126, n >> 8, n & 255]) : (() => { const h = Buffer.alloc(10); h[0] = 0x81; h[1] = 127; h.writeBigUInt64BE(BigInt(n), 2); return h; })();
  return Buffer.concat([head, body]);
}
const send = (socket, e) => { if (!socket.destroyed) socket.write(frame(JSON.stringify(e))); };

const server = createServer((req, res) => { route(req, res).catch((err) => json(res, 500, { detail: String(err) })); });

server.on("upgrade", (req, socket) => {
  const url = new URL(req.url, "http://x");
  const t = tickets.get(url.searchParams.get("ticket"));
  const wanted = url.searchParams.get("episode_id") ?? "*";
  if (url.pathname !== "/api/ws" || !t || t.exp < Date.now() || (t.episode !== "*" && t.episode !== wanted)) {
    socket.write("HTTP/1.1 401 Unauthorized\r\n\r\n");
    return socket.destroy();
  }
  tickets.delete(url.searchParams.get("ticket")); // single use
  const accept = createHash("sha1").update(`${req.headers["sec-websocket-key"]}258EAFA5-E914-47DA-95CA-C5AB0DC85B11`).digest("base64");
  socket.write(`HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ${accept}\r\n\r\n`);
  const entry = { socket, episode: wanted };
  const after = Number(url.searchParams.get("after_id") ?? 0);
  for (const e of episodes.get(wanted)?.events ?? []) if (e.id > after) send(socket, e);
  sockets.add(entry);
  const ping = setInterval(() => send(socket, { type: "ping" }), 15_000);
  const gone = () => { clearInterval(ping); sockets.delete(entry); };
  socket.on("data", (d) => { if ((d[0] & 0x0f) === 0x8) { socket.end(Buffer.from([0x88, 0])); gone(); } }); // client close
  socket.on("close", gone);
  socket.on("error", gone);
});

server.listen(PORT, "127.0.0.1", () => console.log(`fake battlefield on http://127.0.0.1:${PORT} (token "${TOKEN}", day pause ${DAY_PAUSE_MS} ms)`));
