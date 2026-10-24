#!/bin/sh
# Render the VM's .env from the process environment. Owner: Dev Ad.
# Run by .github/workflows/deploy.yml (roll job) from /opt/redledger, with the GitHub
# `production` environment's secrets and variables exported by appleboy/ssh-action.
#   deploy/render-env.sh [output-path]      # default: .env in the current directory
# Writes atomically (temp file in the same directory, then mv) with mode 600. Refuses to write
# anything if AGENT_TOKEN or OPERATOR_TOKEN is empty or the two are equal. Never prints values,
# only variable names.
set -eu
umask 077

out="${1:-.env}"
dir=$(dirname -- "$out")

die() { printf 'render-env: %s\n' "$*" >&2; exit 1; }

[ -n "${AGENT_TOKEN:-}" ] || die "AGENT_TOKEN is empty; refusing to write $out"
[ -n "${OPERATOR_TOKEN:-}" ] || die "OPERATOR_TOKEN is empty; refusing to write $out"
[ "$AGENT_TOKEN" != "$OPERATOR_TOKEN" ] || die "AGENT_TOKEN equals OPERATOR_TOKEN; refusing to write $out"

# Defaults that depend on DOMAIN (set as a `production` environment variable).
if [ -n "${DOMAIN:-}" ]; then
  cors_default="https://app.${DOMAIN}"
  ws_default="wss://api.${DOMAIN}"
else
  cors_default="http://localhost:3000"
  ws_default="ws://localhost:8000"
fi

tmp=$(mktemp "${dir}/.env.render.XXXXXX")
trap 'rm -f "$tmp"' EXIT
trap 'exit 1' HUP INT TERM

written=""
# emit NAME VALUE: append NAME='VALUE' to the temp file. Single quotes make compose read the value
# literally (no ${...} interpolation). Values with a single quote or a newline can't be written
# safely in that form, so they abort the render.
emit() {
  case "$2" in
    *"'"*) die "$1 contains a single quote; refusing to write $out" ;;
  esac
  nl='
'
  case "$2" in
    *"$nl"*) die "$1 contains a newline; refusing to write $out" ;;
  esac
  printf "%s='%s'\n" "$1" "$2" >>"$tmp"
  written="${written} $1"
}

printf '# Rendered by deploy/render-env.sh. Do not edit by hand; the next deploy overwrites it.\n' >"$tmp"

# ---- tokens and secrets ----
emit AGENT_TOKEN "$AGENT_TOKEN"
emit OPERATOR_TOKEN "$OPERATOR_TOKEN"
emit FACTORY_API_KEY "${FACTORY_API_KEY:-}"
emit BLUE_GATE_LLM_API_KEY "${BLUE_GATE_LLM_API_KEY:-}"
emit CRS_API_KEY "${CRS_API_KEY:-}"
emit CARTESIA_API_KEY "${CARTESIA_API_KEY:-}"

# ---- deployment variables ----
emit DOMAIN "${DOMAIN:-}"
emit GITHUB_REPO "${GITHUB_REPO:-}"
emit CORS_ORIGINS "${CORS_ORIGINS:-$cors_default}"
emit NEXT_PUBLIC_WS_URL "${NEXT_PUBLIC_WS_URL:-$ws_default}"
emit NEXT_PUBLIC_MOCK "${NEXT_PUBLIC_MOCK:-false}"
emit MAX_CREDITS_PER_EPISODE "${MAX_CREDITS_PER_EPISODE:-0}"
emit DROID_MODEL_RED "${DROID_MODEL_RED:-}"
emit DROID_MODEL_GREEN "${DROID_MODEL_GREEN:-}"
emit DROID_MODEL_BLUE "${DROID_MODEL_BLUE:-}"
emit BLUE_GATE_LLM_PROVIDER "${BLUE_GATE_LLM_PROVIDER:-gemini}"
emit BLUE_GATE_LLM_MODEL "${BLUE_GATE_LLM_MODEL:-}"
emit DRY_RUN "${DRY_RUN:-false}"

# ---- non-secret defaults (match .env.example) ----
emit EPISODE_DEFAULT_DAYS "${EPISODE_DEFAULT_DAYS:-10}"
emit TURN_TIMEOUT_SEC "${TURN_TIMEOUT_SEC:-180}"
emit GATE_TIMEOUT_SEC "${GATE_TIMEOUT_SEC:-8}"
emit ESCALATION_TIMEOUT_SEC "${ESCALATION_TIMEOUT_SEC:-90}"
emit FP_PENALTY_RATE "${FP_PENALTY_RATE:-0.02}"
emit APPROVAL_THRESHOLD "${APPROVAL_THRESHOLD:-5000}"
emit DAY_PAUSE_SEC "${DAY_PAUSE_SEC:-0}"
emit LOG_LEVEL "${LOG_LEVEL:-info}"
emit POSTGRES_IMAGE "${POSTGRES_IMAGE:-postgres:16-alpine}"

[ -n "${GITHUB_REPO:-}" ] || printf 'render-env: warning: GITHUB_REPO is empty; image refs will not resolve\n' >&2
[ -n "${DOMAIN:-}" ] || printf 'render-env: warning: DOMAIN is empty; Caddy will not serve api./app.\n' >&2

chmod 600 "$tmp"
mv -f "$tmp" "$out"
trap - EXIT
printf 'render-env: wrote %s with:%s\n' "$out" "$written"
