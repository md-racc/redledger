# Agent service contract

Each of `red`, `green`, `blue` is an HTTP service that battlefield drives. Battlefield is the only
caller. All requests carry `Authorization: Bearer $AGENT_TOKEN`.

## Tokens

| Token | Who holds it | What it authorizes |
|---|---|---|
| `AGENT_TOKEN` | battlefield, red, green, blue containers | Every Ledger API request carrying `X-Agent`; battlefield → agent `/turn` `/gate` `/audit` `/schemes` `/reflect` (agent `/health` is unauthenticated) |
| `OPERATOR_TOKEN` | battlefield, frontend **server** (Next route handler), Makefile/curl, the owner | Every Ledger API request without `X-Agent`: control plane (`/episodes*`, `/escalations*`, `/replays*`, `/schemes`, `/health`, `/attacks/all`), `/fe/*` incl. `/fe/query`, `GET /events`, `/inputs`, `POST /ws/ticket`, `/ws?token=` (curl/debug) |
| WS ticket | browser, ≤60 s lifetime, single use | One `/ws` connection, for one episode (or `*`). Minted by `POST /api/ws/ticket` with `OPERATOR_TOKEN` |
| none | anyone | `battlefield/extensions/fe_*` routes deliberately marked public |

Rules (battlefield enforces; see `ledger-api.yaml` per-route `security`):
- A request with `X-Agent` must present `AGENT_TOKEN`. `OPERATOR_TOKEN` + `X-Agent` → 401.
- A request without `X-Agent` must present `OPERATOR_TOKEN`. `AGENT_TOKEN` without `X-Agent` → 401.
- A correctly authenticated agent on a route its role may not call → 403. `GET /api/events` is
  operator-only: agents emit events, they never read them.
- Agent services accept only `AGENT_TOKEN` on `/turn` `/gate` `/audit` `/schemes` `/reflect` → else 401.
- Transition: when `AGENT_TOKEN` / `OPERATOR_TOKEN` is unset, each falls back to the legacy
  `INTERNAL_TOKEN`; battlefield logs a warning when the two resolved values are equal.
  `agentkit.AgentSettings.internal_token` keeps its name and reads `AGENT_TOKEN` first, then
  `INTERNAL_TOKEN`, so agent code needs no change.
- The browser never holds `AGENT_TOKEN` or `OPERATOR_TOKEN`; no token goes in a `NEXT_PUBLIC_*` var.

## Common

```
GET  /health
  → 200 { "ok": true, "agent": "red", "model": "…", "droid_ok": true, "dry_run": false }

POST /turn
  { "episode_id": "ep_…", "day": 3, "controller_mode": "enforce",
    "options": { … agent-specific … } }
  → 200 { "ok": true, "summary": "…", "duration_sec": 41.2,
          "usage": { "factory_credits": 1.2, "input_tokens": …, "output_tokens": … } | null }
  → 200 { "ok": false, "summary": "why", … }     # agent-level failure; episode continues
```

`options.inputs` is always present: a list of `{id, source, payload}` left for this agent via
`POST /api/inputs` since its last turn (judge nudges, crowd page, another agent). Agents may
ignore it; interesting agents won't. Blue's `/audit` receives the same as `inputs`.

Rules:
- `/turn` is synchronous. Return within `TURN_TIMEOUT_SEC` (battlefield default 180). Battlefield
  cancels the HTTP call at the deadline and emits `turn.ended {ok:false}`; the episode continues.
- Battlefield never overlaps `/turn` calls to the same agent.
- During a turn the agent narrates via `POST battlefield/api/events` using `agent.thinking`,
  `agent.tool_call`, `agent.tool_result` only.
- All ledger reads/writes go through `agentkit.LedgerClient` with headers
  `X-Agent`, `X-Episode`, `X-Day`, `X-Tool-Use-Id`.
- Under `DRY_RUN=true` the agent must complete `/turn` with no Droid or LLM calls and still make
  a plausible sequence of ledger calls (so battlefield/frontend can be exercised end to end).

## Red

