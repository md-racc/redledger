#!/bin/sh
# Render the VM's .env from the process environment. Owner: Dev Ad.
# Run by .github/workflows/deploy.yml (roll job) from /opt/redledger, with the GitHub
# `production` environment's secrets and variables exported by appleboy/ssh-action.
#   deploy/render-env.sh [output-path]      # default: .env in the current directory
# Writes atomically (temp file in the same directory, then mv) with mode 600. Refuses to write
# anything if AGENT_TOKEN or OPERATOR_TOKEN is empty or the two are equal. Per-agent tokens
# (contracts/agent-service.md "Tokens"): AGENT_TOKEN_RED/GREEN/BLUE are all-or-none; when set they
# must be pairwise distinct and distinct from OPERATOR_TOKEN, else refuse. When none is set, all
# three fall back to the shared AGENT_TOKEN (warning: per-agent separation off). Never prints values,
# only variable names.
set -eu
umask 077

out="${1:-.env}"
dir=$(dirname -- "$out")

die() { printf 'render-env: %s\n' "$*" >&2; exit 1; }

[ -n "${AGENT_TOKEN:-}" ] || die "AGENT_TOKEN is empty; refusing to write $out"
[ -n "${OPERATOR_TOKEN:-}" ] || die "OPERATOR_TOKEN is empty; refusing to write $out"
[ "$AGENT_TOKEN" != "$OPERATOR_TOKEN" ] || die "AGENT_TOKEN equals OPERATOR_TOKEN; refusing to write $out"
# No token may be whitespace-only (it would look set but authenticate nothing sensible).
for pair in "AGENT_TOKEN:${AGENT_TOKEN:-}" "OPERATOR_TOKEN:${OPERATOR_TOKEN:-}" "AGENT_TOKEN_RED:${AGENT_TOKEN_RED:-}" \
  "AGENT_TOKEN_GREEN:${AGENT_TOKEN_GREEN:-}" "AGENT_TOKEN_BLUE:${AGENT_TOKEN_BLUE:-}"; do
  v=${pair#*:}
  [ -z "$v" ] && continue
  case "$v" in
    *[![:space:]]*) ;;
    *) die "${pair%%:*} is whitespace only; refusing to write $out" ;;
  esac
done
# Per-agent tokens: all three or none.
n_agent_tokens=0
for t in "${AGENT_TOKEN_RED:-}" "${AGENT_TOKEN_GREEN:-}" "${AGENT_TOKEN_BLUE:-}"; do
  [ -z "$t" ] || n_agent_tokens=$((n_agent_tokens + 1))
done
case "$n_agent_tokens" in
  0)
    printf 'render-env: AGENT_TOKEN_RED/GREEN/BLUE unset; all agents share AGENT_TOKEN (per-agent separation off)\n' >&2
    token_red=$AGENT_TOKEN token_green=$AGENT_TOKEN token_blue=$AGENT_TOKEN
    ;;
  3)
    token_red=$AGENT_TOKEN_RED token_green=$AGENT_TOKEN_GREEN token_blue=$AGENT_TOKEN_BLUE
    [ "$token_red" != "$token_green" ] || die "AGENT_TOKEN_RED equals AGENT_TOKEN_GREEN; refusing to write $out"
    [ "$token_red" != "$token_blue" ] || die "AGENT_TOKEN_RED equals AGENT_TOKEN_BLUE; refusing to write $out"
    [ "$token_green" != "$token_blue" ] || die "AGENT_TOKEN_GREEN equals AGENT_TOKEN_BLUE; refusing to write $out"
    for pair in "RED:$token_red" "GREEN:$token_green" "BLUE:$token_blue"; do
      [ "${pair#*:}" != "$OPERATOR_TOKEN" ] || die "AGENT_TOKEN_${pair%%:*} equals OPERATOR_TOKEN; refusing to write $out"
      # the shared AGENT_TOKEN is still rendered (fallback for anything that reads it), so it must not
      # double as one agent's token
      [ "${pair#*:}" != "$AGENT_TOKEN" ] || die "AGENT_TOKEN_${pair%%:*} equals the shared AGENT_TOKEN; refusing to write $out"
    done
    ;;
  *) die "set all of AGENT_TOKEN_RED, AGENT_TOKEN_GREEN, AGENT_TOKEN_BLUE or none of them; refusing to write $out" ;;
