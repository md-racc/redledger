#!/usr/bin/env bash
# Drive the prod stack from your laptop without the operator token ever leaving the VM.
# Owner: Dev Ad. Guide: deploy/PROD-OPS.md. Make wrappers: `make help | grep prod-`.
#
#   deploy/prod.sh health | ps | logs [SVC]
#   deploy/prod.sh episode MODE SEED DAYS [ATTACK_PLAN_JSON]    # create + start; stdout = episode id
#   deploy/prod.sh step|pause|resume|score|wait|credits EP
#   deploy/prod.sh toggle EP off|shadow|enforce
#   deploy/prod.sh attack EP SCHEME [PARAMS_JSON]
#   deploy/prod.sh escalations [EP]
#   deploy/prod.sh resolve ESC approve|block
#   deploy/prod.sh record EP [NAME]          # -> battlefield/fixtures/episodes/<NAME or EP>.jsonl
#
# How the token stays on the VM: every API call is made by a fixed Python program (PROGRAM below)
# run INSIDE the battlefield container (`docker compose exec -T battlefield python3 ...`). It reads
# OPERATOR_TOKEN from the container's own environment and calls http://localhost:8000/api/...;
# the token is never in argv here, in the ssh command line, or in output (the program also
# replaces any token/key value of its environment with [REDACTED] before printing anything).
# User arguments never touch the program source or the remote shell: the program text and every
# argument travel base64-encoded (shell-safe alphabet, single-quoted) and are decoded in Python.
#
# Environment (all optional):
#   PROD_HOST (45.77.6.23)  PROD_USER (deploy)  PROD_KEY (~/.ssh/redledger_deploy)
#   PROD_DIR (/opt/redledger)  PROD_COMPOSE ("docker compose -f docker-compose.yml -f docker-compose.prod.yml")
#   PROD_BF_EXEC ("$PROD_COMPOSE exec -T battlefield") — prefix that runs argv inside battlefield
#   PROD_SSH  — transport override: a command that takes ONE argument, the shell command to run
#               on the VM. Default is ssh to $PROD_USER@$PROD_HOST. Local test: PROD_SSH="bash -c".
#   PROD_DRY=1 — print what would run (program elided, arguments decoded) and exit 0.
#   PROD_HTTP_TIMEOUT (30)  PROD_STEP_TIMEOUT (900: one live day is up to 3 turns + escalations)
#   PROD_WAIT_TIMEOUT (3600)  PROD_WAIT_INTERVAL (5)  PROD_CONNECT_TIMEOUT (10)  PROD_LOG_TAIL (200)
#   PROD_RESOLVE_BY (judge)  PROD_RECORD_OVERWRITE=1 — let `record` replace an existing fixture.
set -euo pipefail

PROD_HOST="${PROD_HOST:-45.77.6.23}"
PROD_USER="${PROD_USER:-deploy}"
PROD_KEY="${PROD_KEY:-$HOME/.ssh/redledger_deploy}"
PROD_DIR="${PROD_DIR:-/opt/redledger}"
PROD_COMPOSE="${PROD_COMPOSE:-docker compose -f docker-compose.yml -f docker-compose.prod.yml}"
PROD_BF_EXEC="${PROD_BF_EXEC:-$PROD_COMPOSE exec -T battlefield}"
HTTP_TIMEOUT="${PROD_HTTP_TIMEOUT:-30}"
STEP_TIMEOUT="${PROD_STEP_TIMEOUT:-900}"
WAIT_TIMEOUT="${PROD_WAIT_TIMEOUT:-3600}"
WAIT_INTERVAL="${PROD_WAIT_INTERVAL:-5}"
CONNECT_TIMEOUT="${PROD_CONNECT_TIMEOUT:-10}"
LOG_TAIL="${PROD_LOG_TAIL:-200}"
RESOLVE_BY="${PROD_RESOLVE_BY:-judge}"

REPO_ROOT="$(cd "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
FIXTURES_DIR="$REPO_ROOT/battlefield/fixtures/episodes"

die() { printf 'prod: %s\n' "$*" >&2; exit 1; }
usage() { sed -n '2,13p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' >&2; exit 2; }

is_uint() { [[ "$1" =~ ^[0-9]+$ ]]; }
for _n in HTTP_TIMEOUT STEP_TIMEOUT WAIT_TIMEOUT WAIT_INTERVAL CONNECT_TIMEOUT LOG_TAIL; do
  is_uint "${!_n}" || die "$_n must be a whole number of seconds/lines"