```
GET /schemes
  → 200 [ { "id": "ghost_vendor", "display_name": "Ghost Vendor", "story": "…",
            "params_schema": { JSON Schema }, "expected_impact": { "min": 1000, "max": 15000 } } ]
```
`/turn` options: `{ "scheme_id"?: str, "params"?: {} }`. If present, red must run that scheme.
Scheme ids are not a fixed list: an evolved scheme red composes from its playbook is listed by
`/schemes` and declared as `evolved:<slug>` like any other (see Lineages below).
Red must `POST /api/attacks` to declare each attack **before** executing it, and may
`PATCH /api/attacks/{id}` with notes. Battlefield computes `outcome` itself.

## Green

`/turn` options: `{}`. Green works the AP queue: match → approve → pay, resolve vendor changes,
approve/pay expenses (automatic GL posting is deferred until a balanced-journal contract exists).
Green never calls blue.

Gated actions are **prepared** before they run (`contracts/ledger-api.yaml` `POST /preparations`):
- Green's permission handler maps the requested tool + args to `{action, entity_id?, args}` and
  calls `POST /api/preparations` with the call's SDK `tool_use_id` as `X-Tool-Use-Id`. Battlefield
  validates, assembles context, asks blue, persists the verdict, marks an enforced block, holds an
  enforced escalation, and answers `200 Preparation` (also for a block).
- `effective: allow` → `PROCEED_ONCE`. `effective: block` → `CANCEL` with the stored reason.
- Prepare failures, by the turn's `controller_mode`:
  - `404`, `409 invalid_state`, `422` (unknown action / invalid body) → `CANCEL` with cause
    `invalid_state`, in every mode.
  - `409` idempotency key conflict and `409 no active turn for this agent` → `CANCEL` with cause
    `integration_failure`, in every mode (the call can never succeed under this key or turn).
  - `401`/`403`/`5xx`/timeout/network/malformed body → `PROCEED` in `off` and `shadow` (the gated
    route then gates inline) and `CANCEL` with cause `integration_failure` in `enforce`.
  - `200 effective: block` → `CANCEL` with cause `control_hold`, or `escalation_timeout` when
    `decided_by` is `timeout`.
- Cancel comments and green's `agent.tool_result` summary carry a `cause`: `control_hold`,
  `escalation_timeout`, `integration_failure` or `invalid_state`, so a fraud hold and an
  integration failure are never conflated.
- The tool then calls the gated route with the same `X-Tool-Use-Id`; the route consumes the
  preparation without a second gate call and stays the enforcement point. No automatic retries:
  a `409 PreparationRejected` goes back to the model as a tool error; a new tool call gets a new id.
- Without a preparation (DRY_RUN, mock agents, any caller that skips it) the gated route gates
  inline exactly as before.

**Identity.** Live Droid writes from green and blue use only SDK-reported tool_use_ids (permission
request or stream); a tool call the SDK reported no unique id for is not executed (refused, never
given a generated id). Red stays best-effort until its owner opts in. DRY_RUN and non-Droid calls
use UUID4.

## Blue

```
POST /gate
  { "idempotency_key": "…", "episode_id": "ep_…", "day": 3, "controller_mode": "enforce",
    "agent": "green", "action": "invoices.pay",
    "entity_type": "invoice", "entity_id": "inv_…", "amount": 4920.00,
    "args": { … route body … },
    "context": { "invoice": {...}, "vendor": {...}, "po": {...}|null,
                 "vendor_recent_changes": [...], "vendor_paid_invoices": [...] } }
  → 200 { "verdict": "allow"|"block"|"escalate", "reason": "…", "confidence": 0.0-1.0,
          "rules_fired": ["vendor_age_lt_7d", …], "latency_ms": 212 }

POST /audit
  { "episode_id": "ep_…", "day": 3, "inputs": [ … ], "lineage"?: { … }, "debrief"?: { … } }
  → 200 { "ok": true, "flags_raised": 2, "report_posted": true }
```
Rules:
- `/gate` must answer within `GATE_TIMEOUT_SEC` (default 8). On timeout battlefield uses
  `allow` in `shadow` and `escalate` in `enforce`.
