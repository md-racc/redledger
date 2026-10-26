# Project closeout

Red Ledger was completed for Cal Hacks 13.0 in October 2026. It is preserved as a
portfolio project: source, screenshots, recorded runs, documented results and keyless local
setup. It is a synthetic finance sandbox, not a production payment system.

## Preserved submission

The original submission is commit
[`230a4a55521e0bbfdef430e8a461d231dae71bf7`](https://github.com/md-racc/redledger/commit/230a4a55521e0bbfdef430e8a461d231dae71bf7),
tagged [`hackathon-submission`](https://github.com/md-racc/redledger/tree/hackathon-submission).
Later maintenance changes do not alter that snapshot.

- [README screenshots](../README.md) show the original arena and escalation view.
- [Recordings](recordings/) preserve real operator event streams from October 24–25, 2026.
  Their index, scoring caveats and reported results are in [EVIDENCE.md](EVIDENCE.md).
- [STORY.md](STORY.md) explains what the prototype found. [PITCH.md](PITCH.md) and
  [SUBMISSION.md](SUBMISSION.md) preserve the historical judging and submission material.
- [Contracts](../contracts/) define the intended API, event and isolation behavior.
  [ARCHITECTURE.md](ARCHITECTURE.md) describes the implementation and known gaps.

Keep the recordings and evidence paths stable: frontend fixtures, generators and tests consume
them. Some headline results came from hosted reports after rescoring and differ from the
original event scoreboard; the evidence ledger explains those differences. Not every report
export is committed, so preserving the repo alone does not preserve the former database.

## Explore locally

For the arena with no backend, Docker or API keys, install Node.js 22 and run:

```bash
cd frontend
npm ci
NEXT_PUBLIC_MOCK=true npm run dev
```

Open <http://localhost:3000>. Mock mode replays events. It demonstrates the interface and event
flow, not a fresh model run. For a local Postgres/Ledger API simulation, stub agents, or the
real agents running keyless under `DRY_RUN=true`, follow [OPERATIONS.md §1](OPERATIONS.md#1-run-locally).
Those local paths do not require the old hosting credentials.

## Hosting retirement

The original hosted hackathon demo at `app.redledger.us` is retired. The owner confirmed
the original Vultr VM was destroyed. GitHub deployment was disabled
and `DEPLOY_ENABLED` set to `false` during closeout. This prevents new rollout through that
automation. The retained deployment workflow is manual-only; its `confirm_restore_hosting`
input defaults to `false` and gates image publishing and rollout. The production runbooks
remain as historical recovery material.

Unused DNS/Cloudflare routes and provider credentials still need their owner's separate review.
The owner may temporarily self-host a demo for visitors later; no future hosted availability is
promised. Keep the deployment assets for that deliberate choice. Screenshots, committed
recordings and local setup remain the permanent showcase.

## Remaining limits

- Green's live Droid turn remains disabled. The unfinished guard-lift PR #160 and acceptance
  driver PR #189 were closed as deferred work; the deterministic clerk remains available.
  There was no completed all-three-live-agent acceptance run.
- Blue's gate uses deterministic rules. Its optional model advisory does not decide verdicts;
  its learned controls select from fixed predicates. Humans shipped the invoice-split fix.
- The post-fix result was one short lineage. Red's other failed attacks contributed to the
  zero-loss result; it is not proof that every fraud scheme is blocked.
- CRS evidence covers one recorded run with three pinned fictional personas, not general
  identity-verification efficacy. Ordinary keyless local runs do not make CRS calls.
- Battlefield is single-process; a deployment can interrupt an active episode. Authentication
  used one shared admin key, not individual user accounts.
- Issue #117 was closed with remaining frontend/demo scope deferred. Closing the hackathon
  backlog does not establish that every proposed feature shipped.

[EVIDENCE.md §2](EVIDENCE.md#2-do-not-claim) retains the detailed claim limits.
