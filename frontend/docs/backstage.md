# Backstage: raw consoles for the other laptops

The live demo uses four laptops on one domain. One runs the arena (the pretty one). The other three show what each team's
backend is doing **right now**. The backstage is the opposite of the arena on purpose: monospace, white on black, no layout,
no styling. It is evidence that the code runs, not a dashboard.

Nothing links to it. No tab, no nav, no button for the public. You type the address, or (as an admin) you use the hidden doors below.

| address | follows |
|---|---|
| `/backstage` | a plain list of the four addresses |
| `/backstage/red` | red's events, the attack tape folded from them, red's thinking and tool calls |
| `/backstage/green` | green's gated attempts and what blue said, AP and cash, what it waits on, thinking, tool calls |
| `/backstage/blue` | the verdicts, the rule board, the confusion matrix, flags and freezes, open escalations with approve / block buttons |
| `/backstage/battlefield` | `/health` of every service, the episodes, and the **control plane** buttons (new episode, start / pause / resume / step, controller mode, force an attack, play a recording) |

Keys inside a console: `1`-`4` switch team, `0` the address list, `A` or `Esc` back to the arena. In the arena, for an admin only,
`B` (or three quick clicks on the brand) opens `/backstage` in a new tab; a viewer pressing them gets nothing. The pages carry
`robots: noindex`.

## What every console prints, top to bottom

1. **Header**: which laptop this is, the time, whether the battlefield answers (and how fast), which episode it follows,
   events held and per minute, and the laptops the relay can see.
2. **LIVE CHECKS**: seven lines, each a thing measured this second, `[ OK ]` or `[FAIL]` (`components/backstage/raw.ts`,
   `liveChecks`): battlefield reachable through the proxy, agents answer `/health`, the event stream delivering, the gate
   issuing verdicts, the relay up, the arena laptop seen in the last 30 s, API calls passing through the proxy.
   - *Event stream delivering* fails only when it should: something is running and nothing arrives for 60 s, or neither the
     socket nor the REST read works (the line then says why). A finished or not-yet-started episode is quiet on purpose and
     reads `idle: episode finished, 260 events delivered, nothing new to send`. The detail also says how events arrive:
     `(websocket)`, or `(REST fallback: the websocket would not open)`.
   - *Arena laptop connected* is red until the arena is open **and signed in as admin** (`/admin` on that laptop): a viewer's
     arena shows but does not report to the relay.
3. **DEMO SCREEN**: what the arena laptop has selected, which card is open, the show beat, the controller mode, and the last
   relayed actions. If the selected agent belongs to this console's team, a highlighted line says so, and the matching lines
   further down are highlighted too (`concerns()`: a red scheme id, a blue rule id).
4. **API TRAFFIC**: every call the frontend server forwarded to the battlefield, from every laptop, with method, path, status,
   milliseconds and the laptop that made it. The consoles' own polling is counted, not listed.
5. **EVENTS**: this team's events, raw, one per line, newest first (`teamEvents`).
6. **STATE**: what the events add up to for this team (`derive.ts`).
7. **RAW READ API**: the JSON the `/api/fe` reads returned.

## How a selection on the demo screen reaches the other laptops

The laptops are separate browsers, so the frontend server is the meeting point (`lib/sync/`):

- The arena publishes what the presenter does (`select`, `launch`, `controller`, `decision`, `panel`, `stage`, `show`, `run`,
  `act`, plus a `hello` heartbeat every 8 s) with `POST /api/sync`. A client id (`arena-xxxx`, `backstagered-xxxx`) lives in
  `sessionStorage`, goes in the `X-RL-Client` header of every proxy call, and tags the traffic log.
- `lib/sync/hub.ts` is an in-memory `Hub` on `globalThis`: the folded state (selected, panel, stage, show, controller, last
  act, clients seen), the last 300 messages and the last 300 proxied calls, on one sequence counter. Everything is sanitised:
  flat primitives only, strings clipped, unknown kinds dropped.
- The backstage subscribes to `GET /api/sync/stream` (server-sent events, `x-accel-buffering: no`). If the stream cannot be
  held it polls `GET /api/sync?after=` every second, and the LIVE CHECKS line says which of the two it is on.
- The proxy (`app/api/bf/[...path]/route.ts`) records each forwarded call into the hub after it returns.

**Limit:** the hub lives in one Node process. The compose file runs exactly one `frontend` container and Caddy sends everything
except `/api/ws` to it, so this holds. Two frontend replicas would each have their own hub and the laptops would stop seeing one
another. Everything the arena does to the *backend* (create episode, step, attack, resolve) is unaffected: the consoles read
that from the battlefield itself.

## How a console follows the run

(`components/backstage/useBackstage.ts`)

