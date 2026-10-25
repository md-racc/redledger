# Frontend API reference

Browser base URL: same-origin `/api/bf`. `/api/bf/<path>?<query>` mirrors battlefield
`/api/<path>?<query>` exactly (method, body, content-type, status, streamed body); the Next
route handler `app/api/bf/[...path]/route.ts` adds `Authorization: Bearer $OPERATOR_TOKEN`
server-side. The browser sends no token and no `Authorization` header; the proxy drops the
browser's `Authorization`, cookies and any `X-*` headers. Paths below are relative to that base
(battlefield `/api/episodes` = browser `/api/bf/episodes`). Interactive docs with live schemas:
`${BATTLEFIELD_URL}/docs`. `lib/api.ts` wraps all of this.

Server env (no `NEXT_PUBLIC_` prefix, read per request): `BATTLEFIELD_URL`, `OPERATOR_TOKEN`.
**Never put a token in a `NEXT_PUBLIC_` var**; those are inlined into the browser bundle at build.
Proxy errors: `502 {error}` if those vars are unset or battlefield is unreachable, `504` on
upstream timeout (30 s; 300 s for `POST /episodes/{id}/step`), `400` on a path containing
`..`/encoded slashes, `403` for a cross-site (`Sec-Fetch-Site: cross-site`) mutation.

Viewers and admins: the site is public and read-only (prod since 2026-10-25, #152/#159). Anyone is a **viewer**; only a
browser signed in at `/admin` (`ADMIN_KEY`, see `AGENTS.md`) is an **admin**. For a viewer the proxy forwards GET/HEAD
only (`403 {"error":"viewer"}` otherwise), refuses the reads that say which rows are red's (`/attacks*`, `/audit_log`,
`/state*`, `/fe/compare`, `/fe/episodes/{ep}/attacks`, `.../entities/*`, `.../state/*`, `.../verdicts/rules`,
`.../verdicts/confusion`, `/lineages/{id}/export`; `lib/proxy.ts` `OPERATOR_ONLY`), and removes `origin`,
`entity_origin` and `origin_of_source` from every JSON answer (`stripGroundTruth`). A viewer's WS ticket must name an
episode. So the `origin` / `entity_origin` fields named below reach admins only. `/api/sync` (the laptop relay) is
admin-only both ways.

Origin auth: when `CF_ACCESS_TEAM_DOMAIN` and `CF_ACCESS_AUD` are set (both blank on prod since P7), `middleware.ts`
requires a valid Cloudflare Access JWT (`Cf-Access-Jwt-Assertion` header or `CF_Authorization`
cookie) on every page and `/api/bf/*` call, else `403 {"error":"forbidden"}`. The browser does
nothing: Access sets both on requests through `app.<domain>`. Unset (local, mock, CI) → no check.
A `403 {error: "forbidden"}` from `/api/bf/*` therefore means "not through our Access app", not a
battlefield error. See `AGENTS.md` for the details.

Two layers:
- **Live stream** — WebSocket and `GET /api/events` (browser: `/api/bf/events`). One `RLEvent`
  per frame, see `contracts/events.md`. Fold with `lib/reducer.ts`. Socket auth is a ticket:
  1. `GET /api/bf/ws-ticket?episode_id=<id>` (Next route; calls battlefield
     `POST /api/ws/ticket {episode_id}` with the operator token) → `{ticket, expires_at, ws_url}`.
     The ticket is valid 60 s, single use, scoped to that episode (`*` when `episode_id` omitted).
     `ws_url` is `NEXT_PUBLIC_WS_URL` read at request time on the server.
  2. Open `${ws_url}/api/ws?episode_id=<id>&ticket=<ticket>&after_id=<n>`.
  3. Invalid/expired ticket → server closes with code `4401`. On any unrequested close,
     `lib/ws.ts` fetches a new ticket and reconnects with backoff, resuming from `after_id`.
  (`?token=<OPERATOR_TOKEN>` on `/api/ws` exists for curl/debug only; never from the browser.)
- **Read API** — `/api/fe/...` returns derived views of the same episode. Poll these or call on
  demand (click an attack → fetch its trail). All return JSON; money is a number in dollars.

## Control plane

| Method | Path | Body | Purpose |
|---|---|---|---|
| POST | `/episodes` | `{controller_mode, seed?, days?, attack_plan?}` | create (seeds the company; ~1–2 s) |
| GET | `/episodes` | | recent episodes |
| GET | `/episodes/{id}` | | status, current_day, controller_mode |
| POST | `/episodes/{id}/start` | | run continuously |
| POST | `/episodes/{id}/pause` · `/resume` | | |
| POST | `/episodes/{id}/step` | | run exactly one day (must be paused/created) → `{day, score}` |
| GET | `/episodes/{id}/score` | | current `Score` |
| PATCH | `/episodes/{id}/controller` | `{mode}` | live toggle; emits `controller.changed` |
| POST | `/episodes/{id}/attack` | `{scheme_id, params?}` | judge picks the next attack |
| GET | `/schemes` | | catalog for the picker (proxied from red) |
| GET | `/escalations?episode_id=&status=open` | | open human decisions |
| POST | `/escalations/{id}/resolve` | `{decision: approve\|block, by}` | 409 if already resolved |
| GET | `/replays` | | fixture ids |
| POST | `/replays/{id}/play` | `{speed, episode_id?}` | stream a fixture under a virtual episode id |
| GET | `/health` | | battlefield + agent health |

## Read API (`/api/fe`)

