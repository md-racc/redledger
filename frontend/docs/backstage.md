# Backstage: raw consoles for the other laptops

The live demo uses four laptops on one domain. One runs the arena (the pretty one). The other three show what each team's
backend is doing **right now**. The backstage is the opposite of the arena on purpose: monospace, white on black, no layout,
no styling. It is evidence that the code runs, not a dashboard.

Nothing links to it. No tab, no nav, no button. You type the address.

| address | follows |
|---|---|
| `/backstage` | a plain list of the four addresses |
| `/backstage/red` | red's events, the attack tape folded from them, red's thinking and tool calls |
| `/backstage/green` | green's gated attempts and what blue said, AP and cash, what it waits on, thinking, tool calls |
| `/backstage/blue` | the verdicts, the rule board, the confusion matrix, flags and freezes, open escalations with approve / block buttons |
| `/backstage/battlefield` | `/health` of every service, the episodes, and the **control plane** buttons (new episode, start / pause / resume / step, controller mode, force an attack, play a recording) |

Keys inside a console: `1`-`4` switch team, `0` the address list, `A` or `Esc` back to the arena. In the arena, `B` (or three
quick clicks on the brand) opens `/backstage` in a new tab. The pages carry `robots: noindex`.

## What every console prints, top to bottom

1. **Header**: which laptop this is, the time, whether the battlefield answers (and how fast), which episode it follows,
   events held and per minute, and the laptops the relay can see.
2. **LIVE CHECKS**: seven lines, each a thing measured this second, `[ OK ]` or `[FAIL]` (`components/backstage/raw.ts`,
   `liveChecks`): battlefield reachable through the proxy, agents answer `/health`, events arriving (age of the last one), the
   gate issuing verdicts, the relay up, the arena laptop seen in the last 30 s, API calls passing through the proxy.
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
   selector pins another one.
2. When the followed episode changes, the ticketed WebSocket (`lib/ws.ts`) is opened with `after_id=0`, so a laptop that joins
   late still receives the whole episode, then the live tail. The socket address is derived from the page host when
   `NEXT_PUBLIC_WS_URL` is unset (`lib/wsurl.ts`), which is what keeps the whole thing on one domain behind Caddy.
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
[development.md](development.md)) and the frontend pointed at it.

## Files

`app/backstage/` (`layout.tsx`, `page.tsx`, `[team]/page.tsx`, `backstage.css`), `components/backstage/` (`RawConsole.tsx`,
`BackstageApp.tsx`, `useBackstage.ts`, `derive.ts`, `raw.ts`), `lib/sync/` (`hub.ts`, `client.ts`), `app/api/sync/` (`route.ts`,
`stream/route.ts`), `lib/wsurl.ts`.
