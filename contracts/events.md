# Events contract

Every event has this envelope. `payload` shape depends on `type`. Frontend derives all UI state
from the ordered stream of these; it never queries ledger tables.

```json
{ "id": 12345, "ts": "2026-10-25T14:03:11.221Z", "episode_id": "ep_...", "day": 4,
  "type": "gate.verdict", "agent": "blue", "payload": {} }
```

- `id` is a monotonically increasing integer per deployment (DB serial). Clients catch up with
  `GET /api/events?episode_id=&after_id=` (operator token only; agents get 403 — agents emit
  events, they never read them).
- `agent` is `red | green | blue | battlefield | human`.
- Agents may emit the three `agent.*` types and any `x.<area>.<name>` custom type via `POST /api/events`. Battlefield emits the rest. `x.*` events are team-defined, need no contracts change, and the frontend keeps them verbatim in `state.custom`.
- Payload fields marked `?` are optional. Money is a JSON number (dollars, 2dp).

| type | emitted by | payload |
|---|---|---|
| `episode.started` | battlefield | `{controller_mode, days, seed}` |
| `episode.ended` | battlefield | `{final_score: Score}` |
| `episode.paused` / `episode.resumed` | battlefield | `{}` |
| `controller.changed` | battlefield | `{from, to}` |
| `day.started` | battlefield | `{day, legit_injected: {invoices, purchase_orders, expenses, bank_lines, vendor_changes, new_vendors}}` — `vendor_changes`/`new_vendors` count legit bank-detail changes and new vendors (false-positive bait) |
| `day.ended` | battlefield | `{day}` |
| `turn.started` | battlefield | `{agent}` |
| `turn.ended` | battlefield | `{agent, ok, summary?, duration_sec, factory_credits?}` |
| `attack.launched` | battlefield | `{attack_id, scheme_id, display_name, story, target_amount}` |
| `attack.outcome` | battlefield | `{attack_id, scheme_id, outcome, amount_extracted, detected_day?}` |
| `agent.thinking` | agent | `{text}` — a delta; UI concatenates per `(agent, day)` |
| `agent.tool_call` | agent | `{tool, args, tool_use_id}` |
| `agent.tool_result` | agent | `{tool_use_id, ok, summary}` |
| `ledger.mutation` | battlefield | `{agent, action, entity_type, entity_id, amount?, verdict_id?}` |
| `gate.verdict` | battlefield | `{verdict_id, agent, action, entity_type?, entity_id?, amount?, verdict, reason, confidence?, rules_fired: string[], enforced}` |
| `escalation.opened` | battlefield | `{escalation_id, verdict_id, action, entity_type?, entity_id?, amount?, reason, expires_at}` |
| `escalation.resolved` | battlefield | `{escalation_id, decision: "approve"\|"block"\|"timeout", by}` |
| `flag.raised` | battlefield | `{flag_id, entity_type, entity_id, severity, reason}` |
| `vendor.frozen` / `vendor.unfrozen` | battlefield | `{vendor_id, reason?}` |
| `report.posted` | battlefield | `{report_id, day}` (fetch body via `GET /api/reports/{id}`) |
| `score.updated` | battlefield | `Score` (below) |
| `error` | battlefield | `{where, message}` — non-fatal problems the UI may surface. Documented cases below |
| `generation.started` | battlefield | `{lineage_id, generation, seed, playbook_versions: {red, green, blue}}` — lineage episodes only |
| `generation.ended` | battlefield | `{lineage_id, generation, score: Score}` |
| `playbook.updated` | battlefield | `{agent, version, parent_version, generation, source: "turn"\|"reflect"\|"operator", rationale}` — content via `GET /api/fe/lineages/{id}/timeline` |
| `debrief.delivered` | battlefield | `{agent, day, revealed_attacks, new_items, window_days}` — counts only, never the items. `revealed_attacks` = distinct attacks the agent's items belong to (for green: the attacks behind its `fraud` items) |
| `lineage.paused` / `lineage.resumed` | battlefield | `{lineage_id, generation}` |
| `x.<area>.<name>` | anyone | team-defined; payload is whatever the team says it is (document it in your AGENTS.md) |

`error` documented cases (`where` values code may rely on; others are free-form):

| `where` | `message` | when / effect |
|---|---|---|
| `credit_guard` | `"episode paused at <n> credits (limit <m>)"` | `MAX_CREDITS_PER_EPISODE > 0` and the episode's summed `turn.ended.factory_credits` (missing/`null` counts as 0, e.g. `DRY_RUN`) reaches the limit after a turn. Battlefield emits the `error`, then pauses the episode and emits `episode.paused` (if the episode is already paused, e.g. during a manual `step`, only the `error` is emitted). It resumes only by an explicit `POST /api/episodes/{id}/resume`; it is never auto-resumed. |
| `credit_guard` | `"lineage paused at <n> credits (limit <m>)"` | Lineage `config.max_credits > 0` and the lineage's summed credits (every generation's `turn.ended.factory_credits` plus `/reflect` usage) reach it. Emitted into the current generation's episode, followed by `lineage.paused` and `episode.paused` (when an episode is running). Resumes only by `POST /api/lineages/{id}/resume`. |

`Score`:
```json
{ "dollars_extracted": 0, "dollars_blocked": 0, "false_positive_cost": 0,
  "detection_latency_days": null, "attacks_launched": 0, "attacks_caught": 0,
  "legit_blocked": 0, "legit_processed": 0 }
```

## Ordering guarantees

Within an episode, events are emitted in causal order: `day.started` → `turn.started(red)` →
red's `agent.*` and `attack.launched` → `turn.ended(red)` → `turn.started(green)` → green's
`agent.*`, `gate.verdict`, `ledger.mutation`, `escalation.*` → `turn.ended(green)` →
`turn.started(blue)` → blue's `agent.*`, `flag.raised`, `vendor.frozen`, `report.posted` →
`turn.ended(blue)` → `attack.outcome`* → `score.updated` → `day.ended`.

Lineage episodes add, in this order:
- at the start of a generation's episode (day 0, before anything else): one `playbook.updated`
  (`source: "reflect"`) per agent whose reflection on the previous generation produced a new
  version → `generation.started` → `episode.started`;
- a `playbook.updated` (`source: "turn"`) inside the writing agent's turn, among its `agent.*` events;
- at the end of each day except the last: … `score.updated` → `debrief.delivered`* → `day.ended` (the last day
  has no next turn, so it emits no `debrief.delivered` and writes no `debriefs` row; that generation's
  truth reaches agents only through the after-action review);
- after the last day: `episode.ended` → `generation.ended`.

So a viewer of the real-time demo episode (the lineage's next generation) sees the agents arrive
with their evolved playbooks before day 0 starts.

## Fixture format

A recorded episode is a `.jsonl` file, one event per line, in `id` order. `make record EP=<id>`
produces one; the frontend mock and `make replay` consume it. A server-side replay re-emits each
event under a new `replay_*` episode with fresh `id`/`ts` (original type, agent, day, payload); the
envelope carries no `replay` flag, so clients dedupe and order by `id` as for any episode.
