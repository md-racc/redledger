# Evolution design: lineages, playbooks, debriefs, headless generations (Ad)

Status: **decisions accepted by Ad 2026-10-24** (§10); contracts not yet edited. Baseline: main
`0e62024`. Companion to [`AD-INTEGRATION-DESIGN.md`](AD-INTEGRATION-DESIGN.md) (packages A/B),
which this does not replace. Ad scaffolds battlefield/agentkit/contracts; what each agent *learns*
is Al's (red), M's (green, blue) and R's (frontend) to build on top.

## 0. Summary

- A **lineage** is a chain of episodes, one per **generation**. Between generations every agent
  **reflects** on an after-action review and writes a new version of its **playbook**. During an
  episode agents may also rewrite their playbook after any tick. Every version is stored with its
  parent, generation, day and rationale: that history *is* the map of how the agents develop.
- Agents get a **debrief** each day (and an after-action review between generations) containing
  what they are allowed to know, including **a sliding window of the opponent's recent behaviour**
  (§3). Outside a lineage, nothing changes: `origin` stays fully secret.
- Generations run **headless** (no UI, no day pause, automatic escalation policy) via
  `make evolve`. The live demo stays real-time: it is simply generation N+1 of a lineage, started
  by hand, with agents carrying evolved playbooks.
- Each generation exports a **log bundle**; `make evolution-report` turns a lineage into a
  deterministic report (scores, tactic mix, rules learned, who beat whom, playbook diffs) with an
  optional LLM narrative. `/fe/lineages/*` serves the same data to R.
- "New interactions" means **new tactics composed from the fixed Ledger API**, not
  runtime-generated endpoints (§5). A genuinely new primitive is a small contracts PR.
- Everything runs under `DRY_RUN=true`: agentkit's default `reflect()` and the mock agents'
  deterministic adaptation make `make mock-agents && make evolve GENS=3` produce a non-trivial
  report with no keys. Real generations need the live hold lifted (§8).

## 1. Concepts

| Term | Meaning |
|---|---|
| Lineage | `{id, name, base_seed, config, status, current_generation}`. Owns playbooks and generations |
| Generation `g` | One episode with `episodes.lineage_id`, `episodes.generation = g`. Seed `base_seed + g` (§3.4) |
| Playbook | Per (lineage, agent) versioned JSON document. Content is opaque to battlefield and owned by the agent's team. Versions are immutable |
| Debrief | Per (episode, day, agent) disclosure delivered as `options.debrief` on that agent's next turn (`debrief` on blue `/audit`) |
| After-action review (AAR) | Per (lineage, generation, agent) disclosure delivered to `POST /reflect` once the generation's episode finished |
| Reveal window | `reveal_days` (default 3) completed days inside an episode, `reveal_generations` (default 2) generations across a lineage |

Lineage `config` (JSONB, validated by battlefield; no new env vars):

```json
{ "generations": 3, "days": 6, "controller_mode": "enforce",
  "reveal_days": 3, "reveal_generations": 2,
  "headless": { "day_pause_sec": 0, "escalation_policy": "block", "escalation_timeout_sec": 5 },
  "max_credits": 0 }
```

## 2. Lifecycle

```
POST /lineages {config}                         → lineage created, playbooks v0 = {} per agent (source=seed)
POST /lineages/{id}/start                       → lineage task:
  for g in 1..generations:
    create episode(lineage, g, seed = base_seed + g); emit generation.started
    run every day as today, plus after score.end_of_day:
      build debrief(agent) for each agent → persisted → options.debrief on the next turn
      (agents may PUT /playbook inside their turn → playbook.updated)
    episode finished → emit generation.ended {score}
    if g < generations or a demo follows:
      for agent in red, green, blue (sequential, TURN_TIMEOUT_SEC each):
        AAR(agent) persisted → POST agent/reflect → new playbook version (source=reflect)
POST /episodes {lineage_id, controller_mode, days}  → the real-time demo: generation N+1, started by hand
```

- The lineage loop is a battlefield task like the episode loop (`app/orchestrator/lineage.py`),
  one lineage at a time per stack. Generations are sequential because each agent service serves
  one turn at a time (`agentkit/agentkit/server.py:51`); speed is bounded by model latency, not by
  the clock. Parallel lineages would need a second compose project; out of scope.
