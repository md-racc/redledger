# Agent service contract

Each of `red`, `green`, `blue` is an HTTP service that battlefield drives. Battlefield is the only
caller. All requests carry `Authorization: Bearer $INTERNAL_TOKEN`.

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
Red must `POST /api/attacks` to declare each attack **before** executing it, and may
`PATCH /api/attacks/{id}` with notes. Battlefield computes `outcome` itself.

## Green

`/turn` options: `{}`. Green works the AP queue: match → approve → pay, resolve vendor changes,
approve/pay expenses, post GL entries for what it paid. Green's Droid permission handler mirrors
`POST blue/gate` with the same `idempotency_key` (= `X-Tool-Use-Id`) and returns `CANCEL` when
the verdict is `block`; the ledger-side gate is still the enforcement point.

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
  { "episode_id": "ep_…", "day": 3 }
  → 200 { "ok": true, "flags_raised": 2, "report_posted": true }
```
Rules:
- `/gate` must answer within `GATE_TIMEOUT_SEC` (default 8). On timeout battlefield uses
  `allow` in `shadow` and `escalate` in `enforce`.
- `/gate` is idempotent on `idempotency_key` for 120 s (same key → same verdict, no re-evaluation).
- `context` is assembled by battlefield so blue does not need to make ledger reads inside the gate;
  blue may still read via `LedgerClient` if it wants more.
- `/audit` may read anything (including `/api/audit_log`) and may `POST /api/flags`,
  `POST /api/vendors/{id}/freeze`, `POST /api/reports`.

## Extension points available to every agent

- `GET/PUT /api/state/{key}` — per-agent JSON memory across turns (`LedgerClient.get_state/put_state`).
- `POST /api/inputs` — message another agent's next turn (`LedgerClient.post_input(target, payload)`).
- `POST /api/events` with type `x.<agent>.<name>` — custom events (`EventEmitter.custom(name, payload)`).
- `battlefield/extensions/<agent>_*.py` + `contracts/ext/<agent>/*.sql` — your own routes and tables (README §16).

## Gated actions (what blue will be asked about)

`invoices.match`, `invoices.approve`, `invoices.reject`, `invoices.pay`,
`vendor_changes.approve`, `vendor_changes.reject`, `expenses.approve`, `expenses.pay`,
`gl.post`.
