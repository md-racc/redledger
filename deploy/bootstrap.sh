#!/usr/bin/env bash
# One-time VM setup (Ubuntu 22.04/24.04 on Vultr). Run as root. Owner: Dev Ad.
#   curl -fsSL https://raw.githubusercontent.com/<org>/redledger/main/deploy/bootstrap.sh | bash -s -- <org>/redledger [<domain>]
# Installs Docker, opens 80/443, creates the `deploy` user, clones the repo to /opt/redledger.
# It does NOT write /opt/redledger/.env: the first deploy renders it (deploy/render-env.sh) from
# the GitHub `production` environment, and every later deploy re-renders it. Don't edit it by hand.
set -euo pipefail
REPO="${1:?github org/repo}"; DOMAIN="${2:-<domain>}"
apt-get update -qq && apt-get install -y -qq ca-certificates curl git ufw
curl -fsSL https://get.docker.com | sh
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw --force enable
useradd -m -s /bin/bash -G docker deploy 2>/dev/null || true
mkdir -p /opt/redledger && chown deploy:deploy /opt/redledger
sudo -u deploy git clone "https://github.com/$REPO.git" /opt/redledger || true
echo
echo "Now: (1) add the deploy user's SSH key: public half in ~deploy/.ssh/authorized_keys; repo secrets VULTR_SSH_KEY (private half), VULTR_HOST=<ip>, VULTR_USER=deploy"
echo "     (2) fill the GitHub 'production' environment (secrets + variables, DOMAIN=$DOMAIN) per OPERATIONS.md (Environment variables)"
echo "     (3) docker login ghcr.io as deploy once (read:packages PAT) so compose can pull"
echo "     (4) set repo variable DEPLOY_ENABLED=true, then run deploy.yml (workflow_dispatch); it renders .env and rolls the stack"
