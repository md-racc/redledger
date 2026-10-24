# Agents and events

The backend has three agents (red, green, blue). The arena shows what each is made of, as 30 figures in three groups.
The roster and its backend ids are in `lib/arena/roster.ts`. What each figure looks like (a distinct tell per scheme, an
emblem per rule, a trade per client) is in [agent-design.md](agent-design.md).

## The roster

### Red: 8 fraudsters (one per scheme)

Id = `red:<scheme_id>`, the string in `attack.launched.payload.scheme_id`.

| id | name | default story (README §8 / `red/schemes`) |
|---|---|---|
| `red:ghost_vendor` | Ghost Vendor | a brand-new vendor appears and immediately invoices for services never delivered |
| `red:bank_swap` | Bank Account Swap | a real vendor's bank details are "updated" right before a large invoice is paid |
| `red:duplicate_invoice` | Duplicate Invoice | a paid invoice is resubmitted with a new number and the amount off by a few cents |
| `red:threshold_split` | Threshold Splitting | one large job billed as several invoices just under the auto-approval line |
| `red:ghost_employee` | Ghost Employee | a payroll record with no HR trail collects a salary |
| `red:expense_inflation` | Expense Inflation | reimbursements creep above what was spent |
| `red:po_mismatch` | PO Mismatch | an invoice billed well above its purchase order |
| `red:amount_drift` | Amount Drift | a recurring vendor's invoices climb a little every month |

The first four stories are the ones in the mock catalog; the last four are placeholders until Al's scheme classes land.
Once `GET /schemes` answers, its `display_name` and `story` replace these.

### Blue: 10 guards (one per gate rule)

Id = `blue:<rule id>`, the strings in `gate.verdict.payload.rules_fired[]`.

| id | name | severity |
|---|---|---|
| `blue:vendor_age_lt_7d` | Young Vendor | 2 |
| `blue:near_threshold` | Near Threshold | 1 |
| `blue:duplicate_invoice` | Duplicate Check | 3 |
| `blue:recent_bank_change` | Bank Change Watch | 3 |
| `blue:bank_change_with_open_invoices` | Bank Swap Trap | 3 |
| `blue:no_po_from_po_vendor` | PO Discipline | 2 |
| `blue:over_po_amount` | PO Ceiling | 2 |
| `blue:recurring_drift` | Drift Sentinel | 1 |
| `blue:employee_bank_matches_vendor` | Payroll Match | 3 |
| `blue:already_flagged_high` | Flag Memory | 3 |

Aliases (`roster.ts`, `RULE_ALIAS`): `no_hr_record` → `employee_bank_matches_vendor` (same rule function), plus the mock
blue's `duplicate_amount_match` → `duplicate_invoice` and `bank_change_requested` → `recent_bank_change`. A rule id nobody
knows still maps to some guard (`guardForRule`, stable per id), so a new rule on the backend never breaks the animation.

### Green: 12 clients

Id = `green:client_01` … `client_12`. They are slots for Coastal Supply Co.'s counterparties. An entity is bound to a slot
by a stable hash (`greenIdFor(entityId)`), so the same vendor or attack always lands on the same client. When
`GET /fe/episodes/{ep}/vendors` answers, the top 12 vendors by spend fill the slots in order (name, category, risk in the
dossier).

## Geography

All coordinates are three.js world space of the glb (1 unit = 1 m, origin = rotunda floor centre, the lagoon toward -Z).
`lib/arena/config.ts`:

| | spawn anchor (x, z, radius) | where | slot ring radius |
|---|---|---|---|
| red | (-86, -12, 8) | lawn at the north colonnade tip | 18.0 |
| blue | (78, -30, 8) | south shore lawn | 12.5 |
| green | (-20, 42, 6) | lawn behind the rotunda | 7.0 |

