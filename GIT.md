# GIT.md — git hygiene protocol

Repo owner: **Dev Ad**. These rules exist so four people and their coding agents can work on one
repo for 36 hours without anyone having to untangle history. They are enforced by branch
protection, CI (`ownership-guard`, `contracts-guard`), and integration review (§4); the rest is
discipline. A coding agent
(Claude Code, Droid, Cursor) operating in this repo follows every rule below as if it were a
teammate, and stops to ask a human when a rule would be violated.

## 1. Branches

- `main` is protected. Nobody pushes to it. Not Ad either. Everything lands through a PR.
- Branch names: `<area>/<short-topic>` where `<area>` ∈ `red | green | blue | frontend | battlefield | contracts | docs | chore`.
  Examples: `red/ghost-vendor-scheme`, `blue/rules-engine`, `frontend/verdict-card`, `battlefield/escalation-wait`.
- One branch, one topic. If you're about to do a second unrelated thing, make a second branch.
- Branch from `main`, always current: `git fetch origin && git switch -c red/x origin/main`.
- A branch lives hours, not days. Open the PR early as a draft.
- Never commit to someone else's branch. Never check out someone else's branch to "help" unless they ask; then push to a new branch and PR into theirs.
  One exception: integration's plain merges of `origin/main` into an open PR branch (§4).

## 2. Scope: stay in your directory

| Branch prefix | May touch |
|---|---|
| `red/` | `red/**`, `battlefield/extensions/red_*.py`, `contracts/ext/red/**`, `devlog/*.md` |
| `green/` | `green/**`, `battlefield/extensions/green_*.py`, `contracts/ext/green/**`, `devlog/*.md` |
| `blue/` | `blue/**`, `battlefield/extensions/blue_*.py`, `contracts/ext/blue/**`, `devlog/*.md` |
| `frontend/` | `frontend/**`, `battlefield/extensions/fe_*.py`, `contracts/ext/fe/**`, `devlog/*.md` |
| `battlefield/` | `battlefield/**`, `agentkit/**`, compose files, `Makefile`, `.env.example`, `.github/**`, `devlog/*.md` |
| `contracts/` | `contracts/**`, `agentkit/agentkit/models.py`, `devlog/*.md` |
| `docs/`, `chore/` | anything, but no code behavior changes |

CI fails the PR if a branch touches files outside its area. The `battlefield/extensions/` and
`contracts/ext/` carve-outs are the designed way to add routes and tables without a contracts PR
(README §16). If your work genuinely needs a change to the core elsewhere (a new Ledger API field, a new event type), that is a **contracts** change: open a
separate `contracts/<topic>` PR first, get it merged, then rebase your branch onto it.

## 3. Commits

- Conventional, lower-case, imperative, scoped by area:
  `red: add bank_swap scheme`, `blue: cache gate verdicts by idempotency key`, `battlefield: resolve attacks at end of day`, `contracts: add vendor.unfrozen event`.
- Commit often locally. Squash on merge (the PR title becomes the commit), so local commit mess is fine; PR title must be good.
- Never `--amend` or rebase a commit that has already been pushed to a branch someone else has pulled. On your own branch, rebase freely before the PR is marked ready.
- Never `git push --force` to any branch. `--force-with-lease` on your own branch only, and only before review starts.
- Never commit: `.env`, keys, tokens, `node_modules`, `.venv`, `__pycache__`, recorded fixtures that contain secrets in payloads, Factory session files. `.gitignore` covers these; don't `-f` past it.
- Never commit generated files that CI can regenerate (`battlefield/db/schema.sql` is a copy; the source is `contracts/schema.sql`).

## 4. Pull requests

Integration (Ad) is the merge authority: Ad controls prod and is the main spoke, and teammates
review little. Authors never merge their own PR, human or agent.

- Title = the squash commit message. Body = the template, every box ticked honestly.
- Gates, all required before a merge:
  1. **CI green**: `python (agentkit|battlefield|red|green|blue)`, `frontend`, `ownership-guard`,
     `contracts-guard` (skipped = pass). No "merge anyway, I'll fix it after".
  2. **PR steward: READY.** Ad's orchestrator runs a read-only steward subagent that polls PRs and
     assesses each: CI triage, branch-prefix scope, exactly one devlog fragment, secrets scan,
     `AGENTS.md` §3 invariants (incl. 11, no peeking), merge order / stacking.
  3. **Verifier: pass**, for anything touching `battlefield/`, `agentkit/`, `contracts/`, `deploy/`,
     compose files, or more than one area. A fresh subagent, never the implementer; runs a
     `make mock-agents` smoke where relevant.
- Merge = `gh pr merge <n> --squash --match-head-commit <assessed sha>`. A push after assessment
  voids it; the steward reassesses.
- Owner review: CODEOWNERS auto-requests the owner. Welcome and fast-tracked, never blocking.
  Objections after merge go in a follow-up PR on the owner's prefix.
- Cross-area edits by integration (e.g. the proxy in `frontend/`) are allowed when integration
  needs them: branch on that area's prefix, PR tags the owner, owner reviews after the fact,
  follow-ups go through the owner's own PR.
