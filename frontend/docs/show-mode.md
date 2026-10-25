# The 90-second show, and the interactive layer

The whole site in a minute and a half, for a stage. `S` (or the red **90s show** button on the title, or `?show=1`) starts it;
`space` pauses, `←` `→` jump between beats, `esc` leaves. When it ends the visitor is left in the arena with everything live.

## The script (`lib/arena/show.ts`)

| t | beat | what happens |
|---|---|---|
| 0:00 | I open | the flight over the Palace and the title (the flight is shortened to 5.8 s in the show) |
| 0:06 | II cast | the scroll tour at film speed: guards, clients, fraudsters (the camera dwells at each chapter by the pacing curve) |
| 0:22 | III arena | everyone converges on the rotunda |
| 0:27 | IV off | **controller off**: an episode with nothing gating payments, the money walks out |
| 0:43 | V on | rewind to day 0, same seed, **controller on**: blue gates every payment; one case goes to a human |
| 1:05 | VI compare | the two runs side by side, numbers counting up |
| 1:15 | VII evolve | the evolution report: generations, what each agent rewrote in its playbook |
| 1:28 | VIII yours | hand-over: the attack console opens |

The progress bar numbers the beats in Roman numerals (I-VIII); a beat too short to carry its name shows the numeral alone, and the name is its tooltip.

`ShowDirector` only decides *when*. Everything it does to the world goes through `ShowHost` (camera scroll, act start, panels,
captions), so it is unit-tested with a fake host (`show.test.ts`); the React side is `components/arena/useShow.ts`.
The tour is driven by writing `window.scrollTo`, so the chapters, rail and camera all follow with no special show camera.
While the show runs, the visitor's wheel, touch and paging keys are swallowed (not `overflow: hidden`, which would drop the
scrollbar and shift the layout).

## Where the show's data comes from

The show picks its source when it starts (`wantLive` in `useShow.ts`):

- **live**: a battlefield answers `GET /health` and all its agents are keyless (`dry_run: true`), so episodes are free and
  fast. Each act creates a real episode (`POST /episodes`, seed 42, 4 days), connects the socket, and runs the days with
  `POST /episodes/{id}/step` on the show's clock. An escalation that nobody answers within 4.8 s is blocked through
  `POST /escalations/{id}/resolve`, so the show never waits on the backend's 90 s timeout.
- **recorded**: otherwise. The recorded episode (`public/mocks/sample.jsonl`) is re-cut by `lib/arena/showScripts.ts`.
  The controller-off act is a *projection* (the same attacks with nothing gating them; battlefield has no recorded off
  twin) and the UI says so.

`?show=live` or `?show=recorded` forces one. With live agents (credits, slow turns) it defaults to recorded.

## When the operator is already running something