Spawns are on open ground (nothing roofed overhead) so the aerial shots can see them. The slot rings put clients in the
middle, guards around them and fraudsters outside, so an attack has to cut through the guards. Everything stays inside
the r = 23.85 outer colonnade (the r = 16 inner piers fade out in the arena and are not obstacles).

## Events → animation (`lib/arena/director.ts`)

| Event | What happens |
|---|---|
| `episode.started`, `day.started` | `sim.converge()` (idempotent) |
| `attack.launched` | the red agent for `scheme_id` is queued against the client bound to `attack_id`; once the arena is formed it walks up to 3.3 m from the client, a red beam links them and it "works" the target. The scene then waits for the outcome |
| `gate.verdict` `block` | the guard for `rules_fired[0]` pulses with `BLOCK` (`WOULD BLOCK` when `enforced=false`, i.e. shadow mode) |
| `gate.verdict` `escalate` | amber pulse `REVIEW` |
| `gate.verdict` `allow` | a client pulses green (at most one per 0.9 s) |
| `escalation.opened` | the guard of the originating verdict pulses `NEEDS A DECISION` |
| `flag.raised` | the `already_flagged_high` guard pulses `FLAG` |
| `vendor.frozen` / `unfrozen` | the bound client turns icy / thaws |
| `attack.outcome` `extracted`, `partial` | coins stream from the client to the fraudster; `+$amount_extracted` pops |
| `attack.outcome` `blocked`, `flagged`, `failed` | a guard sprints to the fraudster (the one from the latest block that day, else the rule built for the scheme); the fraudster is caught for ~3 s; `BLOCKED` / `FLAGGED` pops |

An outcome that arrives for an attack the arena never saw launch (a reconnect catch-up) creates the scene on the spot and
resolves it.

Money, mode and escalations are not animated from events; they come from the reducer state in the HUD. The HUD also
carries the approve / block buttons for an open escalation (`api.resolve`). The card says it in plain words
(`lib/arena/escalation.ts`, tested): the question ("Pay this invoice?"), what is about to happen, why the controller stopped it
(one sentence per rule that fired, never a rule id), and what each button does, with the countdown. The backend's action id
and its developer-facing reason are not shown.

## The sim (`lib/arena/sim.ts`)

Pure TypeScript, no three.js, so it runs under vitest. `ArenaSim.update(dt)` is called once per frame.

Agent modes: `idle` (fidgeting at its spawn) → `travel` (along an A* path to its slot) → `hold` (parked, drifting 0.7 m) →
`approach` → `pitch` (fraudster working a client) → `return`; `dash` (guard intercepting at 24 m/s) and `caught`
(fraudster neutralised). Status overlays: `ok`, `caught`, `drained`, `frozen`.

Phases: `idle` → `converging` → `engaged` → `dispersing` → `idle`. Fraud scenes only start in `engaged`, one live scene per
fraudster, and run `queued → approach → pitch → resolve → after`. Guards against hangs: a stalled agent skips its waypoint
after 1.4 s, an approach that takes over 25 s completes, and a scene without a guard still ends.

Movement: speeds are 11-16 m/s depending on team (fast, stylised sprinters; fraudsters 13.5-15.5, guards 14-16, clients 11-13; departures are staggered by only ~0.05 s each); intermediate waypoints are clipped at 1.3 m
(they are only steering hints); a soft separation keeps agents 2.1 m apart; columns are circles the agents slide out of
(`pushOutOfColumns`).

### Triggering the animation by hand

```ts
window.redledger.converge()   // everyone leaves the perimeter and pathfinds into the rotunda
window.redledger.disperse()   // and back out
```

The HUD's *Send agents in / Send them back* does the same. With `?demo=1`, an ambient demo driver
(`DemoDriver` in `director.ts`) launches a random made-up attack every 5.5-9.5 s (40 % extracted, 45 % blocked, 15 % flagged)
while no feed is running; it is off by default because those attacks never touch the scoreboard. Judge-picked attacks (the
*Launch attack* console) are the real way to make something happen: see [show-mode.md](show-mode.md).
