# docs/devpost — track docs for the Devpost submission and the pitch

Status as of 2026-10-25 ~04:15Z, main @ fb829e6; prod @ 47e3e33. Written for R (Devpost + pitch). Ad keeps them current.

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
| 5 | [crs.md](crs.md) | CRS Financial Intelligence Challenge: submit to **Best Identity / Fraud Innovation** (optionally Most Unexpected Use) | $1,000 / $500 / interviews (Identity / Fraud is an interview) |

CRS is in the submit list now: the end-to-end acceptance passed against the live CRS sandbox (ep_0181eda1c921, #102).
The verdict is **GO, conditional on a live laptop demo at the CRS table**, because the challenge's only rule is "show
it working live" and CRS doesn't run on prod. If nobody can run the laptop demo, drop CRS (crs.md §0).

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
  the episode and lineage caps, and `droid_ok` is truthful. Blue's `/gate`
  is still the deterministic rules engine plus an optional LLM advisor that is **off** on prod. The gate is not a
  Droid session. Its rules decide: some block, some escalate to a human (bank changes), and some only annotate
  (`vendor_age_lt_7d`, `near_threshold`). Real blue does **not** stop every red attack; see hyphenate.md §8.
- **Green is keyless by Ad's decision for the pitch** (#78): it runs its full AP procedure on the same harness with no
  model calls (`DRY_RUN_GREEN=true`; the guard-lift PR #160 stays a draft). Pitch line: "red and blue run live on
  Droid, and green runs on the same harness, keyless."
- **Judges can steer red** (#165): words typed or spoken in the attack console reach red's next turn as quoted data
  and steer which catalog scheme it picks, or that scheme's params. The **voice attack console** (#154) takes speech
  in any language, transcribed by ElevenLabs speech-to-text (key wired in #162/#163). Voice is admin-only on the site,
  maps the words to the closest of five built-in schemes by keyword (`frontend/lib/voice/intent.ts`), and #154 was
  never tested against the real ElevenLabs service. Try one real recording on prod before relying on it.
- **CRS (P6): end-to-end acceptance PASSED** against the live CRS sandbox from a local stack (M, ep_0181eda1c921,
  #102 at 00:09Z): P12's identity mismatch raised a high flag and blocked P12's next expense
  (`already_flagged_high`); P01/P16 paid; 19 identity checks, all `billable:false`. It doesn't run on prod. See crs.md.
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
- The 90-second show in `frontend/` plays a recording when any agent is live (red and blue are), so it's a replay on
  prod (`frontend/public/mocks/sample.jsonl`, mock agents; `wantLive` in `frontend/components/arena/useShow.ts`). The
  live evidence is Launch attack (typed, tiles or voice) plus the backstage consoles, which since #146 join the active
  run and show blue's verdicts with reasons. On prod the EvolutionCard loads the real `/fe/lineages/{id}/report` for
  the newest finished lineage, which is `ln_f52a3df83c8d`, with a recorded fallback (`frontend/lib/arena/lineage.ts`;
  P3, #117 still open). Check what it shows before going on stage.
- The site is still behind Cloudflare Access (email PIN). A public read-only mode is merged (#152, #159): anyone can
  watch, only admins can act. Switching it on is P7, in progress. Until it is on, say "the site is behind Cloudflare
  Access; judges get a live walkthrough or the recordings".

## Planned items (the same IDs in every doc)

| ID | What | Owner | Status | If it doesn't land, say |
|---|---|---|---|---|
| P1 | Live-red evolution lineage | Ad | DONE (`ln_f52a3df83c8d`) | — |
| P2 | Live-red off/on recordings | Ad | DONE (#136, `docs/recordings/`) | — |
| P3 | Evolution view in the frontend from real data | R (#117) | PARTIAL: the EvolutionCard loads the real report | "The evolution card shows the latest real lineage report" |
| P4 | Agents live on Droid | M | Blue audit LIVE; green NOT DOING (Ad's decision, #78) | "Red and blue live on Droid; green on the same harness, keyless" |
| P5 | Prod on the TimescaleDB image | Ad | NOT DOING for the hackathon unless it lands | "TimescaleDB proven in CI; prod on Postgres 16" |
| P6 | CRS live demo | M | Acceptance PASSED locally (ep_0181eda1c921); the table demo from a laptop is pending | "Recorded acceptance run ep_0181eda1c921; live at the table on request" |
| P7 | Public read-only site (no Access) | Ad | IN PROGRESS (code merged in #152, #159) | "Site behind Cloudflare Access; live walkthrough or recordings" |
| P8 | Invoice threshold-split control in blue | M (#175) | ASKED | "Red found a gap in invoice split detection; the expense version is shipped (#173)" |
| P9 | Short live lineage after P8, to show blue closing the gap | Ad | PLANNED after P8 | Keep the P1 story: "the sandbox surfaced a real gap" |

Before the pitch, re-check this table and say the version that's true on the day (R's close already does this).
