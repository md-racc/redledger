// Thin REST client for battlefield. Owner: Dev R. Full surface: battlefield /docs and FRONTEND-API.md.
const BASE = process.env.NEXT_PUBLIC_BATTLEFIELD_URL ?? "http://localhost:8000";
const TOKEN = process.env.NEXT_PUBLIC_INTERNAL_TOKEN ?? "change-me";

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(`${BASE}/api${path}`, {
    method,
    headers: { Authorization: `Bearer ${TOKEN}`, "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });
  if (!r.ok) throw new Error(`${method} ${path} → ${r.status}: ${await r.text()}`);
  return r.status === 204 ? (undefined as T) : r.json();
}

export const api = {
  // control plane
  createEpisode: (b: { controller_mode: "off" | "shadow" | "enforce"; seed?: number; days?: number; attack_plan?: unknown[] }) => call<any>("POST", "/episodes", b),
  listEpisodes: () => call<any[]>("GET", "/episodes"),
  getEpisode: (id: string) => call<any>("GET", `/episodes/${id}`),
  start: (id: string) => call<void>("POST", `/episodes/${id}/start`),
  pause: (id: string) => call<void>("POST", `/episodes/${id}/pause`),
  resume: (id: string) => call<void>("POST", `/episodes/${id}/resume`),
  step: (id: string) => call<any>("POST", `/episodes/${id}/step`),
  setController: (id: string, mode: "off" | "shadow" | "enforce") => call<void>("PATCH", `/episodes/${id}/controller`, { mode }),
  forceAttack: (id: string, scheme_id: string, params?: Record<string, unknown>) => call<void>("POST", `/episodes/${id}/attack`, { scheme_id, params }),
  schemes: () => call<any[]>("GET", "/schemes"),
  openEscalations: (episode_id: string) => call<any[]>("GET", `/escalations?episode_id=${episode_id}&status=open`),
  resolve: (esc_id: string, decision: "approve" | "block", by = "judge") => call<void>("POST", `/escalations/${esc_id}/resolve`, { decision, by }),
  events: (episode_id: string, after_id = 0, limit = 5000) => call<any[]>("GET", `/events?episode_id=${episode_id}&after_id=${after_id}&limit=${limit}`),
  replays: () => call<string[]>("GET", "/replays"),
  playReplay: (id: string, speed = 4, episode_id?: string) => call<any>("POST", `/replays/${id}/play`, { speed, episode_id }),
  // frontend read API (/api/fe/…)
  fe: {
    snapshot: (ep: string) => call<any>("GET", `/fe/episodes/${ep}/snapshot`),
    timeline: (ep: string) => call<any[]>("GET", `/fe/episodes/${ep}/timeline`),
    apAging: (ep: string) => call<any[]>("GET", `/fe/episodes/${ep}/ap_aging`),
    entity: (ep: string, type: string, id: string) => call<any>("GET", `/fe/episodes/${ep}/entities/${type}/${id}`),
    vendors: (ep: string, sort: "risk" | "spend" | "name" | "newest" = "risk") => call<any[]>("GET", `/fe/episodes/${ep}/vendors?sort=${sort}`),
    attacks: (ep: string) => call<any[]>("GET", `/fe/episodes/${ep}/attacks`),
    attackLeaderboard: (ep: string) => call<any[]>("GET", `/fe/episodes/${ep}/attacks/leaderboard`),
    verdicts: (ep: string, q: Record<string, string | number> = {}) => call<any[]>("GET", `/fe/episodes/${ep}/verdicts?${new URLSearchParams(q as any)}`),
    rules: (ep: string) => call<any[]>("GET", `/fe/episodes/${ep}/verdicts/rules`),
    confusion: (ep: string) => call<any[]>("GET", `/fe/episodes/${ep}/verdicts/confusion`),
    agentActivity: (ep: string) => call<any>("GET", `/fe/episodes/${ep}/agents/activity`),
    thinking: (ep: string, agent: string, day?: number) => call<any[]>("GET", `/fe/episodes/${ep}/agents/${agent}/thinking${day === undefined ? "" : `?day=${day}`}`),
    compare: (a: string, b: string) => call<any>("GET", `/fe/compare?a=${a}&b=${b}`),
    feed: (ep: string, after_id = 0) => call<any[]>("GET", `/fe/episodes/${ep}/feed?after_id=${after_id}`),
    search: (ep: string, q: string) => call<any[]>("GET", `/fe/episodes/${ep}/search?q=${encodeURIComponent(q)}`),
    reports: (ep: string) => call<any[]>("GET", `/fe/episodes/${ep}/reports`),
    report: (id: string) => call<any>("GET", `/reports/${id}`),
    escalations: (ep: string) => call<any[]>("GET", `/fe/episodes/${ep}/escalations`),
  },
};
