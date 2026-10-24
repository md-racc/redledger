# Owner checklist (Ad) — do these before anyone's agent touches the repo

In order. ~45 minutes. Items marked ⚑ are the ones that bite if skipped.

## 1. Repo (10 min)

- [ ] Unzip, `git init`, first commit `chore: scaffold`, push `main`.
- [ ] ⚑ Replace `@AD_HANDLE @AL_HANDLE @M_HANDLE @R_HANDLE` in `.github/CODEOWNERS` with real GitHub usernames. CODEOWNERS with fake handles silently requires no one.
- [ ] ⚑ Branch protection on `main` (Settings → Branches → Add rule, pattern `main`):
  require a pull request; require 1 approval; **require review from Code Owners**; dismiss stale approvals;
  require status checks `python`, `frontend`, `ownership-guard`, `contracts-guard` (they appear after the first PR runs CI);
  do not allow force pushes; do not allow deletions; **include administrators**.
- [ ] Settings → General → Pull Requests: allow **squash merging only**; default to PR title + description; **automatically delete head branches**.
- [ ] Settings → Actions → General: allow GitHub Actions; workflow permissions "Read and write" (deploy.yml pushes to GHCR).
- [ ] Add collaborators Al, M, R with Write (not Admin). You stay the only admin.

## 2. Secrets and variables (5 min)

Repo → Settings → Secrets and variables → Actions.
- [ ] Secrets: `VULTR_HOST`, `VULTR_USER` (`deploy`), `VULTR_SSH_KEY` (private key the VM's `deploy` user accepts), `NEXT_PUBLIC_INTERNAL_TOKEN` (same value as `INTERNAL_TOKEN` in the VM's `.env`).
- [ ] Variables: `NEXT_PUBLIC_BATTLEFIELD_URL=https://api.<domain>`, `NEXT_PUBLIC_WS_URL=wss://api.<domain>`.
- [ ] Nothing else goes in GitHub. `FACTORY_API_KEY` and LLM keys live only in `/opt/redledger/.env` on the VM and in teammates' local `.env` files, handed over out of band.

## 3. VM (15 min, can run in parallel with §1)

- [ ] Vultr: Ubuntu 24.04, 2 vCPU / 4 GB is enough; attach your SSH key.
- [ ] `curl -fsSL https://raw.githubusercontent.com/<org>/redledger/main/deploy/bootstrap.sh | bash -s -- <org>/redledger <domain>`
- [ ] Fill `/opt/redledger/.env`: `FACTORY_API_KEY`, `DROID_MODEL_*`, `BLUE_GATE_LLM_*`, `CORS_ORIGINS`.
- [ ] As `deploy`: `docker login ghcr.io` with a classic PAT scoped `read:packages` (or make the five packages public after the first build).
- [ ] Cloudflare DNS: `A api.<domain> → <ip>`, `A app.<domain> → <ip>`. If proxied, SSL mode "Full (strict)". Cloudflare Access on `app.` and `api.` is cheap insurance for the weekend.
- [ ] `workflow_dispatch` deploy.yml once; confirm `https://api.<domain>/` returns `{"service":"battlefield"...}` and `/docs` renders.

## 4. First run (10 min) ⚑

Do this locally before anyone else starts; it's the proof the skeleton holds.
- [ ] `cp .env.example .env`, set `INTERNAL_TOKEN`.
- [ ] `make mock-agents` → `make episode MODE=enforce SEED=42 DAYS=4` → `make score EP=<id>`. Expect ~4 attacks, ≥3 caught, $0 extracted, 0 legit blocked.
- [ ] `make record EP=<id>` and commit the fixture if it differs meaningfully from `sample-enforce-4d.jsonl`.
- [ ] Open `http://localhost:8000/docs`. That URL goes in the team channel; it's what R and M will stare at.
- [ ] ⚑ Verify the Droid CLI install line in `red/Dockerfile` against docs.factory.com and fix it in all three agent Dockerfiles. Record the working line in `contracts/CHANGELOG.md` Findings. This is the one line in the repo I wrote from memory.
- [x] ~~Root uv workspace~~ removed (2026-10-23): it conflicted with each service's `agentkit = { path = "../agentkit" }` source and broke `uv sync` in every service. Each service syncs on its own (`make install`).

## 5. Hand-off (5 min)

- [ ] Post in the team channel: repo link, `/docs` link, the dev→directory table (README §0), and "your first message to your agent is the paste block at the bottom of your directory's AGENTS.md".
- [ ] Each teammate: clone, `cp .env.example .env`, paste `INTERNAL_TOKEN` you give them, `make mock-agents`, then let their agent read their directory.
- [ ] Create the four initial branches yourself so the first PRs have the right prefixes without anyone thinking: `red/scaffold-check`, `green/scaffold-check`, `blue/scaffold-check`, `frontend/scaffold-check`. Their first PR is "make the tests pass in my worktree and append a DEVLOG line". It exercises CI, CODEOWNERS, and the ownership guard on something trivial.

## 6. Things that will come to you anyway

- Contracts PRs. Review fast; they block people. Ask "could this be an extension instead?" first (README §16).
- `make db-reset` requests after a schema change. Record fixtures before wiping the staging DB.
- Factory credit burn. `turn.ended` events carry `factory_credits`; `GET /api/fe/episodes/{ep}/agents/activity` sums them. Check it Saturday afternoon.
- The scoring gap for `bank_swap` (battlefield/AGENTS.md → Known gaps). M will hit it the moment blue blocks a vendor change correctly and gets no credit.