done
command -v timeout >/dev/null 2>&1 || die "needs coreutils 'timeout' (macOS: brew install coreutils, then put gnubin on PATH)"

# ---------------------------------------------------------------------------------------------
# The program run inside the battlefield container. Fixed text: user input arrives only as
# base64 argv, decoded below. stdlib only (the image is python:3.11-slim).
# argv: [-c, PROGRAM_B64, OP, HTTP_TIMEOUT_B64, ARG1_B64, ...]
# ---------------------------------------------------------------------------------------------
IFS= read -r -d '' PROGRAM <<'PY' || true
import base64, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request

API = os.environ.get("RL_OPS_API", "http://localhost:8000").rstrip("/")
TOKEN = os.environ.get("OPERATOR_TOKEN", "")
SECRETS = sorted(
    {v for k, v in os.environ.items() if re.search(r"TOKEN|KEY|SECRET|PASS", k) and len(v) >= 8},
    key=len, reverse=True,
)


def scrub(s):
    for v in SECRETS:
        s = s.replace(v, "[REDACTED]")
    return s


def out(s):
    sys.stdout.write(scrub(s) + "\n")
    sys.stdout.flush()


def err(s):
    sys.stderr.write(scrub(s) + "\n")
    sys.stderr.flush()


def fail(msg, code=1):
    err("prod(remote): " + msg)
    sys.exit(code)


OP = sys.argv[2]
ARGS = [base64.b64decode(a).decode() for a in sys.argv[3:]]
HTTP_TIMEOUT = float(ARGS.pop(0))
if not TOKEN:
    fail("OPERATOR_TOKEN is not set in the battlefield container's environment")


def seg(s):
    return urllib.parse.quote(s, safe="")


def call(method, path, body=None, query=None, timeout=None):
    url = API + "/api" + path + ("?" + urllib.parse.urlencode(query) if query else "")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", "Bearer " + TOKEN)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout or HTTP_TIMEOUT) as r:
            raw = r.read().decode()
    except urllib.error.HTTPError as e:
        fail("%s %s -> HTTP %s: %s" % (method, path, e.code, e.read().decode(errors="replace")[:2000]))
    except (urllib.error.URLError, OSError) as e:
        fail("%s %s -> %s" % (method, path, getattr(e, "reason", e)))
    return json.loads(raw) if raw else None


def show(obj):
    out(json.dumps(obj, indent=2, sort_keys=True, default=str))


def parse_json(s, kind, name):
    try:
        v = json.loads(s)
    except ValueError as e:
        fail("%s is not valid JSON: %s" % (name, e), 2)
    if not isinstance(v, kind):
        fail("%s must be a JSON %s" % (name, "array" if kind is list else "object"), 2)
    return v


def events(ep):
    after = 0
    while True:
        page = call("GET", "/events", query={"episode_id": ep, "after_id": after, "limit": 5000})
        for e in page:
            yield e
        if len(page) < 5000:
            return
        after = page[-1]["id"]


def num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


if OP == "health":
    show(call("GET", "/health"))
elif OP == "episode":
    mode, seed, days, plan = ARGS
    body = {"controller_mode": mode, "seed": int(seed), "days": int(days)}
    if plan.strip():
        body["attack_plan"] = parse_json(plan, list, "ATTACK_PLAN_JSON")
    ep = call("POST", "/episodes", body)
    call("POST", "/episodes/%s/start" % seg(ep["id"]))
    err("started %s: mode=%s seed=%s days=%s" % (ep["id"], ep.get("controller_mode"), ep.get("seed"), ep.get("days")))
    out(ep["id"])
elif OP == "post":  # step / pause / resume
    ep, action, timeout = ARGS
    show(call("POST", "/episodes/%s/%s" % (seg(ep), action), timeout=float(timeout)))
elif OP == "toggle":
    ep, mode = ARGS
    show(call("PATCH", "/episodes/%s/controller" % seg(ep), {"mode": mode}))
elif OP == "attack":
    ep, scheme, params = ARGS
    body = {"scheme_id": scheme, "params": parse_json(params or "{}", dict, "PARAMS_JSON")}
    show(call("POST", "/episodes/%s/attack" % seg(ep), body))
elif OP == "escalations":
    (ep,) = ARGS
    q = {"status": "open"}
    if ep:
        q["episode_id"] = ep
    show(call("GET", "/escalations", query=q))
