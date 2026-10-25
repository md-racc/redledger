## What

<!-- one or two sentences -->

## Area

- [ ] red  - [ ] green  - [ ] blue  - [ ] frontend  - [ ] battlefield/agentkit  - [ ] contracts

## Checklist (all required)

- [ ] Branch is `<area>/<topic>` and only touches `<area>/` (+ its `devlog/` fragment)
- [ ] `make lint` and my area's `make test-<area>` pass locally
- [ ] Runs under `DRY_RUN=true` (agents) / `NEXT_PUBLIC_MOCK=true` (frontend)
- [ ] No `contracts/` change — or there is a `contracts/CHANGELOG.md` entry and every affected owner is tagged
- [ ] No new env var — or `.env.example` and docs/OPERATIONS.md §2 are updated
- [ ] No secrets, no `.env`, no recorded fixtures containing keys
- [ ] Exactly one devlog fragment added: `make devlog WHO=<Ad|Al|M|R> MSG="what changed; next: …; blocked: …"` (don't append to `DEVLOG.md`)
- [ ] If an AI coding agent wrote most of this: I read the whole diff
- [ ] I won't merge this myself: integration (Ad) merges once CI is green and the steward/verifier pass (`GIT.md` §4)

## Notes for reviewer

<!-- anything surprising, any Finding for contracts/CHANGELOG.md, stacked-on / merge-after PRs.
     Owner review is welcome and fast-tracked, never blocking. -->
