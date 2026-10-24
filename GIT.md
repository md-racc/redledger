# GIT.md — git hygiene protocol

Repo owner: **Dev Ad**. These rules exist so four people and their coding agents can work on one
repo for 36 hours without anyone having to untangle history. They are enforced by branch
protection, CODEOWNERS, and the `ownership-guard` CI job; the rest is discipline. A coding agent
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

## 2. Scope: stay in your directory

| Branch prefix | May touch |
|---|---|
| `red/` | `red/**`, `battlefield/extensions/red_*.py`, `contracts/ext/red/**`, `DEVLOG.md` |
| `green/` | `green/**`, `battlefield/extensions/green_*.py`, `contracts/ext/green/**`, `DEVLOG.md` |
| `blue/` | `blue/**`, `battlefield/extensions/blue_*.py`, `contracts/ext/blue/**`, `DEVLOG.md` |
| `frontend/` | `frontend/**`, `battlefield/extensions/fe_*.py`, `contracts/ext/fe/**`, `DEVLOG.md` |
| `battlefield/` | `battlefield/**`, `agentkit/**`, compose files, `Makefile`, `.env.example`, `.github/**`, `DEVLOG.md` |
| `contracts/` | `contracts/**`, `agentkit/agentkit/models.py`, `DEVLOG.md` |
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

- Title = the squash commit message. Body = the template, every box ticked honestly.
- Required reviewer = the CODEOWNER of the directory. For `contracts/` that is Ad plus every affected area owner.
- CI must be green. No "merge anyway, I'll fix it after".
- Small PRs. A scheme, a rule set, a component, a route group. If the diff is >600 lines, split it.
- Rebase onto `main` before marking ready; resolve conflicts on your branch, never in `main`.
- Squash-merge only (repo setting). Delete the branch on merge (repo setting).
- The author merges once approved, unless the author is an AI agent — then the human owner merges.

## 5. Contracts changes

`contracts/` and `agentkit/agentkit/models.py` are law. Changing them:
1. Branch `contracts/<topic>`.
2. Edit the contract file(s) **and** `contracts/CHANGELOG.md` (CI blocks a contracts PR without a CHANGELOG line).
3. Tag every affected owner in the PR. They have to approve.
4. Merge, announce in the team channel, everyone rebases.
No code may depend on a contract change that isn't merged.

## 6. DEVLOG.md — the common ledger

`DEVLOG.md` at repo root is append-only and shared by everyone. One line per PR (or per working
session if you haven't opened a PR yet), newest at the bottom:

```
- 2026-10-24T03:10Z · Al · red: ghost_vendor + bank_swap landing against mock battlefield; next: threshold_split; blocked: none
```

`make devlog WHO=Al MSG="..."` appends it for you. Rules:
- Append only. Never edit or reorder another person's line.
- Every PR adds exactly one line (the template checks for it). Conflicts on DEVLOG.md are resolved by keeping both lines.
- It is the first thing anyone reads after sleeping. Write for that reader: what changed, what's next, what's blocking.
- Findings about the Droid SDK or sponsor APIs go in `contracts/CHANGELOG.md` under Findings, not here; link from here.

## 7. Coding-agent rules (Claude Code / Droid / Cursor)

An agent working in this repo:
- Reads `AGENTS.md`, `GIT.md`, and the `AGENTS.md` inside its working directory before its first edit.
- Confirms the current branch matches its area before editing. If on `main` or another area's branch, it creates the correct branch first.
- Edits only inside its area. If a change elsewhere is needed, it writes the proposed diff into the PR description or a `contracts/` PR and stops.
- Does not run `git push --force`, `git rebase` on pushed shared history, `git reset --hard` on anything it didn't create, `git clean -fdx`, `git checkout -- .`, or any command that destroys uncommitted work, without explicit per-command human confirmation.
- Does not create, approve, or merge PRs. It pushes a branch and hands the PR to the human.
- Does not edit `DEVLOG.md` lines it didn't write, `contracts/CHANGELOG.md` entries it didn't write, or any file under `.github/` unless on a `battlefield/` or `chore/` branch owned by Ad.
- Does not commit secrets. If it finds one in the working tree, it says so and stops.
- Writes commit messages in the convention above and includes its attribution trailer.
- Orchestrators spawning subagents follow `AGENTS.md` §10: one worktree per implementer,
  subagents commit but never push, the orchestrator reviews and pushes.
- `.claude/settings.json` (committed) denies force-push, hard reset, clean, amend, branch -D,
  PR merge/approve, `rm -rf`, volume wipes, and reading/writing `.env`. A denial is the answer,
  not an obstacle.
- When a test fails that it did not cause, it reports it rather than "fixing" by deleting or skipping the test.

## 8. Recovery

- Pushed to the wrong branch: don't force-push. Cherry-pick onto the right branch, then revert on the wrong one via PR.
- Merged something broken: `git revert` via a `chore/revert-<pr>` PR. Never rewrite `main`.
- Leaked a secret: rotate the key first (the key is burned the moment it's pushed), then clean history with Ad.
- Conflict on `DEVLOG.md`: keep both sides, both lines.

## 9. Repo settings (Ad applies on creation — full list in `deploy/OWNER-CHECKLIST.md`)

- Branch protection on `main`: require PR, require 1 CODEOWNER review, require status checks (`python`, `frontend`, `ownership-guard`, `contracts-guard`), dismiss stale approvals, no force pushes, no deletions, include administrators.
- Merge: squash only; auto-delete head branches.
- Secrets: `FACTORY_API_KEY` etc. live in GitHub Actions secrets only if CI ever needs them (it currently doesn't).
