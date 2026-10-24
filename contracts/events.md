# Events contract

Every event has this envelope. `payload` shape depends on `type`. Frontend derives all UI state
from the ordered stream of these; it never queries ledger tables.

```json
{ "id": 12345, "ts": "2026-10-25T14:03:11.221Z", "episode_id": "ep_...", "day": 4,
  "type": "gate.verdict", "agent": "blue", "payload": {} }
```

- `id` is a monotonically increasing integer per deployment (DB serial). Clients catch up with
  `GET /api/events?episode_id=&after_id=`.
- `agent` is `red | green | blue | battlefield | human`.
- Agents may emit the three `agent.*` types and any `x.<area>.<name>` custom type via `POST /api/events`. Battlefield emits the rest. `x.*` events are team-defined, need no contracts change, and the frontend keeps them verbatim in `state.custom`.
- Payload fields marked `?` are optional. Money is a JSON number (dollars, 2dp).

| type | emitted by | payload |
|---|---|---|
| `episode.started` | battlefield | `{controller_mode, days, seed}` |
| `episode.ended` | battlefield | `{final_score: Score}` |
| `episode.paused` / `episode.resumed` | battlefield | `{}` |
| `controller.changed` | battlefield | `{from, to}` |
| `day.started` | battlefield | `{day, legit_injected: {invoices, purchase_orders, expenses, bank_lines}}` |
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
| `error` | battlefield | `{where, message}` — non-fatal problems the UI may surface |
| `x.<area>.<name>` | anyone | team-defined; payload is whatever the team says it is (document it in your AGENTS.md) |

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

## Fixture format

A recorded episode is a `.jsonl` file, one event per line, in `id` order. `make record EP=<id>`
produces one; the frontend mock and `make replay` consume it.
