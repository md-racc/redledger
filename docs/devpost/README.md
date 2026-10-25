# docs/devpost — track docs for the Devpost submission and the pitch

Status as of 2026-10-25 ~04:45Z, main @ 53adcb7; prod @ fb829e6 (CRS lines updated ~05:45Z, main @ e440119). Written for R (Devpost + pitch). Ad keeps them current.
The red-and-blue-live recordings (#193, recorded 04:54–05:05Z, before #195 reached prod) are cited where they change a
claim (blue's audit cost, the audits that raised no flags).

Each file is one prize track. Each has the same ten sections: prize snapshot, our angle, a criteria → evidence
matrix, what we have in detail, what's planned, demo beats, paste-ready Devpost copy, a claims ledger
(safe / caveat / don't say), likely judge questions, and a numbers sheet with sources. The spoken pitch they
line up with is [`frontend/docs/pitch-script.md`](../../frontend/docs/pitch-script.md) (#132, reworded in #145 to match the
real agents). The old "R should reword" notes in these docs are resolved by #145. A few lines went stale after #145
(red got 8 schemes, the voice console landed); hyphenate.md §6 lists them. R's close was already fixed in #177.

| Rank | File | Track | Prize (confirm on Devpost) |
|---|---|---|---|
| 1 | [hyphenate.md](hyphenate.md) | Hyphenate: The Hyphenated Enterprise, Autonomous Systems for Finance | $8k / $5k / $3k, expedited interviews for top 5 |
| 2 | [factory.md](factory.md) | Factory: Best Use of the Droid SDK | $2,000 + credits |
| 3 | [technical.md](technical.md) | Cal Hacks Most Technically Advanced; Microsoft Built for the Real World / Customer Impact | NuPhy Air60 HE each; $3,800 + Surface each |
| 4 | [armadin.md](armadin.md) | Armadin: Best Security Hack | $996 + Apple headphones (criteria pending) |
| 5 | [crs.md](crs.md) | CRS Financial Intelligence Challenge: submit to **Best Identity / Fraud Innovation** and **Best Financial AI Agent** (optionally Most Unexpected Use) | $1,000 / $500 / interviews (Identity / Fraud is an interview) |

CRS is in the submit list: on 2026-10-25 `make prod-crs-episode SEED=42 DAYS=2` (#197) **passed on prod** with blue's
live Droid audit (ep_9cbc3362d44e): the model called the CRS check, raised the hold on P12, and the gate blocked P12's
next expense while P01's and P16's paid. Verdict: **GO for Best Identity / Fraud Innovation and Best Financial AI
Agent**. The challenge's only rule is "show it working live", so run that command live at the CRS table; the
recording (`docs/recordings/crs-live-ep_9cbc3362d44e.jsonl`) is the fallback (crs.md §0).

Rank 6 has no doc because the claims are one-liners. Paste them as-is:

- **MLH Best Use of Tiger Data:** `events` and `audit_log` are TimescaleDB hypertables keyed `(id, ts)`, and a
  `score_timeline` continuous aggregate serves score over time. CI runs the full battlefield suite on the real
  Timescale image (#98, #100). Local compose defaults to `timescale/timescaledb:latest-pg16`. Prod runs plain
  Postgres 16 until P5 lands, so don't say "in production" before then.
- **MLH Best Use of Vultr:** the whole stack runs on one Vultr VM, deployed by an approval-gated GitHub Actions
  workflow (README §13, §17).

Not submitting, or drop the claim:

- **MLH Gemini:** red moved off `gemini-3.8-flash` after it stalled live turns (Finding, #118), and blue's live audit
  runs on `gpt-5.4-mini` for the same reason (#78). The gate LLM supports Gemini but isn't enabled on prod. Don't
  claim it unless that changes.
- **Anthropic, GoDaddy/.Tech, Fetch.ai, Solana, Snowflake:** see `INTEGRATIONS.md` §5 and §8.

## Status legend (used in every doc)

- `LIVE`: running on prod (app.redledger.us) with a real model today.
- `ON MAIN`: merged and tested; runs keyless (DRY_RUN / mock agents), not exercised live on prod.
- `PLANNED`: not done yet. Each doc names the owner, the dependency, and the fallback wording.
- `NOT DOING`: out of scope.

## What is live today (the honest baseline)

- Red runs live on Factory's Droid SDK on prod (`gpt-5.4-mini`, reasoning low): ~11 s and ~2.6k credits per turn.
  It has **8 schemes** (#166): ghost_vendor, bank_swap, duplicate_invoice, threshold_split, ghost_employee,
  expense_inflation, po_mismatch, amount_drift (`red/schemes/`).
- **Blue's daily audit runs live on Droid on prod** (`gpt-5.4-mini`, `DRY_RUN_BLUE=false`; guard lifted in #157).
  Smoke episode `ep_f9c695b3144f` (2-day enforce) finished live audits on both days, 3,806 and 4,109 credits (blue's
  `turn_usage` log; #78). That smoke predates #176, so battlefield recorded those audits as 0 and blue's `droid_ok`
  read false; from the deploy containing 6640354, `/audit` returns `usage` (#174, #176), blue's credits count toward
  the episode and lineage caps, and `droid_ok` is truthful. In the 6-day red-and-blue-live pair (#193) an audit cost
  3.4k–18.7k credits (66,422 and 37,446 over the two runs, about 6–11k a day), so ~4k is a quiet day, not the
  average. Every one of those 12 audits ended "0 confirmed flags, 0 confirmed freezes" (3 of them partial): on prod the
  live audit's `raise_flag` calls were being refused by agentkit's strict tool identity check (streamed arguments; fixed
  in #195). Since #195 the live audit has raised a flag the gate enforced (CRS run ep_9cbc3362d44e, #197/#201). Blue's `/gate`
  is still the deterministic rules engine plus an optional LLM advisor that is **off** on prod. The gate is not a
  Droid session. Its rules decide: some block, some escalate to a human (bank changes), and some only annotate
  (`vendor_age_lt_7d`, `near_threshold`). Real blue does **not** stop every red attack; see hyphenate.md §8.
- **Green is keyless by Ad's decision for the pitch** (#78): it runs its full AP procedure on the same harness with no
  model calls (`DRY_RUN_GREEN=true`; the guard-lift PR #160 stays a draft). Pitch line: "red and blue run live on
  Droid, and green runs on the same harness, keyless."
- **Judges can steer red** (#165): words typed or spoken in the attack console reach red's next turn as quoted data
  and steer which catalog scheme it picks, or that scheme's params. The **voice attack console** (#154) takes speech
  in any language, transcribed by ElevenLabs speech-to-text (key wired in #162/#163). Voice is admin-only on the site,
  maps the words to the closest of red's eight schemes by keyword (`frontend/lib/voice/intent.ts`; since #186 a test keeps
  its eight the same as the arena roster's), and #154 was
  never tested against the real ElevenLabs service. Try one real recording on prod before relying on it.
- **CRS (P6): PASSED on prod with the live audit** (ep_9cbc3362d44e, enforce, seed 42, 2 days, ~05:40Z;
  `make prod-crs-episode`, #197). Blue's live Droid audit (`gpt-5.4-mini`) called `crs_identity_check` on day 0 and
  day 1; the sandbox reported a mismatch for P12; the model raised the HIGH employee flag via `raise_flag`; on day 1
  the gate blocked P12's expense (`already_flagged_high`, enforced); P01's and P16's expenses all paid; blue credits
  3,985 / 5,318. The first attempt (ep_c2c98b2da583) failed because strict identity refused the model's streamed
  `raise_flag` calls; #195 fixed it. Earlier, M's local acceptance (ep_0181eda1c921, #102) proved the same chain with
  the keyless audit and 19 `billable:false` checks. One prod run, so say "one recorded run". See crs.md.
- **`threshold_split` control: expense version shipped, invoice version still open.** #173 adds a blocking aggregate
  `threshold_split` rule for **expenses only**. Red's scheme splits **invoices**, so the gap the live lineage found is
  still open (P8, #175).
- **Closed information leaks:** red's `GET /attacks` now withholds unrevealed outcomes (#138 contract, #142 code), and
  replayed gate verdicts are bound to their day and enforcement mode (#147 contract, #151 code). See armadin.md §4.9.
- **Live-red evolution (P1, done):** the live-red prod lineage `ln_f52a3df83c8d` (5 generations × 8 days, enforce,
  seeds 502–506, red live, green and blue keyless real code, ~109k red credits). It ran **before** blue's audit went
  live and before #148 and #173; no lineage has run since. Red re-weighted its catalog toward
  `threshold_split` (launches 1 → 2 → 6 → 3 → 7, every one extracted) and extraction rose from $19,076 (g1) to
  $97,734 (g5). Blue switched on its four pre-written learned controls after g1 and widened its near-threshold band,
  but none of them ever fired on a split. Red invented no new schemes. That is a controls gap the sandbox found,
  and we say so. The report is an operator export, not committed.
- **Mock-agent evolution (illustration only):** a keyless mock-agent lineage run (local), `ln_fbdfbd2d74cc`, shows what
  closing the loop looks like: red evades in generation 2, blue catches 5/5 in generation 3. Those are the **mock**
  agents (`battlefield/mock_agents/`), not M's blue or Al's red. Always label it mock.
- **Controller off vs. on with live red (P2, done):** `docs/recordings/` (#136), seed 42, 10 days, recorded on prod:
  off $10,284.61 extracted, 0 of 10 caught; enforce $1,824.22 extracted, 1 of 10 caught, $100 false-positive cost.
  Green and blue were both keyless when these were recorded.
  In both runs 9 of red's 10 attacks were duplicate invoices that were never paid; all the money came from one bank
  swap. In enforce, the bank-change approvals escalated and timed out to blocks, but red's own $1,824.22 invoice was
  still paid (outcome `partial`). So the enforce number is not zero.
- **Controller off vs. on with red and blue live (#193):** seed 42, 6 days, one fixed attack plan (ghost_vendor,
  bank_swap, threshold_split, expense_inflation, amount_drift, ghost_employee), red and blue's audit live, green keyless:
  off `ep_89d1df6b012a` $23,681.43 extracted, 0 of 6 caught; enforce `ep_d9b561111d60` $20,350.37 extracted, 2 of 6
  caught, $1,480 blocked, $50 false-positive cost. The splitting, drift and inflation schemes got through, and the two
  catches came from the gate rules (the live audit raised no flags in this pre-#195 pair, see above). This pair is the honest picture of the
  controls against a harder plan; the #136 pair looks better largely because 9 of its 10 attacks were duplicate
  invoices that were never paid either way. If you quote #136, say "with red choosing its own schemes"; don't present it as the general result.
- The 90-second show in `frontend/` plays a recording when any agent is live (red and blue are), so it's a replay on
  prod (`frontend/public/mocks/sample.jsonl`, mock agents; `wantLive` in `frontend/components/arena/useShow.ts`). The
  live evidence is Launch attack (typed, tiles or voice) plus the backstage consoles, which since #146 join the active
  run and show blue's verdicts with reasons. On prod the EvolutionCard loads the real `/fe/lineages/{id}/report` for
  the newest finished lineage, which is `ln_f52a3df83c8d`, with a recorded fallback (`frontend/lib/arena/lineage.ts`;
  P3, #117 still open). Check what it shows before going on stage.
- **The site is public and read-only (P7, LIVE since ~04:30Z 2026-10-25; #152, #159).** Judges can open
  app.redledger.us on their own devices and watch runs live. Only the stage laptops, signed in at `/admin`, can start
  runs, launch attacks, use voice or resolve escalations; the server enforces it (viewers get 403 on anything but
  GET/HEAD; reads that say which rows are red's, such as the lineage export, attacks, the audit log and the
  verdict × origin matrices, are admin-only; and `origin` keys are stripped from every other read a viewer gets).
  Cloudflare Access no longer gates the site. The event socket is still the operator stream, so viewers see red's
  attacks as they launch, which is the show.

## Planned items (the same IDs in every doc)

| ID | What | Owner | Status | If it doesn't land, say |
|---|---|---|---|---|
| P1 | Live-red evolution lineage | Ad | DONE (`ln_f52a3df83c8d`) | — |
| P2 | Live off/on recordings | Ad | DONE (#136 red live; #193 red and blue live, `docs/recordings/`) | — |
| P3 | Evolution view in the frontend from real data | R (#117) | PARTIAL: the EvolutionCard loads the real report | "The evolution card shows the latest real lineage report" |
| P4 | Agents live on Droid | M | Blue audit LIVE; green NOT DOING (Ad's decision, #78) | "Red and blue live on Droid; green on the same harness, keyless" |
| P5 | Prod on the TimescaleDB image | Ad | NOT DOING for the hackathon unless it lands | "TimescaleDB proven in CI; prod on Postgres 16" |
| P6 | CRS live demo | M / Ad | PASSED on prod with blue's live audit (ep_9cbc3362d44e, #197); local acceptance earlier (ep_0181eda1c921). Live at the table still to do | "Recorded on prod 2026-10-25 (ep_9cbc3362d44e); live at the table on request" |
| P7 | Public read-only site (no Access) | Ad | DONE, LIVE since ~04:30Z 2026-10-25 (#152, #159) | — |
| P8 | Invoice threshold-split control in blue | M (#175) | ASKED | "Red found a gap in invoice split detection; the expense version is shipped (#173)" |
| P9 | Short live lineage after P8, to show blue closing the gap | Ad | PLANNED after P8 | Keep the P1 story: "the sandbox surfaced a real gap" |

Before the pitch, re-check this table and say the version that's true on the day (R's close already does this).