- Small PRs. A scheme, a rule set, a component, a route group. If the diff is >600 lines, split it.
- Stacked PRs say `stacked on #N` in the body. Integration merges bottom-up.
- Conflicts with `main`: resolve on your branch, never in `main`. Integration may push a plain
  merge commit of `origin/main` into any open PR branch to resolve trivial conflicts or resync a
  stack: never force-push, never rewrite, no change beyond the conflict resolution. Authors
  `git pull` before continuing.
- Squash-merge only (repo setting). Delete the branch on merge (repo setting).

## 5. Contracts changes

`contracts/` and `agentkit/agentkit/models.py` are law. Changing them:
1. Branch `contracts/<topic>`.
2. Edit the contract file(s) **and** `contracts/CHANGELOG.md` (CI blocks a contracts PR without a CHANGELOG line).
3. Tag every affected owner in the PR.
4. Integration merges on owner authority (Ad) after the verifier passes (§4), and posts an FYI in
   the PR and the team channel. Everyone pulls `main` into their branch.
5. Affected owners object with a follow-up `contracts/` PR, not by blocking.
No code may depend on a contract change that isn't merged.

## 6. devlog — the common ledger

Every PR adds exactly one fragment, `devlog/<YYYY-MM-DDTHHMMZ>-<who>-<slug>.md`, holding one line
(no PR yet: one per working session):

```
- 2026-10-24T03:10Z · Al · red: ghost_vendor + bank_swap landing against mock battlefield; next: threshold_split; blocked: none
```

`make devlog WHO=Al MSG="..." [SLUG=topic]` writes it (UTC; SLUG defaults to the branch topic; MSG
is written verbatim, `$` and quotes included). `make devlog-show` prints the combined log. Rules:
- One fragment per PR. CI warns, doesn't fail, if a PR adds zero or several.
- New files never conflict, so the devlog never forces a resync.
- `DEVLOG.md` is frozen history (entries to 2026-10-24T03:00Z). Don't append, edit, or reorder it.
- Never edit or delete another person's fragment.
- WHO is the dev the work is for (Ad / Al / M / R), not the agent.
- It is the first thing anyone reads after sleeping. Write for that reader: what changed, what's next, what's blocking.
- Findings about the Droid SDK or sponsor APIs go in `contracts/CHANGELOG.md` under Findings, not here; link from here.

## 7. Coding-agent rules (Claude Code / Droid / Cursor)

An agent working in this repo:
- Reads `AGENTS.md`, `GIT.md`, and the `AGENTS.md` inside its working directory before its first edit.
- Confirms the current branch matches its area before editing. If on `main` or another area's branch, it creates the correct branch first.
- Edits only inside its area. If a change elsewhere is needed, it writes the proposed diff into the PR description or a `contracts/` PR and stops.
- Does not run `git push --force`, `git rebase` on pushed shared history, `git reset --hard` on anything it didn't create, `git clean -fdx`, `git checkout -- .`, or any command that destroys uncommitted work, without explicit per-command human confirmation.
- Teammates' agents (Al, M, R) may push their branch and open a PR on their prefix. They never
  merge, approve, or push to another person's branch; the human owner keeps CI green.
- Ad's orchestrator is the integration authority and may merge per §4 when Ad enables it. It
  merges only a READY, pinned SHA, and may push plain merges of `origin/main` into PR branches.
  Still never force-pushes or rewrites history.
- Does not edit `DEVLOG.md`, devlog fragments it didn't write, `contracts/CHANGELOG.md` entries it didn't write, or any file under `.github/` unless on a `battlefield/` or `chore/` branch owned by Ad.
- Does not commit secrets. If it finds one in the working tree, it says so and stops.
- Writes commit messages in the convention above and includes its attribution trailer.
- Orchestrators spawning subagents follow `AGENTS.md` §10: one worktree per implementer,
  subagents commit but never push, the orchestrator reviews and pushes.
- `.claude/settings.json` (committed) denies force-push, hard reset, clean, amend, branch -D,
  PR merge/approve, `rm -rf`, volume wipes, and reading/writing `.env`. A denial is the answer,
  not an obstacle. Only Ad's machine overrides the merge denial, locally and uncommitted; nobody
  commits that override.
- When a test fails that it did not cause, it reports it rather than "fixing" by deleting or skipping the test.

## 8. Recovery

- Pushed to the wrong branch: don't force-push. Cherry-pick onto the right branch, then revert on the wrong one via PR.
- Merged something broken: `git revert` via a `chore/revert-<pr>` PR. Never rewrite `main`.
- Leaked a secret: rotate the key first (the key is burned the moment it's pushed), then clean history with Ad.
- Conflict on `DEVLOG.md` (pre-fragment branches): keep both sides, both lines; better, move your
  line into a `devlog/` fragment.

## 9. Repo settings (Ad applies on creation — full list in `deploy/OWNER-CHECKLIST.md`)

- Branch protection on `main`: require PR, 0 approvals, code-owner review off, required checks
  `python (agentkit)`, `python (battlefield)`, `python (red)`, `python (green)`, `python (blue)`,
  `frontend`, `ownership-guard`, `contracts-guard` (skipped = pass), include administrators,
  no force pushes, no deletions.
- Merge: squash only; auto-delete head branches.
- CODEOWNERS: routing/notification only, not a gate.
- Secrets: `FACTORY_API_KEY` etc. live in GitHub Actions secrets only if CI ever needs them (it currently doesn't).