esac
# ADMIN_KEY gates every mutation through the frontend's operator proxy (frontend/AGENTS.md "Viewers and
# admins"). When set it must be long and must not double as any token.
if [ -n "${ADMIN_KEY:-}" ]; then
  case "$ADMIN_KEY" in *[![:space:]]*) ;; *) die "ADMIN_KEY is whitespace only; refusing to write $out" ;; esac
  [ "${#ADMIN_KEY}" -ge 32 ] || die "ADMIN_KEY is shorter than 32 characters; refusing to write $out"
  for t in "${AGENT_TOKEN:-}" "${OPERATOR_TOKEN:-}" "${AGENT_TOKEN_RED:-}" "${AGENT_TOKEN_GREEN:-}" "${AGENT_TOKEN_BLUE:-}"; do
    [ "$ADMIN_KEY" != "$t" ] || die "ADMIN_KEY equals a token; refusing to write $out"
  done
fi
# A public deploy (DOMAIN set) must either verify the Cloudflare Access JWT at the origin (both CF_ACCESS_*
# set) or run public read-only with ADMIN_KEY gating every mutation (both CF_ACCESS_* empty). A partial
# Access config, or Access off without ADMIN_KEY, would leave the operator proxy open. Fail closed.
if [ -n "${DOMAIN:-}" ]; then
  if [ -n "${CF_ACCESS_TEAM_DOMAIN:-}" ] || [ -n "${CF_ACCESS_AUD:-}" ]; then
    [ -n "${CF_ACCESS_TEAM_DOMAIN:-}" ] || die "DOMAIN is set but CF_ACCESS_TEAM_DOMAIN is empty; refusing to write $out"
    [ -n "${CF_ACCESS_AUD:-}" ] || die "DOMAIN is set but CF_ACCESS_AUD is empty; refusing to write $out"
  else
    [ -n "${ADMIN_KEY:-}" ] || die "DOMAIN is set with Cloudflare Access off (CF_ACCESS_* empty) but ADMIN_KEY is empty; refusing to write $out"
    printf 'render-env: warning: Cloudflare Access off; the site is public read-only and only ADMIN_KEY holders can act\n' >&2
  fi
fi

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
emit AGENT_TOKEN_RED "$token_red"
emit AGENT_TOKEN_GREEN "$token_green"
emit AGENT_TOKEN_BLUE "$token_blue"
emit OPERATOR_TOKEN "$OPERATOR_TOKEN"
emit FACTORY_API_KEY "${FACTORY_API_KEY:-}"
emit BLUE_GATE_LLM_API_KEY "${BLUE_GATE_LLM_API_KEY:-}"
emit CRS_USERNAME "${CRS_USERNAME:-}"
emit CRS_PASSWORD "${CRS_PASSWORD:-}"
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
# blank = model default; agents reject anything outside none|off|minimal|low|medium|high|xhigh|max at startup
emit DROID_REASONING_RED "${DROID_REASONING_RED:-}"
emit DROID_REASONING_GREEN "${DROID_REASONING_GREEN:-}"
emit DROID_REASONING_BLUE "${DROID_REASONING_BLUE:-}"
emit BLUE_GATE_LLM_PROVIDER "${BLUE_GATE_LLM_PROVIDER:-gemini}"
emit BLUE_GATE_LLM_MODEL "${BLUE_GATE_LLM_MODEL:-}"
emit DRY_RUN "${DRY_RUN:-false}"
# per-agent overrides, resolved here so compose never depends on nested defaults; blank = DRY_RUN
emit DRY_RUN_RED "${DRY_RUN_RED:-${DRY_RUN:-false}}"
emit DRY_RUN_GREEN "${DRY_RUN_GREEN:-${DRY_RUN:-false}}"
emit DRY_RUN_BLUE "${DRY_RUN_BLUE:-${DRY_RUN:-false}}"
emit CF_ACCESS_TEAM_DOMAIN "${CF_ACCESS_TEAM_DOMAIN:-}"
emit CF_ACCESS_AUD "${CF_ACCESS_AUD:-}"
emit ADMIN_KEY "${ADMIN_KEY:-}"

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