elif OP == "resolve":
    esc, decision, by = ARGS
    show(call("POST", "/escalations/%s/resolve" % seg(esc), {"decision": decision, "by": by}))
elif OP == "score":
    (ep,) = ARGS
    show(call("GET", "/episodes/%s/score" % seg(ep)))
elif OP == "wait":
    ep, total, interval = ARGS
    deadline = time.monotonic() + float(total)
    last = None
    while True:
        e = call("GET", "/episodes/%s" % seg(ep))
        now = (e.get("status"), e.get("current_day"))
        if now != last:
            err("%s: %s, day %s/%s" % (ep, now[0], now[1], e.get("days")))
            last = now
        summary = {k: e.get(k) for k in ("id", "status", "current_day", "days", "controller_mode", "seed")}
        if now[0] == "finished":
            show(summary)
            sys.exit(0)
        if now[0] in ("failed", "paused", "created"):
            show(summary)
            fail("episode is %s; nothing will advance it (credit guard? run `credits`, then `resume`)" % now[0], 3)
        if time.monotonic() >= deadline:
            show(summary)
            fail("timed out after %ss" % total, 124)
        time.sleep(float(interval))
elif OP == "events":
    (ep,) = ARGS
    n = 0
    for e in events(ep):
        out(json.dumps(e))
        n += 1
    err("%d events" % n)
elif OP == "credits":
    (ep,) = ARGS
    agents, days, tripped = {}, {}, []
    for e in events(ep):
        p = e.get("payload") or {}
        if e.get("type") == "error" and p.get("where") == "credit_guard":
            tripped.append({"day": e.get("day"), "message": p.get("message")})
        if e.get("type") != "turn.ended":
            continue
        c = num(p.get("factory_credits"))
        a = agents.setdefault(p.get("agent") or "?", {"turns": 0, "priced_turns": 0, "credits": 0.0, "max_turn": 0.0})
        a["turns"] += 1
        if c is not None:
            a["priced_turns"] += 1
            a["credits"] += c
            a["max_turn"] = max(a["max_turn"], c)
            days[str(e.get("day"))] = days.get(str(e.get("day")), 0.0) + c
    for a in agents.values():
        a["avg_turn"] = round(a["credits"] / a["priced_turns"], 1) if a["priced_turns"] else 0.0
    total = sum(a["credits"] for a in agents.values())
    limit = num(float(os.environ.get("MAX_CREDITS_PER_EPISODE") or 0)) or 0.0
    show({
        "episode_id": ep,
        "total_credits": total,
        "max_credits_per_episode": limit,
        "remaining": (limit - total) if limit > 0 else None,
        "per_agent": agents,
        "per_day": days,
        "credit_guard_trips": tripped,
    })
else:
    fail("unknown op %r" % OP, 2)
PY

b64() { printf '%s' "$1" | base64 | tr -d '\n'; }

# transport: the argv that runs one shell command string on the VM
transport() {
  if [[ -n "${PROD_SSH:-}" ]]; then
    read -r -a TRANSPORT <<<"$PROD_SSH"
  else
    TRANSPORT=(ssh -i "$PROD_KEY" -o IdentitiesOnly=yes -o BatchMode=yes
      -o ConnectTimeout="$CONNECT_TIMEOUT" -o ServerAliveInterval=15 -o ServerAliveCountMax=4
      -T "$PROD_USER@$PROD_HOST")
  fi
}

# vm SECONDS DISPLAY COMMAND: run COMMAND (a shell string) on the VM under a local timeout.
# DISPLAY is what PROD_DRY prints instead (same command, program elided).
vm() {
  local secs="$1" display="$2" cmd="$3"
  transport
  if [[ "${PROD_DRY:-}" == 1 ]]; then
    printf 'local timeout: %ss\ntransport:     %s\nremote shell:  %s\n' "$((secs + 45))" "${TRANSPORT[*]}" "$display"
    return 0
  fi
  timeout -k 5 "$((secs + 45))" "${TRANSPORT[@]}" "$cmd" </dev/null
}

qdir() { printf "cd '%s'" "$PROD_DIR"; }
[[ "$PROD_DIR" != *"'"* ]] || die "PROD_DIR must not contain a single quote"

