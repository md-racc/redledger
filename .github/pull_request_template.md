## What

<!-- one or two sentences -->

## Area

- [ ] red  - [ ] green  - [ ] blue  - [ ] frontend  - [ ] battlefield/agentkit  - [ ] contracts

## Checklist (all required)

- [ ] Branch is `<area>/<topic>` and only touches `<area>/` (+ `DEVLOG.md`)
- [ ] `make lint` and my area's `make test-<area>` pass locally
- [ ] Runs under `DRY_RUN=true` (agents) / `NEXT_PUBLIC_MOCK=true` (frontend)
- [ ] No `contracts/` change — or there is a `contracts/CHANGELOG.md` entry and affected owners are tagged
- [ ] No new env var — or `.env.example` and README §11 are updated
- [ ] No secrets, no `.env`, no recorded fixtures containing keys
- [ ] `DEVLOG.md` entry added (one line: what changed, what's next, blockers)
- [ ] If an AI coding agent wrote most of this: I read the whole diff

## Notes for reviewer

<!-- anything surprising, any Finding for contracts/CHANGELOG.md -->
