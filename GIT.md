# GIT.md — maintenance workflow

Red Ledger is a completed hackathon project maintained by Ad (@md-racc). Preserve the final
submission and its evidence while keeping local reproduction usable.

## 1. Branches and commits

- `main` is protected; changes land through PRs. Start topic branches from current `origin/main`.
- Use a descriptive prefix such as `docs/`, `chore/`, `frontend/`, `battlefield/`, `red/`,
  `green/`, `blue/`, or `contracts/`. Prefixes describe the change; they do not restrict paths.
- Keep each PR focused. Cross-area maintenance is allowed when its scope is explicit.
- Commit messages use a lower-case area and imperative summary, for example
  `docs: document local reproduction` or `blue: narrow duplicate detection`.
- Never force-push or rewrite shared history. Resolve conflicts with a plain merge from
  `origin/main`. Do not destroy another person's uncommitted work.
- Never commit `.env`, tokens, keys, dependencies, virtual environments, Factory sessions or
  recorded fixtures containing secrets. Do not bypass `.gitignore` to include them.

## 2. Contracts and extensions

`contracts/` is authoritative. Core contract changes require a `contracts/CHANGELOG.md` entry
and review of all affected services before dependent code lands. CI retains `contracts-guard`.
The existing extension namespaces remain `contracts/ext/{red,green,blue,fe}/` and
`battlefield/extensions/{red_,green_,blue_,fe_}*.py`; they do not authorize changes to core API
shapes without a contract update. `contracts/schema.sql` is the schema source; never edit a
generated copy in `battlefield/db/`.

## 3. Pull requests and merging

Describe the problem, resulting behavior and validation. Link related issues and disclose
limitations. Run affected lint/tests, preserve `DRY_RUN=true` and `NEXT_PUBLIC_MOCK=true`, and
keep environment documentation current. Do not delete or skip tests to hide a failure.

Passing CI is required. Security, contracts, core runtime, deployment and cross-service changes
also require independent review of the final diff. A coordinating agent may merge only with
explicit maintainer authorization, after that independent review and checks pass. Pin the
reviewed head: `gh pr merge <n> --squash --match-head-commit <reviewed-sha>`. A newer head
requires reassessment. Squash-merge and delete merged topic branches.

CODEOWNERS routes maintenance review to @md-racc. Original author credits remain in README.
The `ownership-guard` check name is retained for branch-protection compatibility, but no longer
enforces team ownership prefixes or devlog fragments. It can be removed from required checks
in a separate settings change before the compatibility job is removed.

## 4. Historical development log

`DEVLOG.md` and existing `devlog/` fragments are hackathon history. Preserve them; do not append
to `DEVLOG.md` or edit other people's entries. New fragments are optional. `make devlog` and
`make devlog-show` remain available for browsing or adding a maintenance note. PR descriptions
are the record of new maintenance work.

## 5. Hosting and releases

The public hosting is retired; screenshots, recordings and local setup are the supported
showcase. CI continues to run on PRs and `main`. The historical deploy workflow is manual only,
requires explicit confirmation before even building/publishing images, and still requires
`DEPLOY_ENABLED=true` and production environment approval before rollout. Routine maintenance
must not redeploy it. Infrastructure deletion and credential retirement are separate actions.

Publish releases only with maintainer authorization, from a reviewed, checked commit. Identify
the preserved hackathon submission separately from later cleanup, and describe known limitations.

## 6. Recovery

Revert a broken merge through a PR; never rewrite `main`. If a secret leaks, notify the
maintainer immediately so it can be rotated before any history cleanup. Destructive commands
and tool approval denials remain subject to their existing protections.

## 7. Coding agents

Read the root and service guides before editing. State scope, use a topic branch and preserve
unrelated work. For parallel work use one worktree per implementer and explicit file lists;
implementers commit and report, the coordinator publishes only when authorized. A fresh
reviewer checks the final diff independently. Do not access production or edit `.env` during
routine maintenance. Do not bypass `.claude/settings.json` denials or commit local overrides.
Report unrelated test failures and external blockers without abandoning independent work.