Battlefield allows one active run at a time (contracts #122/#123); starting, resuming or stepping a second one answers `409 {error: "another run is active", episode_id, lineage_id}`. On stage the operator runs the live lineage or episode, and the screen should simply show it:

- **Run episode** and **Launch attack** look for a running episode first (`GET /episodes`) and, if there is one (or on a 409 anyway), *join* it: the socket attaches to that episode with a full catch-up and the note reads "watching the run already in progress". A running **lineage** is followed generation to generation (`GET /lineages/{id}` every 3 s) until it finishes. A launched attack is queued on the running episode (red picks it up on its next turn) instead of creating a sandbox. No empty episode is left behind.
- The **90-second show** cannot join: its off and on acts need their own episodes. With another run active, both acts play from the recording and the note says "the backend is busy with another run".
- The backstage consoles follow the *running* episode before the newest one, so they stay on the run on stage.

`lib/arena/activeRun.ts` (tested) parses the 409 and finds a lineage's current episode; `lib/api.ts` throws an `ApiError` that carries the status and body. The stand-in (`tools/fake-battlefield.mjs`) answers the same 409.

## Reading the screen: focus

Thirty agents is a lot to look at. `lib/arena/focus.ts` keeps a set of whoever is in an interaction right now (the fraudster,
its client and the guard in a live scene, a guard that just acted, the guard holding an open escalation, the selected agent).
Everyone else is dimmed (emissive, ring, beacon and floating props), and a spotlight (`.spot`, a screen-space radial gradient
over the interaction) darkens the rest of the frame. The HUD dims with it. It eases in fast and out slowly.

## What a judge can do (free play and after the show)

| | |
|---|---|
| **Run episode / Run again** | a live episode (`POST /episodes` + `/start`), or the recorded run without a backend |
| **Say it in your own words** | in the attack console: speak or type any fraud scheme, in any language (ElevenLabs speech-to-text on the server). Red reads those words (to set the amount and details) and the closest of its eight schemes runs. See [voice.md](voice.md) |
| **Launch attack** | the attack console. Live: `POST /episodes/{id}/attack` (queued for red's next turn); with no running episode a paused *sandbox* episode is created and each click forces the scheme and steps one day. Offline: `lib/arena/localAttack.ts` plays it from the mock agents' rules |
| **Controller off / shadow / enforce** | `PATCH /episodes/{id}/controller`; the HUD shows the mode |
| **Approve / Block** | an open escalation, against its clock. Approve it and that invoice goes through |
| **Compare** | off vs on from the runs this session finished (or the run in flight vs its projection). The **Real run** tab beside it shows the two recorded live-red runs on our server (seed 42, 10 days: off $10,285 stolen, on $1,824, with a day-by-day bar for each): the numbers the pitch says out loud. The card always opens on *This show* |
| **Evolution** | `GET /lineages` + `/fe/lineages/{id}/report`, or the recorded report (`public/mocks/lineage-report.json`) |
| **Report** | the end-of-day report: a chip per day that has one (`report.posted`). With a live backend it is blue's own text (`GET /reports/{id}`), drawn by a small markdown reader (`lib/markdown.ts`, no HTML injected). With a recording there is no text to fetch, so it shows a tally built from that day's events and says so |
| **raw** (on every card) | a small toggle that opens the JSON the card is built from: the escalation, the compare pair, the evolution report, the report, the dossier |
| **Source / Agents** (top bar) | an honest badge, LIVE, RECORDED, SHOW or REPLAY, and each agent's own `/health`: `live` (a real model, named) or `keyless` (canned turns) (`lib/arena/provenance.ts`). Hover for what it means |
| **Click an agent** (or pick one in the roster) | the camera goes to them and the dossier opens; the same selection shows on the backstage laptops |

There is no running commentary panel: the scene is the feed. Live events pass through a pacer (`lib/arena/pacer.ts`) so a day's burst is shown one beat at a time, and the agents involved are lit (see focus above). `lib/arena/headlines.ts` still holds the plain-English wording and the money formatter.

Everything the presenter does is also published to the other laptops (`lib/sync`, see [backstage.md](backstage.md)).

## Pitch mode (the live main screen)

`P`, `?pitch=1`, or the admin **Live pitch** button. A 5.8 s flight and a fast tour, then it joins the run that is going or (admin only)
creates a live enforce episode (seed 42 or `?seed=`, 4 days, no attack plan, so red picks its own schemes) and starts it. Captions
come only from real events: the day, red's own `turn.ended.summary`, a block or escalation's reason, attack outcomes, the score from
`score.updated`. An escalation gets a centred card with a countdown; an admin's screen auto-blocks after 40 s (viewers show the
backend's expiry). At `episode.ended` a closing card links the controls report (`/report/{ep}`). With no backend it replays the
real prod recording `public/mocks/pitch-fallback.jsonl` (ep_d9b561111d60, 2026-10-25) under a RECORDED badge, block-only. Pitch mode
and the 90-second show never run together. Code: `lib/arena/{pitch,narration}.ts`, `components/arena/usePitch.ts`,
`overlays/PitchOverlay.tsx`, `useFeed.ts` (`pitch`, `stopPitch`).

## Files

`lib/arena/`: `show.ts` (script + director), `showClock.ts`, `script.ts` (timed event scripts with holds for a human),
`showScripts.ts` (the recorded run re-cut, baseline projection, escalation), `useFeed.ts` (live + recorded feed, acts, sandbox),
`pacer.ts`, `localAttack.ts`, `headlines.ts`, `compare.ts`, `lineage.ts`, `liveRuns.ts`, `report.ts`, `provenance.ts`, `focus.ts`.
`components/arena/`: `useShow.ts`, `overlays/{ShowBar,ThreatConsole,CompareCard,EvolutionCard,ReportCard,Markdown,Raw}.tsx`.

### Why the show does not play the real runs

The recorded live-red runs (`docs/recordings`, #136) are the real thing, but they are a poor stage show: nine of ten attacks are the same
duplicate invoice, and the three escalations are bank-change approvals that nobody answers. The show keeps the richer mock-agent
recording (every scheme, a decision for a human) and labels it as a recording; the real numbers are one click away in the Compare card's
**Real run** tab. `node tools/gen-live-runs.mjs` rebuilds `public/mocks/live-runs.json` from the recordings (numbers only), and a test keeps
the two in step.