- `/gate` requests in a lineage episode carry `"playbook_version": <int>` (blue's latest; absent
  otherwise), so blue can cache learned rules by version and refresh them with `GET /api/playbook`
  (reads are allowed outside turns).
- `/gate` is called only by battlefield (at preparation, or inline on an unprepared gated route).
  It is idempotent on `idempotency_key` for 120 s (same key → same verdict, no re-evaluation).
- A key is bound to the action it was first judged for: (action, entity_type, entity_id, amount);
  for `gl.post`, the posted fields. Battlefield answers the same key on a *different* action with
  `409 {"error": "idempotency key reused for a different action", "verdict_id": …}`, audited, and
  never replays the earlier verdict. Agents derive keys from the Droid `tool_use_id`: the first
  ledger write of a tool call uses it as-is, the n-th uses `<tool_use_id>:<n>`
  (`agentkit.LedgerClient` does this). A preparation is keyed by the same `tool_use_id` as that
  call's first ledger write.
- `context` is assembled by battlefield so blue does not need to make ledger reads inside the gate;
  blue may still read via `LedgerClient` if it wants more.
- `/audit` may read anything (including `/api/audit_log`) and may `POST /api/flags`,
  `POST /api/vendors/{id}/freeze`, `POST /api/reports`.

## Lineages: playbooks, debriefs, reflection

A lineage is a chain of episodes (generations) whose agents carry versioned playbooks forward
(`docs/EVOLUTION-DESIGN.md`). Everything below applies only to episodes with a `lineage_id`; plain
episodes are unchanged and reveal nothing.

Lineage episodes add two fields: inside `options` on `/turn` (red, green), and top-level on
blue's `/audit` (next to `inputs`):

```
"lineage": { "id": "ln_…", "generation": 2, "playbook_version": 7 }
"debrief": { "day": 4, "window_days": 3, "items": [ … ] }   # absent on day 0 and when reveal_days = 0
```

`debrief` is built after day `day`'s scoring and delivered on the next turn. It lists items
*resolved* on the last `window_days` completed days (a sliding window: an item reappears until it
leaves the window; `"new": true` on its first appearance). Item shapes, by agent:

| agent | item `kind` | fields |
|---|---|---|
| red | `attack` | `attack_id, scheme_id, day_launched, resolved_day, outcome, amount_extracted, detected_day, new, controls: [{kind: "verdict", day, action, verdict, rules_fired, reason} \| {kind: "flag", day, severity, reason} \| {kind: "freeze", day, vendor_id, reason}]` — its own attacks and the controls they ran into |
| blue | `attack` | `attack_id, scheme_id, display_name, day_launched, resolved_day, outcome, amount_extracted, detected_day, new, entities: [{entity_type, entity_id, amount?}], caught_by: [{kind: "verdict"\|"flag"\|"freeze", id, day, rules_fired?}]` — every resolved red attack; `caught_by: []` = missed |
| blue | `false_positive` | **after-action review only, never in a daily debrief** — `entity_type, entity_id, amount?, day, by: {kind: "verdict"\|"flag"\|"freeze", id, rules_fired?}` — a legit item blue blocked, escalated, flagged or froze |
| green | `fraud` | `entity_type: "invoice"\|"expense"\|"vendor_change", entity_id, amount?, field?, green_action, outcome: "paid"\|"approved"\|"blocked"\|"rejected", day, new` — an item of a resolved red attack on which green actually took a gated action (`green_action` is that action; never inferred). `approved` = green approved it and it was neither paid nor stopped (for a `vendor_change`: the change was applied; `field` names it, `amount` is absent). A live approved bank swap is unresolved, so it appears only in the after-action review |
| green | `legit_blocked` | **after-action review only, never in a daily debrief** — `entity_type, entity_id, amount?, action, verdict_id, day` — green's action on a legit item that the gate blocked |

Information policy (amends `AGENTS.md` invariant 4 for lineage episodes only):
- Daily debriefs reveal **only resolved red attacks**, never legit items: a list of legit items an
  agent blocked or froze would let it infer that the unlisted ones are red from unresolved attacks.
  Legit items (`false_positive`, `legit_blocked`) appear only in the after-action review.