# py SECONDS OP ARG...: run PROGRAM inside battlefield with OP and base64'd args.
py() {
  local secs="$1" op="$2"; shift 2
  local enc shown="http_timeout=$HTTP_TIMEOUT" a
  enc="'$(b64 "$HTTP_TIMEOUT")'"
  for a in "$@"; do enc+=" '$(b64 "$a")'"; shown+=" $(printf '%q' "$a")"; done
  local boot="python3 -c 'import base64,sys;exec(base64.b64decode(sys.argv[1]))'"
  local pre
  pre="$(qdir) && timeout -k 5 $((secs + 15)) $PROD_BF_EXEC $boot"
  if [[ "${PROD_DRY:-}" == 1 ]]; then
    printf 'op: %s  args (decoded): %s\n' "$op" "$shown"
    printf 'program: %s bytes, sha256 %s; no token anywhere in this command\n' \
      "${#PROGRAM}" "$(printf '%s' "$PROGRAM" | sha256sum | cut -c1-16)"
  fi
  vm "$secs" "$pre '<PROGRAM_B64>' '$op' $enc" "$pre '$(b64 "$PROGRAM")' '$op' $enc"
}

need() { [[ $# -ge 2 && -n "$2" ]] || die "$1 is required"; }
check_id() { [[ "$2" =~ ^[A-Za-z0-9_-]{1,64}$ ]] || die "$1 must match [A-Za-z0-9_-]{1,64}"; }
check_mode() { [[ "$1" =~ ^(off|shadow|enforce)$ ]] || die "MODE must be off|shadow|enforce"; }

# ---------------------------------------------------------------------------------------------
# record: secret scan. Fixtures get committed and replayed publicly, so a key in one is a leak.
# HARD patterns refuse the fixture (it is moved out of the repo); SOFT ones warn. Matches are
# printed redacted (first 4 chars + length), never in full.
# ---------------------------------------------------------------------------------------------
HARD_PATTERNS=(
  'sk-[A-Za-z0-9_-]{20,}'            # OpenAI / Anthropic style
  'fk-[A-Za-z0-9_-]{20,}'            # Factory style
  'gh[pousr]_[A-Za-z0-9]{30,}'
  'github_pat_[A-Za-z0-9_]{30,}'
  'AKIA[0-9A-Z]{16}'
  'AIza[0-9A-Za-z_-]{35}'            # Google / Gemini
  'xox[abprs]-[A-Za-z0-9-]{10,}'     # Slack
  'eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.'  # JWT
  '-----BEGIN [A-Z ]*PRIVATE KEY'
  '[Bb]earer [A-Za-z0-9._~+/=-]{16,}'
  '\[REDACTED\]'                     # the VM scrubbed a live token/key out of an event payload
)
SOFT_PATTERNS=(
  '[0-9a-fA-F]{32,}'                 # long hex (openssl rand -hex)
  '[A-Za-z0-9+/_-]{40,}={0,2}'       # long base64 / base64url
)

# scan FILE PATTERN...: print redacted hits, return 0 if any
scan() {
  local file="$1" hit=1 p ln m; shift
  for p in "$@"; do
    while IFS=: read -r ln m; do
      [[ -n "$m" ]] || continue
      # soft base64 rule: require a digit and a letter, skip URL paths
      if [[ "$p" == '[A-Za-z0-9+/_-]{40,}={0,2}' ]]; then
        [[ "$m" =~ [0-9] && "$m" =~ [A-Za-z] && "$m" != /* ]] || continue
      fi
      printf '  line %s: %s... (%d chars, pattern %s)\n' "$ln" "${m:0:4}" "${#m}" "$p" >&2
      hit=0
    done < <(grep -noE -e "$p" "$file" | head -n 20 || true)
  done
  return "$hit"
}

cmd_record() {
  local ep="$1" name="${2:-$1}"
  check_id EP "$ep"
  [[ "$name" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$ ]] || die "NAME must match [A-Za-z0-9][A-Za-z0-9._-]*"
  name="${name%.jsonl}"
  local dest="$FIXTURES_DIR/$name.jsonl" tmp="$FIXTURES_DIR/$name.jsonl.tmp"  # *.jsonl.tmp is gitignored
  if [[ -e "$dest" && "${PROD_RECORD_OVERWRITE:-}" != 1 ]]; then
    die "$dest exists; pick another NAME or set PROD_RECORD_OVERWRITE=1"
  fi
  if [[ "${PROD_DRY:-}" == 1 ]]; then py 600 events "$ep"; return; fi
  mkdir -p "$FIXTURES_DIR"
  trap 'rm -f "$tmp"' EXIT
  py 600 events "$ep" >"$tmp"
  [[ -s "$tmp" ]] || die "no events for $ep"
  if scan "$tmp" "${HARD_PATTERNS[@]}"; then
    local q
    q="$(mktemp -d)/$name.jsonl"
    mv -f "$tmp" "$q"
    trap - EXIT
    printf 'prod: REFUSED: %s looks like it contains a key or token (hits above).\n' "$name.jsonl" >&2
    printf 'prod: quarantined outside the repo at %s; inspect it, do not commit it.\n' "$q" >&2
    exit 3
  fi
  if scan "$tmp" "${SOFT_PATTERNS[@]}"; then
    printf 'prod: WARNING: long hex/base64 strings above; check them before committing %s\n' "$dest" >&2
  fi
  mv -f "$tmp" "$dest"
  trap - EXIT
  printf '%s: %s events\n' "${dest#"$REPO_ROOT"/}" "$(wc -l <"$dest" | tr -d ' ')"
}

# ---------------------------------------------------------------------------------------------
main() {
  [[ $# -ge 1 ]] || usage
  local sub="$1"; shift
  case "$sub" in
    health) py "$HTTP_TIMEOUT" health ;;
    ps)
      vm "$HTTP_TIMEOUT" "$(qdir) && timeout -k 5 $HTTP_TIMEOUT $PROD_COMPOSE ps" \
        "$(qdir) && timeout -k 5 $HTTP_TIMEOUT $PROD_COMPOSE ps" ;;
    logs)
      local svc="${1:-}"
      [[ -z "$svc" || "$svc" =~ ^(battlefield|red|green|blue|frontend|postgres|caddy)$ ]] ||
        die "SVC must be battlefield|red|green|blue|frontend|postgres|caddy"
      local c
      c="$(qdir) && timeout -k 5 $HTTP_TIMEOUT $PROD_COMPOSE logs --no-color --timestamps --tail $LOG_TAIL $svc"
      vm "$HTTP_TIMEOUT" "$c" "$c" ;;
    episode)
      need MODE "${1:-}"; need SEED "${2:-}"; need DAYS "${3:-}"
      check_mode "$1"; is_uint "$2" || die "SEED must be an integer"
      { is_uint "$3" && (($3 >= 1 && $3 <= 365)); } || die "DAYS must be 1..365"
      py "$HTTP_TIMEOUT" episode "$1" "$2" "$3" "${4:-}" ;;
    step)   need EP "${1:-}"; check_id EP "$1"; py "$STEP_TIMEOUT" post "$1" step "$STEP_TIMEOUT" ;;
    pause)  need EP "${1:-}"; check_id EP "$1"; py "$HTTP_TIMEOUT" post "$1" pause "$HTTP_TIMEOUT" ;;
    resume) need EP "${1:-}"; check_id EP "$1"; py "$HTTP_TIMEOUT" post "$1" resume "$HTTP_TIMEOUT" ;;
    toggle)
      need EP "${1:-}"; need MODE "${2:-}"; check_id EP "$1"; check_mode "$2"
      py "$HTTP_TIMEOUT" toggle "$1" "$2" ;;
    attack)
      need EP "${1:-}"; need SCHEME "${2:-}"; check_id EP "$1"; check_id SCHEME "$2"
      py "$HTTP_TIMEOUT" attack "$1" "$2" "${3:-}" ;;
    escalations)
      [[ -z "${1:-}" ]] || check_id EP "$1"
      py "$HTTP_TIMEOUT" escalations "${1:-}" ;;
    resolve)
      need ESC "${1:-}"; need DECISION "${2:-}"; check_id ESC "$1"
      [[ "$2" =~ ^(approve|block)$ ]] || die "DECISION must be approve|block"
      py "$HTTP_TIMEOUT" resolve "$1" "$2" "$RESOLVE_BY" ;;
    score)   need EP "${1:-}"; check_id EP "$1"; py "$HTTP_TIMEOUT" score "$1" ;;
    wait)    need EP "${1:-}"; check_id EP "$1"; py "$((WAIT_TIMEOUT + HTTP_TIMEOUT))" wait "$1" "$WAIT_TIMEOUT" "$WAIT_INTERVAL" ;;
    credits) need EP "${1:-}"; check_id EP "$1"; py 600 credits "$1" ;;
    record)  need EP "${1:-}"; cmd_record "$1" "${2:-}" ;;
    -h|--help|help) usage ;;
    *) printf 'prod: unknown subcommand %q\n' "$sub" >&2; usage ;;
  esac
}

main "$@"
