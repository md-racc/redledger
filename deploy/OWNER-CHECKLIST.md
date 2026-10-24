# Owner checklist (Ad) — do these before anyone's agent touches the repo

In order. ~45 minutes. Items marked ⚑ are the ones that bite if skipped.

## 1. Repo (10 min)

- [ ] Unzip, `git init`, first commit `chore: scaffold`, push `main`.
- [x] `.github/CODEOWNERS` has real handles (Ad=@md-racc, Al=@Alex-Epstein, M=@moterodiaz, R=@RaagaSundar). It is routing/notification only: owners get auto-requested; it gates nothing.
- [x] ⚑ Branch protection on `main`: require a pull request; **0 approvals; code-owner review off** (integration merges; GIT.md §4);
  require status checks by their real job names: `python (agentkit)`, `python (battlefield)`, `python (red)`, `python (green)`, `python (blue)`, `frontend`, `ownership-guard`, `contracts-guard` (skipped = pass);
  do not allow force pushes; do not allow deletions; **include administrators**.
- [x] Ad's machine only: a local, **uncommitted** removal of the `gh pr merge*` deny in `.claude/settings.json` so the orchestrator can merge (`git update-index --skip-worktree .claude/settings.json`). Never commit it; teammates keep the committed denies.
- [x] Integration loop (AGENTS.md §10, GIT.md §4): PR steward subagent polls and assesses; an independent verifier reviews core/cross-area PRs; merge with `gh pr merge --squash --match-head-commit <assessed sha>`; resync PR branches with plain merges of `origin/main`, never force.
- [ ] Settings → General → Pull Requests: allow **squash merging only**; default to PR title + description; **automatically delete head branches**.
- [ ] Settings → Actions → General: allow GitHub Actions; workflow permissions "Read and write" (deploy.yml pushes to GHCR).
- [ ] Add collaborators Al, M, R with Write (not Admin). You stay the only admin.

## 2. Secrets and variables (10 min)

Images carry no secrets. The deploy job renders `/opt/redledger/.env` on the VM from the
`production` environment on every deploy (`deploy/render-env.sh`); nobody edits that file by hand.

