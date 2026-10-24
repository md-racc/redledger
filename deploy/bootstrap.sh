#!/usr/bin/env bash
# One-time VM setup (Ubuntu 22.04/24.04 on Vultr). Run as root. Owner: Dev Ad.
#   curl -fsSL https://raw.githubusercontent.com/<org>/redledger/main/deploy/bootstrap.sh | bash -s -- <org>/redledger <domain>
set -euo pipefail
REPO="${1:?github org/repo}"; DOMAIN="${2:?domain}"
apt-get update -qq && apt-get install -y -qq ca-certificates curl git ufw
curl -fsSL https://get.docker.com | sh
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw --force enable
useradd -m -s /bin/bash -G docker deploy 2>/dev/null || true
mkdir -p /opt/redledger && chown deploy:deploy /opt/redledger
sudo -u deploy git clone "https://github.com/$REPO.git" /opt/redledger || true
cd /opt/redledger
[ -f .env ] || sudo -u deploy cp .env.example .env
sudo -u deploy sed -i "s|^INTERNAL_TOKEN=.*|INTERNAL_TOKEN=$(openssl rand -hex 24)|" .env
sudo -u deploy bash -c "grep -q '^GITHUB_REPO=' .env || echo 'GITHUB_REPO=$REPO' >> .env"
sudo -u deploy bash -c "grep -q '^DOMAIN=' .env || echo 'DOMAIN=$DOMAIN' >> .env"
sudo -u deploy bash -c "sed -i 's|^CORS_ORIGINS=.*|CORS_ORIGINS=https://app.$DOMAIN,https://<pages-project>.pages.dev,http://localhost:3000|' .env"
echo
echo "Now: (1) put FACTORY_API_KEY and BLUE_GATE_LLM_* in /opt/redledger/.env"
echo "     (2) add the deploy user's SSH public key to GitHub secrets as VULTR_SSH_KEY (private half), VULTR_HOST=<ip>, VULTR_USER=deploy"
echo "     (3) docker login ghcr.io as deploy once (read:packages PAT) so compose can pull"
echo "     (4) push to main → deploy.yml does the rest"
