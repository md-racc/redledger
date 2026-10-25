# Demo recordings

The stage fallback: controller-off vs controller-on demo pairs (README §14), recorded on prod. Each line is one event from the operator stream (`contracts/events.md`), exported with `make prod-record` and secret-scanned. The long hex strings are Droid tool-call ids. These are operator streams, so `attack.launched` events identify red's entities. Never feed them to an agent.

To replay one: copy it into `battlefield/fixtures/episodes/` (or the frontend's mocks) and use the replay route (`POST /replays/{id}/play`).

## CRS on prod with blue's live audit (2026-10-25)

Not a demo pair: one run of blue's CRS identity scenario, `make prod-crs-episode SEED=42 DAYS=2` (#197;
`deploy/PROD-OPS.md`). Red and blue's audit live on Droid (`gpt-5.4-mini`), green keyless. Result **PASS**.

| file | episode | mode | seed / days | CRS result | P12's day-1 expense | P01 / P16 expenses | blue credits (day 0 / day 1) |
|---|---|---|---|---|---|---|---|
| `crs-live-ep_9cbc3362d44e.jsonl` | `ep_9cbc3362d44e` | `enforce` | 42 / 2 | `crs_identity_check` called on day 0 and day 1; sandbox mismatch for P12; the model raised the HIGH employee flag via `raise_flag` | `expenses.approve` → block, `already_flagged_high`, enforced | all paid | 3,985 / 5,318 |

The stream starts with the operator setup (fixture employees and expenses, three `x.blue.crs_profile_bound`
events carrying only `employee_id`). It has no persona names, identity fields or CRS response text: blue's tool
result is a one-line summary and the flag reason is blue's fixed finding text. Red also ran its own two attacks
(amount_drift, duplicate_invoice), unrelated to CRS. The scoreboard counts P12's blocked expense as a legit
block (`legit_blocked` 1, false-positive cost $51.82), because the persona employees are operator fixtures,
not red's; here that block is the CRS hold working. Details: `blue/CRS.md`, "Prod live-audit acceptance".

## Red and blue live (2026-10-25), the current pair

Seed 42, 6 days, with **red and blue's audit live on Droid** (`gpt-5.4-mini`) and green keyless. Both runs follow one fixed attack plan, so the controller is the only difference: day 0 ghost_vendor, 1 bank_swap, 2 threshold_split, 3 expense_inflation, 4 amount_drift, 5 ghost_employee.

| file | episode | mode | attacks launched / caught | extracted | blocked | false-positive cost | red / blue credits |
|---|---|---|---|---|---|---|---|
| `demo-off-redblue-live.jsonl` | `ep_89d1df6b012a` | `off` | 6 / 0 | $23,681.43 | $0 | $0 | 16,038 / 66,422 |
| `demo-enforce-redblue-live.jsonl` | `ep_d9b561111d60` | `enforce` | 6 / 2 | $20,350.37 | $1,480.00 | $50 | 14,206 / 37,446 |

Honest reading: with the controller on, blue caught 2 of the 6 schemes. The splitting, drift and inflation schemes still got through. That is the gap P8 (#175) targets. At recording time, blue's live-audit `raise_flag` calls were being refused on prod by agentkit's strict tool identity check, so these catches come from the gate rules, not from audit flags. The cause was that `gpt-5.4-mini` streams tool arguments (first event `{}`); #195 has since fixed it, and the CRS run above shows a live-audit flag landing on prod. These two files predate the fix.

## Red live only (2026-10-24)

Seed 42, 10 days, red live on Droid (`gpt-5.4-mini`, reasoning `low`), green and blue keyless. Red chose its own schemes.

| file | episode | mode | attacks launched / caught | extracted | false-positive cost | red credits |
|---|---|---|---|---|---|---|
| `demo-off-live.jsonl` | `ep_7f473df2a138` | `off` | 10 / 0 | $10,284.61 | $0 | 26,230 |
| `demo-enforce-live.jsonl` | `ep_540353ebf616` | `enforce` | 10 / 1 | $1,824.22 | $100 | 24,449 |