- **Resolved** = `failed`, or entities and none pending. An approved red bank-detail change that is
  still live (no later approved change of that field on the vendor) is pending: a working bank swap
  is never revealed before the episode ends. Pending red items are never revealed mid-episode.
- An attack is **frozen** once revealed (`attacks.revealed_day`): its outcome, detection and score
  contribution (extracted, blocked, frozen vendor) are evaluated as of `revealed_day`, so later blocks,
  flags or freezes on it change nothing. `controls` / `caught_by` list only actions on or before
  `revealed_day`.
- Vendor-change attribution is always computed over all of an episode's attacks; revealing or
  freezing some attacks never re-attributes another attack's changes.
- No agent ever sees another agent's playbook. Opponents' strategy is visible only as behaviour.
- Every disclosure is stored in `debriefs` exactly as delivered (operator-readable).
- `origin` itself still never appears in any field; disclosures say "attack" / "legit", per item.

**Playbook routes** (Ledger API; `LedgerClient.get_playbook/put_playbook/playbook_history`):
`GET /api/playbook`, `PUT /api/playbook {content, rationale, base_version}` (active turn only;
409 on a stale `base_version`, on an `X-Tool-Use-Id` reused with a different body, or outside a turn; 413 over 64 KiB), `GET /api/playbook/history`.

**`POST /reflect`** (every agent). Called by battlefield after a generation's episode finished,
once per agent, sequentially:

```
POST /reflect
  { "lineage_id": "ln_…", "generation": 2, "episode_id": "ep_…",
    "review": { "generation": 2, "episode_id": "ep_…", "seed": 44, "score": Score,
                "items": [ … same kinds as the debrief plus the AAR-only kinds, covering every
                          attack of the generation whether or not it resolved (the episode
                          has ended, so nothing is still in play; an unresolved attack's
                          outcome is as scored at the end), green's fraud items for every
                          red item it acted on, and blue's false_positive / green's
                          legit_blocked items for every legit item concerned … ],
                "rules": [ { "rule_id": "…", "fired": 9, "on_red": 6, "on_legit": 3 } ],   # blue only
                "history": [ { "generation": 1, "seed": 43, "score": Score,
                               "summary": { … per-agent counts by scheme / rule / outcome … } } ] },
    "playbook": { "version": 7, "parent_version": 6, "generation": 2, "episode_id": "ep_…", "day": 4,
                  "source": "turn", "content": { … }, "rationale": "…" } }
  → 200 { "ok": true, "playbook": { … new content … } | null, "rationale": "…",
          "usage": { "factory_credits": …, … } | null }
```

Rules:
- Return within `TURN_TIMEOUT_SEC`. Timeout, error or `ok: false` → the playbook is kept.
- `playbook: null` keeps the current version. Otherwise battlefield writes the next version with
  `source: "reflect"` and the given `rationale`; the agent does not call `PUT /api/playbook`
  during reflect (there is no active turn, so it would get 409) and makes no ledger writes.
- `history` holds the `reveal_generations - 1` generations before this one (oldest first);
  `reveal_generations: 0` → no `/reflect` call at all.
- Narration via `agent.thinking` is allowed (episode = the finished generation, `day` = its `days`).
- Under `DRY_RUN=true` the agent makes no model calls; agentkit's default returns
  `{ok: true, playbook: null, rationale: "dry run"}`.

## Extension points available to every agent

- `GET/PUT /api/state/{key}` — per-agent JSON memory across turns (`LedgerClient.get_state/put_state`).
- `POST /api/inputs` — message another agent's next turn (`LedgerClient.post_input(target, payload)`).
- `POST /api/events` with type `x.<agent>.<name>` — custom events (`EventEmitter.custom(name, payload)`).
- `battlefield/extensions/<agent>_*.py` + `contracts/ext/<agent>/*.sql` — your own routes and tables (README §16).

## Gated actions (what blue will be asked about)

`invoices.match`, `invoices.approve`, `invoices.reject`, `invoices.pay`,
`vendor_changes.approve`, `vendor_changes.reject`, `expenses.approve`, `expenses.pay`,
`gl.post`.