1. `GET /api/health` and `GET /api/episodes` every 2.5 s through the `/api/bf` proxy. The episode that is *running* is followed
   (battlefield allows one active run), else the newest, whoever made it (the arena's show, a curl, the battlefield console). A
   selector pins another one. Only a backend that is really gone (network failure, timeout, 5xx) switches to the recorded loop; a
   refusal (403 not signed in, 401 token, 429 rate limit) is an answer, so the console keeps asking and says what it got:
   `backend REFUSED 403 ...` and `[FAIL] ... refused, not unreachable: 403 ...`.
2. When the followed episode changes, the ticketed WebSocket (`lib/ws.ts`) is opened with `after_id=0`, so a laptop that joins
   late still receives the whole episode, then the live tail. The socket address is derived from the page host when
   `NEXT_PUBLIC_WS_URL` is unset (`lib/wsurl.ts`), which is what keeps the whole thing on one domain behind Caddy. If two socket
   attempts in a row deliver nothing (a venue network or proxy that drops the upgrade, a dev server with no `/api/ws`, a ticket
   that keeps being refused), the same file also reads `GET /events?after_id=` through the proxy every 1.5 s and the header
   reads `via REST (socket blocked)`; the first frame a socket delivers ends the polling. Both the arena and the consoles use it.
3. Events go through the same reducer as the arena. `/api/fe` reads add what events do not carry (`snapshot`, `ap_aging`,
   `verdicts`, `verdicts/confusion`, `reports`, `timeline`), every 4 s and right after day ends.
4. With no battlefield a console loops the recorded episode with fresh timestamps and the first LIVE CHECK says `[FAIL]`, so a
   rehearsal can never be mistaken for the real thing.

No token is needed in the browser; all of it goes through the proxy.

## Setting up four laptops

1. All four open the same site (same domain).
2. Laptop 1: `/`. Laptops 2-4: `/backstage/red`, `/backstage/green`, `/backstage/blue` (or battlefield on one of them).
3. Start the show on laptop 1 (`S`). Its episodes, selections and decisions appear on the others within a second or two.

Rehearse with no stack: `npm run dev:live` starts `tools/fake-battlefield.mjs` (a stand-in for the contract, see
[development.md](development.md)) and the frontend pointed at it. Other laptops can open it by this machine's LAN address
(`http://<its address>:3104/backstage/red`): the dev server has no `/api/ws`, so they read events over REST (the header says so).
The real socket path is only exercised on the deployed site.

## Files

`app/backstage/` (`layout.tsx`, `page.tsx`, `[team]/page.tsx`, `backstage.css`), `components/backstage/` (`RawConsole.tsx`,
`BackstageApp.tsx`, `useBackstage.ts`, `derive.ts`, `raw.ts`), `lib/sync/` (`hub.ts`, `client.ts`), `app/api/sync/` (`route.ts`,
`stream/route.ts`), `lib/wsurl.ts`.

## The hidden doors: `red.<site>` and `blue.<site>`

Two addresses for the two consoles that make the best show of a messy backend. `red.redledger.us` is red's console and `blue.redledger.us`
is blue's, the same pages as `/backstage/red` and `/backstage/blue`, reached by hostname.

- **How they work.** `next.config.ts` rewrites `/` on any `red.*` or `blue.*` host to `/backstage/<team>`
  (`lib/backstage/alias.ts` knows what a door host is). Locally, browsers resolve `*.localhost`: `http://red.localhost:3000/`.
- **Hidden.** On a door host the page exists only for an **admin** (`lib/backstage/gate.ts`). Anyone else gets exactly the 404 a mistyped
  address gets: not a 403, not a login prompt, so the door's existence is not confirmed. This covers every console under a door host, not
  only that team's. The plain `/backstage/...` paths are unchanged.
- **Quiet.** The browser tab reads only `red.redledger` or `blue.redledger` (not "backstage"). In the arena an admin sees two diamonds in
  the bottom-right corner at about 8% opacity (`components/arena/overlays/Doors.tsx`); they light up when the pointer is on them and open
  the door for the site you are on (`app.redledger.us` becomes `red.redledger.us`). A viewer gets no element at all, and the `B` key and the
  brand's triple-click now do nothing for a viewer.
- **The knock.** The admin cookie belongs to the host that set it, so on a door host you log in once at `/admin` on that host (the page
  works there; everything else is a 404 until you do). The cookie then lasts seven days.
- **The messy backend.** With no battlefield behind it, or with `?replay=1` on the address, the red and blue consoles replay the real
  live-red run from `docs/recordings` (copied to `public/mocks/demo-enforce-live.jsonl`; a test fails if the copy drifts): about 1,200
  raw events, the tool calls, ledger writes, verdicts, escalations and reasoning, paced by the run's own gaps (bursts stay bursts, pauses
  stay pauses, a long Droid turn cut to four seconds) over 90 seconds, then again. The header says it is a replay. Live, they show the
  live battlefield as before.

**Turning the doors on for real hostnames (Ad's side, outside `frontend/`).** The frontend already answers `red.*` and `blue.*`. The
domain has to deliver them: a DNS record for each, pointing at the same origin as `app.`; the edge (`deploy/Caddyfile`) must send those
hosts to the `frontend` container like `app.`; and the Cloudflare Access application must cover them (a wildcard policy, or one app per host;
`CF_ACCESS_AUD` has to match the token Access issues for them). Until then the doors work on `localhost` and on any host that already
reaches the frontend.