### `GET /fe/episodes/{ep}/snapshot`
Company-at-a-glance. Cheap; poll every few seconds if you like.
```json
{ "episode": {...}, "company": { "name": "Coastal Supply Co.", "cash_position": 412033.12, "employees_active": 40,
  "vendors": { "active": 61, "frozen": 1, "new_this_episode": 2 }, "paid_last_day": 18822.4 },
  "ap": { "open": { "n": 14, "total": 61200.5 }, "overdue": { "n": 2, "total": 4100 } },
  "controls": { "mode": "enforce", "open_escalations": 1 },
  "exposure": { "red_dollars_in_flight": 4920.0 }, "score": { ...Score } }
```

### `GET /fe/episodes/{ep}/timeline`
One row per day: `cash_in, cash_out, invoices_received, payments_made, verdict_allow, verdict_block, verdict_escalate, extracted_cumulative, blocked_cumulative, attacks_launched, flags_raised`. Chart fodder.

### `GET /fe/episodes/{ep}/ap_aging`
Buckets `current, 1-30, 31-60, 60+` with `n, total`.

### `GET /fe/episodes/{ep}/entities/{type}/{id}`
`type ∈ invoice | vendor | employee | expense | vendor_change | purchase_order | payment | attack`.
Returns the entity plus `verdicts, escalations, flags, audit_log, events` that touched it, and
type-specific joins (`vendor`, `po`, `payment`, `attack` for invoices; `invoices`, `changes`,
`purchase_orders` for vendors; `invoices`, `expenses` for attacks). This is the "click anything →
see its whole story" endpoint.

### `GET /fe/episodes/{ep}/vendors?sort=risk|spend|name|newest&limit=`
Vendor profiles with derived signals: `lifetime_paid, invoice_count, blocked_count,
recent_bank_changes, flag_count, no_po_invoices, newness, risk_score (0–100)`. Includes `origin`
(operator view; don't show live).

### `GET /fe/episodes/{ep}/attacks`
Every declared attack with `invoices, expenses, verdicts, flags`. Use for attack detail panes.

### `GET /fe/episodes/{ep}/attacks/leaderboard`
Per scheme: `attempts, extracted, targeted, caught, avg_latency`.

### `GET /fe/episodes/{ep}/verdicts?verdict=&action=&day=&rule=&limit=`
Filterable verdict list, each with `entity_origin` (ground truth) so you can show hits vs misses.

### `GET /fe/episodes/{ep}/verdicts/rules`
`rule × verdict × origin → n`. Which controls are doing the work, and which are noise.

### `GET /fe/episodes/{ep}/verdicts/confusion`
`verdict × origin → n, dollars` on money-moving actions. The honest controller scorecard
(true blocks, false blocks, misses).

### `GET /fe/episodes/{ep}/agents/activity`
`activity`: per agent per day `calls, ok, blocked, distinct_actions`. `turns`: per agent per day
`credits, seconds`.

### `GET /fe/episodes/{ep}/agents/{agent}/thinking?day=`
Concatenated thinking text per day. Same data as folding `agent.thinking` events; handy for
re-opening a past day.

### `GET /fe/compare?a=&b=`
Two episodes side by side: `episode, score, timeline, attacks` for each, plus `delta` on the
three money numbers. Intended for same seed, `off` vs `enforce`.

### `GET /fe/episodes/{ep}/feed?after_id=&limit=&include_verdict_allows=false`
Card-worthy events only, with `headline` and `subline` already composed. Use as a default
activity feed or ignore and compose your own from raw events.

### `GET /fe/episodes/{ep}/search?q=`
Free text across vendors, invoices, employees, verdict reasons → `[{kind, id, label, status}]`.

### `GET /fe/episodes/{ep}/reports` · `GET /reports/{id}`
Report list with 200-char preview; full markdown by id.

### `GET /fe/episodes/{ep}/escalations`
All escalations (open and resolved) joined with their verdicts.

### `GET /fe/episodes/{ep}/controls`
The controls assessment behind `/report/{ep}`: `controls[]` (per rule: fired, blocks, escalations, notes, `on_fraud`/`on_legit`
{n, dollars}, schemes, effect), `schemes[]` (attempts, outcomes, caught_by, lost and its split), `gaps[]` (why money got through),
`false_positives` (same pool as the score), `audit`, `evidence`, and the money split: `lost` (= score.dollars_extracted) =
`to_attacker_accounts` + `to_real_parties`, plus `unattributed` (lost not tied to a scheme row). The split is null for replays.
`final` is true once the episode is finished or failed. Contains no `origin` keys. **Viewers get it only when `final` is true**
(`403 {"error":"viewer","detail":"available when the run ends"}` before that); admins always.

## Agent read routes you may also use (operator sees everything)

`GET /vendors?episode_id=`, `/invoices?episode_id=&status=`, `/payments`, `/expenses`,
`/purchase_orders`, `/bank/transactions?from_day=&to_day=`, `/gl/entries`, `/flags`, `/audit_log`,
`/attacks/all?episode_id=`. Pass `episode_id` as a query param (agents pass it as a header).

## Notes

- Everything is per-episode. Create two episodes with the same `seed` and different
  `controller_mode` for the off/on demo; `compare` does the rest.
- `shadow` mode records verdicts with `enforced=false` and does not block. Useful to show
  "would have caught" during a baseline.
- Escalations time out after `ESCALATION_TIMEOUT_SEC` (90 s) and default to block.
- Public `battlefield/extensions/fe_*` routes (`/api/x/fe/...`) need no token; call them through
  the proxy (`/api/bf/x/fe/...`) or directly at the battlefield's public URL.
- Replays broadcast under a virtual `episode_id` (`replay_<fixture>` by default) and are not
  persisted; `/api/events` won't have them. The reducer handles `replay: true` frames.