Repo → Settings → Secrets and variables → Actions → **Repository** secrets (deploy plumbing only):
- [ ] `VULTR_HOST`, `VULTR_USER` (`deploy`), `VULTR_SSH_KEY` (private key the VM's `deploy` user accepts). Nothing else at repo level.

Repo → Settings → Environments → **New environment** `production`:
- [ ] ⚑ Deployment protection: **required reviewer = Ad**. Deployment branches: `main` only.
- [ ] Environment **secrets**:
  - `AGENT_TOKEN`, `OPERATOR_TOKEN`: `openssl rand -hex 32` each, two different values (render-env refuses equal or empty tokens).
  - `FACTORY_API_KEY`: the dedicated prod key. ⚑ It goes here and nowhere else: not in a teammate's `.env`, not in chat. Each dev uses their own key locally.
  - `BLUE_GATE_LLM_API_KEY`, `CRS_API_KEY`, `CARTESIA_API_KEY` (leave unset if unused).
- [ ] Environment **variables**:
  - `DROID_MODEL_RED`, `DROID_MODEL_GREEN`, `DROID_MODEL_BLUE`: pinned prod models (never `auto`).
  - `DROID_REASONING_RED`, `DROID_REASONING_GREEN`, `DROID_REASONING_BLUE`: optional reasoning effort, one of `none|off|minimal|low|medium|high|xhigh|max` (leave unset for the model default). A bad value stops that agent at startup.
  - `BLUE_GATE_LLM_PROVIDER`, `BLUE_GATE_LLM_MODEL`.
  - `MAX_CREDITS_PER_EPISODE`: e.g. `40`. Battlefield pauses an episode that reaches it; `0` disables.
  - `DOMAIN`: e.g. `example.com` (Caddy serves `api.` and `app.` under it).
  - (`GITHUB_REPO` is not a variable: GitHub reserves the `GITHUB_` prefix, so deploy.yml passes `github.repository`, the same name the build job tags images with. It must be lowercase for GHCR.)
  - `CORS_ORIGINS`: e.g. `https://app.<domain>,https://<pages-project>.pages.dev` (defaults to `https://app.<domain>`).
  - `NEXT_PUBLIC_WS_URL`: `wss://api.<domain>` (the default if unset).
- [ ] Repo → Settings → Secrets and variables → Actions → **Repository variables**: `DEPLOY_ENABLED=true`, but only once the VM in §3 is up. Until then merges to `main` build and push images and skip the SSH roll.
- [ ] Rotation = change the secret in the environment, then re-run deploy.yml. Rotating `AGENT_TOKEN`/`OPERATOR_TOKEN` restarts every service with the new value; nothing else to touch.

## 3. VM (15 min, can run in parallel with §1)

- [ ] Vultr: Ubuntu 24.04, 2 vCPU / 4 GB is enough; attach your SSH key.
- [ ] `curl -fsSL https://raw.githubusercontent.com/<org>/redledger/main/deploy/bootstrap.sh | bash -s -- <org>/redledger <domain>`. It installs Docker, creates `deploy`, clones to `/opt/redledger`. It does not write `.env`; the first deploy renders it.
- [ ] Add the `deploy` user's public key to `~deploy/.ssh/authorized_keys`; its private half is `VULTR_SSH_KEY` (§2).
- [ ] As `deploy`: `docker login ghcr.io` with a classic PAT scoped `read:packages` (or make the five packages public after the first build).
- [ ] Cloudflare DNS: `A api.<domain> → <ip>`, `A app.<domain> → <ip>`. If proxied, SSL mode "Full (strict)". Cloudflare Access on `app.` and `api.` is cheap insurance for the weekend.
- [ ] Set `DEPLOY_ENABLED=true` (§2), then `workflow_dispatch` deploy.yml once and approve the `production` deployment. Confirm `/opt/redledger/.env` exists with mode 600 (`ls -l`, don't `cat` it), `https://api.<domain>/` returns `{"service":"battlefield"...}`, and `/docs` renders.

## 4. First run (10 min) ⚑

Do this locally before anyone else starts; it's the proof the skeleton holds.
- [ ] `cp .env.example .env`, set `AGENT_TOKEN` and `OPERATOR_TOKEN` to two different strings; your own `FACTORY_API_KEY` or `DRY_RUN=true`.
- [ ] `make mock-agents` → `make episode MODE=enforce SEED=42 DAYS=4` → `make score EP=<id>`. Expect ~4 attacks, ≥3 caught, $0 extracted, 0 legit blocked.
- [ ] `make record EP=<id>` and commit the fixture if it differs meaningfully from `sample-enforce-4d.jsonl`.
- [ ] Open `http://localhost:8000/docs`. That URL goes in the team channel; it's what R and M will stare at.
- [ ] ⚑ Verify the Droid CLI install line in `red/Dockerfile` against docs.factory.com and fix it in all three agent Dockerfiles. Record the working line in `contracts/CHANGELOG.md` Findings. This is the one line in the repo I wrote from memory.
- [x] ~~Root uv workspace~~ removed (2026-10-23): it conflicted with each service's `agentkit = { path = "../agentkit" }` source and broke `uv sync` in every service. Each service syncs on its own (`make install`).

## 5. Hand-off (5 min)

- [ ] Post in the team channel: repo link, `/docs` link, the dev→directory table (README §0), and "your first message to your agent is the paste block at the bottom of your directory's AGENTS.md".
- [ ] Each teammate: clone, `cp .env.example .env`, pick any two different local `AGENT_TOKEN`/`OPERATOR_TOKEN` values (they never leave their machine), put in their own `FACTORY_API_KEY` (or `DRY_RUN=true`), `make mock-agents`, then let their agent read their directory. Prod tokens and the prod Factory key are never handed out.
- [ ] Create the four initial branches yourself so the first PRs have the right prefixes without anyone thinking: `red/scaffold-check`, `green/scaffold-check`, `blue/scaffold-check`, `frontend/scaffold-check`. Their first PR is "make the tests pass in my worktree and append a DEVLOG line". It exercises CI, CODEOWNERS, and the ownership guard on something trivial.

## 6. Things that will come to you anyway

- Contracts PRs. Ask "could this be an extension instead?" first (README §16). Verifier pass, then merge on owner authority and post an FYI in the PR + team channel; owners object with a follow-up contracts PR.
- `make db-reset` requests after a schema change. Record fixtures before wiping the staging DB.
- Factory credit burn. `turn.ended` events carry `factory_credits`; `GET /api/fe/episodes/{ep}/agents/activity` sums them. Check it Saturday afternoon. `MAX_CREDITS_PER_EPISODE` pauses a runaway episode (`error` event, `where: credit_guard`); resume it by hand.
- The scoring gap for `bank_swap` (battlefield/AGENTS.md → Known gaps). M will hit it the moment blue blocks a vendor change correctly and gets no credit.