- Restart recovery mirrors episodes (#52): a `running` lineage becomes `paused`; its episode is
  paused by the existing recovery; `POST /lineages/{id}/resume` continues at the same generation.
  A reflection interrupted by a restart is re-run (reflect is read-only, so idempotent enough).
- Credits: `MAX_CREDITS_PER_EPISODE` still applies per generation; `config.max_credits` caps the
  lineage (turns + reflections) and pauses it with `error {where: "credit_guard"}`.
- Headless escalations: in a lineage episode with `headless` set, the gatekeeper uses
  `escalation_timeout_sec` from the lineage config and resolves by `escalation_policy`
  (`block` = today's timeout semantics, default). The demo episode (no `headless`) uses
  `ESCALATION_TIMEOUT_SEC` and a human as today.

## 3. Information policy (amends invariant 4)

Ad's decision: agents may see the last few rounds of the opponent's behaviour to recognise
patterns. Interpretation recorded here (correct it if wrong): a sliding window, both inside an
episode (the last `reveal_days` completed days) and across generations (the last
`reveal_generations` AARs). Outside a lineage episode nothing is revealed.

**Invariant 4, proposed wording:** *`origin` is secret during play. The only exception is
battlefield's debrief and after-action review in a lineage episode, which may reveal the ground
truth of **resolved** attacks after the day they resolved, within the lineage's reveal window,
and log every disclosure in `debriefs`. Never through any other field, route, error or event
visible to agents.*

### 3.1 What each agent sees

| | Debrief (daily, window `reveal_days`) | AAR (between generations, window `reveal_generations`) |
|---|---|---|
| **red** | its own resolved attacks: outcome, amount extracted, detected day, and the controls it ran into: `rules_fired` + reasons of verdicts on its entities, flags (severity, reason), freezes | the same for the whole generation + score; summaries of earlier generations in the window |
| **blue** | resolved red attacks: scheme id, display name, day launched, entities, amounts, outcome; which of its blocks/escalations/flags hit red and which hit legit items (precision), red attacks it missed | the same for the whole generation, plus every legit item it blocked/escalated, precision/recall per rule id, score |
| **green** | items it acted on that resolved as red (paid fraud) and legit items whose actions were blocked | the same for the whole generation + score |

Nobody sees an opponent's **playbook**: patterns come from behaviour only. Agents read only their
own playbook history (§4.2).

### 3.2 Only resolved attacks

An attack is **resolved** when it is `failed`, or it has entities and none is pending (the first
branch of `score.resolve_attacks`, `battlefield/app/scoring/score.py:161`). Pending, matched or
approved red items are never revealed mid-episode: otherwise the debrief would hand blue the
answer before the money moves. Unresolved attacks appear only in the AAR, after the episode ended.
Battlefield records `attacks.resolved_day` the first day it is resolved.

### 3.3 Revealed outcomes are frozen

`resolve_attacks` recomputes outcomes every day; a freeze or flag after the reveal would turn an
`extracted` attack into `partial` (`score.py:162`) and set `detected_day`, scoring hindsight as
detection. So when a debrief first reveals an attack battlefield sets `attacks.revealed_day`, and
`resolve_attacks` no longer updates attacks with `revealed_day` set. Learning still pays off on
*later* attacks, which is the point.

### 3.4 A fresh seed per generation

Legit traffic, including the false-positive bait vendors, is deterministic in the seed
(`legit_traffic.inject(episode_id, seed, day)`). With one seed across generations, an AAR that
lists legit items would let blue memorise "these vendors are fine" and the report would show
learning that is really overfitting. Generation `g` therefore uses `base_seed + g`, and the demo
episode a seed no generation used. The report states the seeds.

## 4. Contract changes (text for PR E1; not applied)

### 4.1 `contracts/schema.sql`

```sql
CREATE TABLE IF NOT EXISTS lineages (
  id                  TEXT PRIMARY KEY,
  name                TEXT NOT NULL DEFAULT '',
  base_seed           INTEGER NOT NULL,
  config              JSONB NOT NULL,
  status              TEXT NOT NULL DEFAULT 'created' CHECK (status IN ('created','running','paused','finished','failed')),
  current_generation  INTEGER NOT NULL DEFAULT 0,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at         TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS playbooks (
  id              BIGSERIAL PRIMARY KEY,
  lineage_id      TEXT NOT NULL REFERENCES lineages(id) ON DELETE CASCADE,
  agent           TEXT NOT NULL CHECK (agent IN ('red','green','blue')),
  version         INTEGER NOT NULL,           -- 0 = seed, then +1 per write
  parent_version  INTEGER,
  generation      INTEGER NOT NULL,           -- generation it was written in (reflect: the one it reflects on)
  episode_id      TEXT,                       -- NULL for seed/operator
  day             INTEGER,                    -- NULL for reflect/seed/operator
  source          TEXT NOT NULL CHECK (source IN ('seed','turn','reflect','operator')),
  content         JSONB NOT NULL,             -- opaque to battlefield; ≤ 64 KiB
  rationale       TEXT NOT NULL DEFAULT '',
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (lineage_id, agent, version)
);

-- Every disclosure of ground truth (debrief: day set; AAR: day NULL). What the agent was shown.
CREATE TABLE IF NOT EXISTS debriefs (
  id          BIGSERIAL PRIMARY KEY,
  lineage_id  TEXT NOT NULL REFERENCES lineages(id) ON DELETE CASCADE,
  generation  INTEGER NOT NULL,
  episode_id  TEXT NOT NULL,
  day         INTEGER,
  agent       TEXT NOT NULL,
  payload     JSONB NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE episodes ADD COLUMN IF NOT EXISTS lineage_id TEXT;
ALTER TABLE episodes ADD COLUMN IF NOT EXISTS generation INTEGER;
ALTER TABLE attacks  ADD COLUMN IF NOT EXISTS resolved_day INTEGER;
ALTER TABLE attacks  ADD COLUMN IF NOT EXISTS revealed_day INTEGER;
```

Diffs between playbook versions are computed at read time (report, `/fe`), not stored.

### 4.2 `contracts/ledger-api.yaml`

| Route | Who | Behaviour |
|---|---|---|
| `POST /lineages {name?, base_seed?, config}` | operator | 201 lineage + v0 playbooks; 422 on invalid config |
| `GET /lineages`, `GET /lineages/{id}` | operator | lineage + generations `[{generation, episode_id, seed, status, score}]` + latest playbook version per agent |
| `POST /lineages/{id}/start\|pause\|resume` | operator | like episodes; 409 if another lineage is running |
| `POST /episodes {…, lineage_id?}` | operator | with `lineage_id`: generation = current + 1, agents use the lineage's playbooks; seed must not be a seed the lineage used (422) |
| `GET /lineages/{id}/export` | operator | the §6 bundle as one JSON document (per generation: events, audit_log, verdicts, attacks, score, credits, debriefs, playbook versions) |
| `GET /playbook` | red, green, blue | the caller's latest version in the lineage of `X-Episode`: `{version, generation, content, rationale}`; 404 `{error:"not a lineage episode"}` outside lineages |
| `GET /playbook/history?limit=` | red, green, blue | the caller's own versions, newest first; never another agent's (no route takes an agent parameter) |
| `PUT /playbook {content, rationale, base_version}` | red, green, blue | write guard applies (active turn only, else 409 `no active turn`); 409 `{error:"stale base_version", latest}` on a lost race; 413 over 64 KiB; audited; emits `playbook.updated` |
| `GET /fe/lineages/{id}/timeline` | operator / frontend | playbook versions (with diffs), generation scores, debrief counts, ordered by time |
| `GET /fe/lineages/{id}/report` | operator / frontend | the report's JSON (§7) |

Agents cannot write ground truth anywhere and cannot read `debriefs` except as delivered.

### 4.3 `contracts/agent-service.md`

- `/turn` options gain, in lineage episodes only: `options.lineage {id, generation, playbook_version}`
  and `options.debrief {day, window_days, items: [...]}` (shape per agent, §3.1). Blue's `/audit`
  request gains the same as top-level `lineage` and `debrief`. Absent outside lineages.
- New on every agent:

```
POST /reflect
  { "lineage_id": "ln_…", "generation": 2, "episode_id": "ep_…",
    "review": { … AAR, §3.1 … }, "playbook": { "version": 7, "content": { … } } }
  → 200 { "ok": true, "playbook": { … new content … } | null, "rationale": "…", "usage": {…} | null }
```

  Within `TURN_TIMEOUT_SEC`. `playbook: null` = keep the current version. Battlefield writes the
  version (`source=reflect`); the agent never writes the ledger during reflect (no active turn, so
  the write guard 409s it anyway). Narration via `agent.thinking` is allowed with
  `day = episode days`. `DRY_RUN`: no model calls; agentkit's default returns `playbook: null`.
- Blue `/gate` (battlefield → blue) gains optional `playbook_version` so blue can cache learned
  rules by version and refresh with a read of `GET /playbook` (reads are allowed outside turns).

### 4.4 `contracts/events.md`

| Type | Emitter | Payload |
|---|---|---|
| `generation.started` | battlefield | `{lineage_id, generation, seed, playbook_versions: {red, green, blue}}` |
| `generation.ended` | battlefield | `{lineage_id, generation, score: Score}` |
| `playbook.updated` | battlefield | `{agent, version, parent_version, generation, source, rationale}` (content via `/fe/lineages/{id}/timeline`) |
| `debrief.delivered` | battlefield | `{agent, day, revealed_attacks: n, window_days}` (counts only) |
| `lineage.paused` / `error {where:"credit_guard"}` | battlefield | as for episodes |

Reflection-time events (`playbook.updated` with `source=reflect`) are emitted into the **next**
generation's episode before `episode.started` (day 0), so a viewer of the demo episode sees the
agents arrive with their evolved playbooks. Events stay operator-only.

### 4.5 `agentkit/agentkit/models.py`

`LineageInfo`, `Debrief`, `ReflectRequest`, `ReflectResponse`, `Playbook`; `TurnRequest` unchanged
(debrief rides in `options`); `EventType` gains the four types above.

## 5. Dynamic interactions without new endpoints

Runtime-generated battlefield routes would bypass the one enforcement point and are the easiest
way to leak `origin`, so what evolves is **tactics over fixed primitives**:

- **Red (Al):** schemes become data. A composed scheme is a playbook entry: ordered steps over the
  existing red tools with parameter rules, declared as an attack with `scheme_id = "evolved:<slug>"`.
  `SchemeBase` stays for the hand-written ones; a `ComposedScheme` executes entries. `GET /schemes`
  returns both, so judges can force evolved schemes. Scoring needs nothing: attacks are linked by
  `attack_id`, not by scheme.
- **Blue (M):** learned rules as data: a small declarative predicate format over the gate context
  (vendor age, amount vs threshold, bank-change recency, …) evaluated next to `blue/gate/rules.py`;
  `rules_fired` ids `learned:<slug>` so `/fe/verdicts/rules` and the report attribute catches.
- **Green (M):** procedures as data: per-action checklists green's prompt and workflow consult.
- **Optional phase 2, the mailroom (decision pending):** a mediated message channel in which red
  can social-engineer green ("our bank details changed") under a persona. Today an agent's
  `POST /inputs` stores `source = <agent>` (`battlefield/app/api/extension_points.py:72`), which
  names red; the mailroom would store a hidden origin and a persona, and legit traffic would send
  benign mail too so the channel is not a tell. Separate contracts PR if Ad wants it.

## 6. Log capture

`make lineage-export LN=<id>` writes `runs/<lineage>/gen-<g>/` (gitignored, outside fixtures):
`events.jsonl` (same format as `make record`), `audit_log.jsonl`, `verdicts.jsonl`,
`attacks.json`, `score.json`, `credits.json`, `debriefs.jsonl`, `playbooks/<agent>-v<n>.json`,
plus `lineage.json`. It reads `GET /lineages/{id}/export` with the operator token and runs the same
secret scan as `prod-record`. Container logs (`make logs > runs/…/compose.log`) are optional and
local only: battlefield's logs can contain `origin`, so they never reach a browser.

## 7. Evolution report

`make evolution-report LN=<id>` → `runs/<lineage>/report.md` + `report.json` (the same JSON
`/fe/lineages/{id}/report` serves). Deterministic sections, all from the database:

1. Run card: seeds, generations, days, controller mode, models, git SHA, credits per generation.
2. Score per generation: extracted, blocked, false-positive cost, detection latency, caught/launched.
3. Red tactic mix per generation (scheme id → launched, outcome, $), evolved schemes and their parent.
4. Blue rules: learned rules by generation, precision/recall per rule id, rules retired.
5. Who beat whom: red scheme × blue rule matrix (fired / missed), per generation.
6. Green: throughput, false positives it suffered, fraud it paid.
7. Playbook timeline per agent: versions, source, rationale, structural diff.
8. What each agent was shown (debrief/AAR counts), so the information policy is auditable.

Optional narrative: one LLM call over `report.json` when a key is configured; off by default and
never required. Under `DRY_RUN` the report is fully deterministic.

## 8. Speed, cost, environments

- Headless means `day_pause_sec 0`, no frontend, short escalation timeout. Wall clock per
  generation ≈ days × (red + green + blue turn latency); measure on the first live generation.
- Real evolution needs live agents: the live hold (D15 in the integration design) must lift and
  a lineage `max_credits` must be set. Until then everything is built and verified keyless:
  agentkit default `reflect()` keeps playbooks; `battlefield/mock_agents` implement `/reflect`
  with deterministic adaptation (mock red avoids schemes blocked twice in the window and repeats
  extracted ones; mock blue tightens its near-threshold band after a miss) so a mock lineage shows
  real tactic shifts.
- Green cannot evolve live until packages A/B land (green is DRY_RUN-only today).

## 9. Showing the backend is real (R, with backend support)

Strongest proof is interaction nobody could script: a judge forces an attack
(`POST /episodes/{id}/attack`), sends a nudge (`POST /inputs`) or resolves an escalation and
watches agents react within seconds. Already supported. On top:

- **Wire tap:** every Ledger API call as it happens (agent, action, status, latency, tool-use id)
  from `audit_log`: an `/api/fe` read with `after_id` polling (R may add `/api/fe` reads).
- **Raw thinking:** `agent.thinking` deltas unedited, with timestamps and model id.
- **Numbers that vary:** credits, tokens and latency per turn (`turn.ended`, `verdicts.latency_ms`).
- **Raw JSON toggle** on every card (event id, ts, payload).
- **Provenance strip:** git SHA, models, DRY_RUN vs live (`GET /health` already reports agents'
  `dry_run`), and an honest LIVE / REPLAY badge (replays are `replay_*` episodes).
- **Failures visible:** timeouts, `turn.ended {ok:false}`, `error` events.
- **Rules that did not fire**, with the values they checked: blue's `/gate/explain` exists; M
  decides what reaches `gate.verdict`.
- **Evolution view:** `/fe/lineages/{id}/timeline` as a playbook-version timeline.
- Never stream container logs to the browser (`origin`).

## 10. Decisions (Ad, 2026-10-24)

| # | Decision | Status |
|---|---|---|
| E-D1 | Ground truth may reach agents in lineages; **sliding window of the opponent's recent behaviour** inside an episode and across generations (§3). Interpretation of "last few rounds" recorded in §3 | Accepted |
| E-D2 | One generic, lineage-scoped, versioned playbook store; content owned by each team | Accepted |
| E-D3 | Build and verify keyless now; real generations wait for the live hold to lift, with a credit cap | Accepted |
| E-D4 | Order: integration-design docs PR → this doc → contracts E1 → battlefield/agentkit work alongside package A | Accepted |
| E-D5 | Only resolved attacks revealed mid-episode; revealed outcomes frozen; fresh seed per generation (§3.2–3.4) | Proposed (follows from E-D1; flag if not) |
| E-D6 | No agent sees an opponent's playbook | Proposed |
| E-D7 | Mailroom (§5) | Open, phase 2 |
| E-D8 | Defaults `reveal_days 3`, `reveal_generations 2`, training mode `enforce` | Proposed |

## 11. Implementation plan

| PR | Branch | Files (exclusive while open) | Tests | Needs |
|---|---|---|---|---|
| E0 | `docs/evolution-design` | this doc | — | — |
| E1 | `contracts/evolution` | `contracts/{schema.sql,ledger-api.yaml,agent-service.md,events.md,CHANGELOG.md}`, `agentkit/agentkit/models.py` | schema applies twice cleanly; frontend `gen:api` compiles | E0; reviewers Ad, Al, M, R. Serialised with integration PR1 (same files): E1 first |
| E2a | `battlefield/playbooks-debrief` | new `app/api/playbooks.py`, new `app/evolution/debrief.py`, `scoring/score.py` (resolved/revealed), `orchestrator/runner.py` (debrief hook), `main.py` (mount), tests | DB: playbook CRUD + stale 409 + guard 409 + 413; each agent's debrief contents per §3.1; unresolved never revealed; revealed outcome frozen; no disclosure outside lineages; every disclosure in `debriefs` | E1 |
| E2b | `battlefield/agentkit-reflect` | `agentkit/agentkit/{server,droid_agent,ledger_client}.py`, `agentkit/tests/*` | unit: `/reflect` route + auth, default `reflect()` → null, DRY_RUN no model calls, `get/put_playbook` | E1; parallel with E2a |
| E3 | `battlefield/lineage-runner` | new `app/orchestrator/lineage.py`, `api/control.py` (lineage routes, `lineage_id` on episodes), `mock_agents/server.py` (`/reflect` + adaptation), `Makefile` (`evolve`, `lineage-*`), `main.py` (recovery), tests; headless escalation hook in `gate/gatekeeper.py` **after integration 2a merges** (2a owns that file) | DB: 3-generation mock lineage end to end, seeds distinct, reflect versions written, restart → paused → resume, credit cap; `make mock-agents && make evolve GENS=3` | E2a, E2b |
| E4 | `battlefield/lineage-report` | `api/control.py` export route, new `scripts/evolution_report.py`, `api/frontend.py` (`/fe/lineages/*`), `Makefile` (`lineage-export`, `evolution-report`), `.gitignore` (`runs/`), tests | report from a mock lineage is deterministic (golden JSON); export secret scan | E3 |
| E5 | `docs/evolution-invariants` | `AGENTS.md` invariant 4, README §3/§7/§16 | — | E2a merged |
| T-red | `red/evolving-schemes` (Al) | `red/**` | keyless: composed scheme from playbook, `/reflect` | E2b |
| T-blue | `blue/learned-rules` (M) | `blue/**` | keyless: learned rule evaluation, `/reflect` | E2b |
| T-green | `green/procedures` (M) | `green/**` | keyless | E2b + packages A/B for live |
| T-fe | `frontend/ops-console` (R) | `frontend/**`, `battlefield/extensions/fe_*.py` | `NEXT_PUBLIC_MOCK=true` | wire tap now; lineage view after E4 |

File conflicts with the integration plan: E1 vs PR1 (contracts, serialised); E2a/E3 `main.py`
vs 2a (small hunks, merged sequentially, never edited concurrently); E3's gatekeeper hook waits
for 2a. Everything else is disjoint.

## 12. Briefs for teammates (paste after your directory's AGENTS.md block)

- **Al (red):** in lineage episodes your turn gets `options.lineage` and `options.debrief`
  (your resolved attacks + the controls they hit, last 3 days). Read your playbook with
  `ledger.get_playbook()`, write it with `ledger.put_playbook(content, rationale, base_version)`
  inside your turn. Implement `reflect(req)` (AAR → new playbook). Put evolved schemes in the
  playbook and declare them as `evolved:<slug>`. Keep DRY_RUN keyless.
- **M (blue, green):** blue gets `debrief` on `/audit`, `playbook_version` on `/gate`; learned
  rules as data with `learned:<slug>` ids; precision per rule arrives in the AAR. Green gets
  `options.debrief`; procedures as data. Implement `reflect()` for both.
- **R (frontend):** wire tap, raw JSON toggle, provenance strip, LIVE/REPLAY badge now (§9);
  lineage timeline and report from `/fe/lineages/{id}/timeline|report` after E4. Mock fixtures for
  both will ship with E4.
