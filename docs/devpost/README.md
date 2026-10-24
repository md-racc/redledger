# docs/devpost — track docs for the Devpost submission and the pitch

Status as of 2026-10-24 ~23:00Z, main @ 0de4fe8; prod runs 4c6bdd9 (#131). Written for R (Devpost + pitch). Ad keeps them current.

Each file is one prize track. Each has the same ten sections: prize snapshot, our angle, a criteria → evidence
matrix, what we have in detail, what's planned, demo beats, paste-ready Devpost copy, a claims ledger
(safe / caveat / don't say), likely judge questions, and a numbers sheet with sources. The spoken pitch they
line up with is [`frontend/docs/pitch-script.md`](../../frontend/docs/pitch-script.md) (#132).

| Rank | File | Track | Prize (confirm on Devpost) |
|---|---|---|---|
| 1 | [hyphenate.md](hyphenate.md) | Hyphenate: The Hyphenated Enterprise, Autonomous Systems for Finance | $8k / $5k / $3k, expedited interviews for top 5 |
| 2 | [factory.md](factory.md) | Factory: Best Use of the Droid SDK | $2,000 + credits |
| 3 | [technical.md](technical.md) | Cal Hacks Most Technically Advanced; Microsoft Built for the Real World / Customer Impact | NuPhy Air60 HE each; $3,800 + Surface each |
| 4 | [armadin.md](armadin.md) | Armadin: Best Security Hack | $996 + Apple headphones (criteria pending) |
| 6 | [crs.md](crs.md) | CRS Financial Intelligence Challenge | $1,000 / $500 / interviews |

Rank 5 has no doc because the claims are one-liners. Paste them as-is:

- **MLH Best Use of Tiger Data:** `events` and `audit_log` are TimescaleDB hypertables keyed `(id, ts)`, and a
  `score_timeline` continuous aggregate serves score over time. CI runs the full battlefield suite on the real
  Timescale image (#98, #100). Local compose defaults to `timescale/timescaledb:latest-pg16`. Prod runs plain
  Postgres 16 until P5 lands, so don't say "in production" before then.
- **MLH Best Use of Vultr:** the whole stack runs on one Vultr VM, deployed by an approval-gated GitHub Actions
  workflow (README §13, §17).

Not submitting, or drop the claim:

- **MLH Gemini:** red moved off `gemini-3.8-flash` after it stalled live turns (Finding, #118). The gate LLM
  supports Gemini but isn't enabled on prod. Don't claim it unless that changes.
- **Anthropic, GoDaddy/.Tech, Fetch.ai, Solana, Snowflake:** see `INTEGRATIONS.md` §5 and §8.

## Status legend (used in every doc)

- `LIVE`: running on prod (app.redledger.us) with a real model today.
- `ON MAIN`: merged and tested; runs keyless (DRY_RUN / mock agents), not exercised live on prod.
- `PLANNED`: not done yet. Each doc names the owner, the dependency, and the fallback wording.
- `NOT DOING`: out of scope.

## What is live today (the honest baseline)

- Red runs live on Factory's Droid SDK on prod (`gpt-5.4-mini`, reasoning low): ~11 s and ~2.6k credits per turn.
- Green and blue run their full logic on prod with no model calls (`DRY_RUN_GREEN/BLUE=true`). Blue's
  deterministic rules decide there: some block, some escalate to a human (bank changes), and some only annotate
  (`vendor_age_lt_7d`, `near_threshold`). Real blue does **not** stop every red attack; see hyphenate.md §8.
- **Live-red evolution (P1, done):** the live-red prod lineage `ln_f52a3df83c8d` (5 generations × 8 days, enforce,
  seeds 502–506, red live, green and blue keyless real code, ~109k red credits). Red re-weighted its catalog toward
  `threshold_split` (launches 1 → 2 → 6 → 3 → 7, every one extracted) and extraction rose from $19,076 (g1) to
  $97,734 (g5). Blue switched on its four pre-written learned controls after g1 and widened its near-threshold band,
  but none of them ever fired on a split. Red invented no new schemes. That is a controls gap the sandbox found,
  and we say so. The report is an operator export, not committed.
- **Mock-agent evolution (illustration only):** a keyless mock-agent lineage run (local), `ln_fbdfbd2d74cc`, shows what
  closing the loop looks like: red evades in generation 2, blue catches 5/5 in generation 3. Those are the **mock**
  agents (`battlefield/mock_agents/`), not M's blue or Al's red. Always label it mock.
- **Controller off vs. on with live red (P2, done):** `docs/recordings/` (#136), seed 42, 10 days, recorded on prod:
  off $10,284.61 extracted, 0 of 10 caught; enforce $1,824.22 extracted, 1 of 10 caught, $100 false-positive cost.
  In both runs 9 of red's 10 attacks were duplicate invoices that were never paid; all the money came from one bank
  swap. In enforce, the bank-change approvals escalated and timed out to blocks, but red's own $1,824.22 invoice was
  still paid (outcome `partial`). So the enforce number is not zero.
- The 90-second show in `frontend/` plays a recording when any agent is live (red is), so it's a replay on prod
  (`frontend/public/mocks/sample.jsonl`, mock agents). The live evidence is Launch attack plus the backstage consoles.
  On prod the EvolutionCard loads the newest finished lineage from the backend, which is now `ln_f52a3df83c8d` (code
  reading: `frontend/lib/arena/lineage.ts:47-57`; `GET /lineages` is newest first). Check what it shows before going on stage.

## Planned items (the same IDs in every doc)

| ID | What | Owner | If it doesn't land, say |
|---|---|---|---|
| P1 | Live-red evolution lineage on prod. **Done:** `ln_f52a3df83c8d`, 5 generations × 8 days, enforce (numbers above) | Ad | Done. Say what it showed: red adapted and farmed `threshold_split`; blue's bounded learning didn't close it. Use the mock lineage only as a labelled illustration |
| P2 | Recorded controller-off vs. controller-on episodes with live red, same seed. **Done:** `docs/recordings/` (#136) | Ad | Done. Not yet wired into the show; replay via `POST /replays/{id}/play` after copying into the fixtures dir. Say they are recordings |
| P3 | Evolution view in the frontend from the real `/fe/lineages` routes (#117) | R | The EvolutionCard already loads the newest finished backend lineage when connected (now `ln_f52a3df83c8d` on prod); offline it shows the golden test fixture `ln_rpt_sample`, which is synthetic. Say which one is on screen |
| P4 | Green and/or blue live on Droid on prod (#78) | M | "Red is live; green and blue run their full logic keyless on the same harness" |
| P5 | Prod on the TimescaleDB image | Ad | "TimescaleDB proven in CI; prod on Postgres 16" |
| P6 | CRS sandbox live demo (#102) | M | See crs.md |

Before the pitch, re-check this table and say the version that's true on the day (R's close already does this).
