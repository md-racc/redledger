# The agent dossier (click an agent)

Clicking an agent in the 3D scene (or picking it in the HUD roster) opens a dossier panel. It is plain HTML/CSS
(`components/arena/overlays/AgentModal.tsx`); its content comes from `lib/arena/details.ts`.

## How picking works

`components/arena/Picking.tsx` listens on the canvas and uses an explicit `THREE.Raycaster` against an invisible pick
volume on every agent (`FigureHandle.hit`, a cylinder carrying `userData.agentId`).

- **hover** (pointer move, no buttons): sets `hoveredId`, the cursor, and brightens that agent; a name tag follows it
- **click** (pointer down + up within 6 px and 700 ms, so a drag never selects): selects the agent; clicking empty space
  closes the dossier
- **screen-space assist**: at aerial distances an agent is a few pixels wide, so a ray miss falls back to the nearest agent
  head within 30 px
- only live in the `scroll` and `arena` stages

Selecting also dollies the camera in on the agent (26 m), shifts the projection centre so it sits clear of the panel (left
of it on desktop, above it on phones), and the panel draws a dashed connector line to the agent. `Esc` closes; the arrows
step through the agents of the same team.

## What the panel shows

```
FRAUDSTER · RED TEAM                              01/08
Ghost Vendor                      (serif title)
scheme · ghost_vendor             (mono caption)
[● blocked]   [placeholder data]   ‹  ›  ✕
│ "A brand-new vendor appears …"  (serif quote)
SCHEME            scheme_id ............ ghost_vendor
                  Expected impact ...... ○ GET /schemes → expected_impact
THIS EPISODE      Attempts ............. 1
                  Targeted ............. $4,920
RUNTIME           Droid model .......... gpt-5.4-mini            (GET /health → agents.red.model)
                  Factory credits ...... 1,240 over 3 turns · 410 today
```

A row whose value is missing renders the dashed `○ <source>` pill. The source is the endpoint or event field the value
should come from, so a placeholder is a to-do that names its own data. `placeholder data` shows in the header while nothing
real has been merged yet.

### What the team is thinking

Under the sections the dossier shows **what this team's agent has been thinking**: the newest two days of `agent.thinking`, folded per day by the
reducer (`lib/arena/thinking.ts`), the newest open. A figure in the arena speaks for its team's agent (red, green or blue). With no
`agent.thinking` yet (the mock-agent recording has none) it shows the usual dashed placeholder naming `agent.thinking`. A **raw** toggle at the
bottom opens the JSON the dossier was built from.

## Where values come from (three layers, later wins)

1. **Derived from the event stream** (`buildDetails(id, state, …)` reads `UIState` from the reducer): attempts, targeted,
   extracted, caught, detection latency, latest attack and status per scheme; fires, blocks, escalations, dollars stopped,
   mean confidence and latest reason per rule; attacks aimed at, dollars at risk and dollars lost per client; frozen
   state.
2. **Catalogs** (`useFeed` fetches them when an episode runs live): `GET /schemes` fills display name, story, expected
   impact and params for a fraudster; `GET /fe/episodes/{ep}/vendors?sort=spend` (top 12) binds clients to vendors
   (name, category, risk score, lifetime paid, invoice and blocked counts, status).
3. **Host overrides**: the `agentDetails` prop on `<ArenaExperience>` (type `AgentDetailOverrides`), keyed by agent id.
   Top-level keys (`title`, `caption`, `story`, `status`, `role`) replace the derived ones; `fields` sets individual rows by
   key. Setting any `fields` clears the `placeholder data` badge.

```tsx
<ArenaExperience
  agentDetails={{
    "red:ghost_vendor": {
      story: "New vendor, same day, just under the line.",
      status: { label: "extracted", tone: "bad" },
      fields: { targeted: 4920, extracted: 4920, last_attack: "atk_8af781daef2d" },
    },
    "green:client_03": { title: "Acme Freight", fields: { risk: 12, paid: 184200 } },
  }}
/>
```

Values may be numbers or strings; numbers are formatted by the row's kind (`money` → `$4,920`, `percent` → `83%`,
`int`, `text`, `mono`). `status.tone` is `ok | warn | bad | idle`.

## Field keys

**Red** (fraudster)

| section | keys |
|---|---|
| Scheme | `scheme_id`, `expected_impact`, `params` |
| This episode | `attempts`, `targeted`, `extracted`, `caught`, `latency`, `last_attack` |
| Runtime | `model`, `credits`, `turn` |

**Blue** (guard)

| section | keys |
|---|---|
| Rule | `rule_id`, `severity`, `policy`, `mode` |
| Verdicts this episode | `fired`, `blocks`, `escalations`, `blocked_amount`, `confidence`, `last_reason` |
| Scorecard | `true_blocks`, `false_blocks` (need `origin`, from `/fe/episodes/{ep}/verdicts/rules`; left as placeholders on purpose) |
| Blue agent runtime | `model`, `credits`, `turn` |

**Green** (client)

| section | keys |
|---|---|
| Counterparty | `name`, `category`, `ein`, `bank`, `created` |
| Books | `risk`, `paid`, `invoices`, `blocked` |
| Exposure this episode | `targeted`, `at_risk`, `lost` |
| Green agent runtime | `model`, `credits`, `turn` |

`ein`, `bank`, `true_blocks` and `false_blocks` are never filled from the live stream: they need operator-only endpoints,
and `origin` is ground truth the audience must not see during a live run (`frontend/AGENTS.md`). Pass them through
`agentDetails` for the reveal.

### Runtime rows (every team)

A figure speaks for its team's agent, so each dossier ends with that agent's runtime (`lib/arena/runtime.ts`):

- **Droid model**: from `GET /api/bf/health` → `agents.<team>.{model, droid_ok, dry_run}`, fetched while a dossier is open
  (shared, kept 30 s; never in `NEXT_PUBLIC_MOCK=true`). A `dry_run` agent shows **keyless (DRY_RUN)**, whatever model is
  configured, because it never calls one (on prod today: green). `droid_ok: false` on a keyed agent shows
  `<model> · Droid unavailable`. No health answer → the usual placeholder naming the source.
- **Factory credits (episode)**: the sum of the team's `turn.ended → factory_credits` in the reducer state, with today's share.
  A keyless agent's turns carry `null` and show `0 · keyless (DRY_RUN), n turns`; without health it says `none reported`.
- **Last turn summary**: the team's newest `turn.ended → summary`.

## Adding a field

Add an `f("key", "Label", value, "source", kind)` entry in the matching `redDetails` / `blueDetails` / `greenDetails`
function in `details.ts`. It shows as a placeholder until the value is defined. `lib/arena/director.test.ts` has the
patterns for testing derived values.

## Styling

`app/arena.css`, section "agent dossier". The panel is a right-docked glass card on desktop and a bottom sheet under
760 px. Tone colour comes from `.tone-red | .tone-blue | .tone-green` (`--tone`).
