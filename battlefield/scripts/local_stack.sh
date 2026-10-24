#!/usr/bin/env bash
# Red Ledger without Docker: Postgres 16 (pgserver) + battlefield + three agents as local processes.
# Owner: Dev Ad. Usage (normally via the Makefile):
#   battlefield/scripts/local_stack.sh up      # start; AGENTS=mock|real, RED/GREEN/BLUE=mock|real override per agent
#   battlefield/scripts/local_stack.sh status  # health of every process
#   battlefield/scripts/local_stack.sh stop    # stop processes + Postgres; RESET=1 CONFIRM=yes also wipes the DB
#
# State lives in <repo>/.local-stack/ (self-ignoring: it writes its own .gitignore). Tokens are generated
# per data dir into .local-stack/env (mode 600) and never printed; the Makefile's curl targets read them
# from there while the stack is up. This script never reads or writes any .env file. Real agents get
# DRY_RUN=true unless you export DRY_RUN=false (or DRY_RUN_<AGENT>=false), and FACTORY_API_KEY /
# DROID_MODEL_<AGENT> / CRS_* only if you exported them yourself.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DIR="$ROOT/.local-stack"
LOGS="$DIR/logs"
PIDS="$DIR/pids"
PGDATA="$DIR/pgdata"
ENVF="$DIR/env"
PORTS=(8000 8001 8002 8003)
declare -A AGENT_PORT=([red]=8001 [green]=8002 [blue]=8003)
HEALTH_WAIT="${LOCAL_STACK_HEALTH_WAIT:-120}"

die() { echo "local-stack: $*" >&2; exit 1; }
say() { echo "local-stack: $*" >&2; }

port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

pg_start() {  # start (or reuse) Postgres in our data dir; writes its URI to $DIR/database_url
  # The postmaster outlives this call and inherits our fds, so give it none of the caller's: stdin from
  # /dev/null, stdout/stderr into its own log. Otherwise `make local-stack | tee` would never see EOF.
  uvx -q -p 3.11 --from pgserver python -c \
    "import pgserver,sys; s=pgserver.get_server(sys.argv[1], cleanup_mode=None); open(sys.argv[2],'w').write(s.get_uri())" \
    "$PGDATA" "$DIR/database_url" </dev/null >>"$LOGS/postgres.log" 2>&1
}

pg_pid() {  # the running postmaster's pid, read from postmaster.pid (never starts Postgres)
  local pid
  pid="$(head -n 1 "$PGDATA/postmaster.pid" 2>/dev/null || true)"
  pid_alive "$pid" && printf '%s' "$pid"
}

pid_alive() { [[ -n "${1:-}" ]] && kill -0 "$1" 2>/dev/null; }

start_proc() {  # name, workdir, then the command (env is inherited from the caller's exports)
  # setsid may fork, so `$!` would be a pid that is already gone. Instead the new session's leader
  # records its own pid ($$ = the process group id) and then execs the command, keeping that pid, so
  # stop can signal the whole group (uv run and the uvicorn it spawns).
  local name="$1" wd="$2"; shift 2
  rm -f "$PIDS/$name"
  printf '=== local-stack start %s: %s\n' "$(date -u +%FT%TZ)" "$*" >>"$LOGS/$name.log"
  # The redirections sit on the backgrounded subshell itself, so no shell left between us and the
  # service ever holds the caller's stdout/stderr (`make local-stack | tee` must see EOF).
  (cd "$wd" || exit 1; exec setsid bash -c 'echo "$$" >"$0"; exec "$@"' "$PIDS/$name" "$@") </dev/null >>"$LOGS/$name.log" 2>&1 &
  local t=0
  until [[ -s "$PIDS/$name" ]]; do ((t++ >= 50)) && die "$name did not start"; sleep 0.1; done
}

wait_health() {  # name, url
  local name="$1" url="$2" t=0
  until curl -fsS --max-time 3 "$url" >/dev/null 2>&1; do
    pid_alive "$(cat "$PIDS/$name" 2>/dev/null)" || die "$name exited during startup; see $LOGS/$name.log"
    ((t++ >= HEALTH_WAIT)) && die "$name not healthy after ${HEALTH_WAIT}s; see $LOGS/$name.log"
    sleep 1
  done
}

mode_of() {  # red|green|blue -> mock|real
  local a="$1" v
  v="$(eval "printf '%s' \"\${${a^^}:-}\"")"
  v="${v:-${AGENTS:-mock}}"
  [[ "$v" == mock || "$v" == real ]] || die "${a^^}/AGENTS must be mock or real (got '$v')"
  printf '%s' "$v"
}

cmd_up() {
  [[ -s "$PIDS/battlefield" ]] && pid_alive "$(cat "$PIDS/battlefield")" && die "already running (make local-stack-status / local-stack-stop)"
  for p in "${PORTS[@]}"; do port_busy "$p" && die "port $p is in use (another stack?) — not touching it"; done
  mkdir -p "$LOGS" "$PIDS"
  printf '*\n' >"$DIR/.gitignore"

  # One token per agent plus the operator's (contracts/agent-service.md "Tokens"); a stack created
  # before per-agent tokens gets the missing ones appended. AGENT_TOKEN stays as the shared fallback.
  umask 077
  touch "$ENVF"
  python3 - "$ENVF" <<'PY'
import secrets, sys
path = sys.argv[1]
have = {line.split("=", 1)[0] for line in open(path) if "=" in line}
with open(path, "a") as f:
    for name in ("AGENT_TOKEN", "AGENT_TOKEN_RED", "AGENT_TOKEN_GREEN", "AGENT_TOKEN_BLUE", "OPERATOR_TOKEN"):
        if name not in have:
            f.write(f"{name}={secrets.token_hex(24)}\n")
PY
  chmod 600 "$ENVF"
  set -a
  # shellcheck disable=SC1090
  . "$ENVF"
  set +a

  say "starting Postgres 16 (pgserver) in .local-stack/pgdata"
  local uri
  pg_start || die "pgserver failed; see $LOGS/postgres.log"
  chmod 600 "$DIR/database_url"
  uri="$(cat "$DIR/database_url")"
  [[ "$uri" == postgresql://* ]] || die "pgserver did not return a URI; see $LOGS/postgres.log"

  local A=http://127.0.0.1
  export BATTLEFIELD_URL="$A:8000" BLUE_URL="$A:8003"
  export RED_URL="$A:8001" GREEN_URL="$A:8002"
  export DAY_PAUSE_SEC="${DAY_PAUSE_SEC:-0}" LOG_LEVEL="${LOG_LEVEL:-info}"

  say "starting battlefield on :8000"
  DATABASE_URL="$uri" SCHEMA_PATH="$ROOT/contracts/schema.sql" \
    start_proc battlefield "$ROOT/battlefield" uv run --quiet uvicorn app.main:app --host 127.0.0.1 --port 8000
  local t=0  # /api/health is operator-only, so this one waits with the token
  until curl -fsS --max-time 3 -H "Authorization: Bearer $OPERATOR_TOKEN" "$A:8000/api/health" >/dev/null 2>&1; do
    pid_alive "$(cat "$PIDS/battlefield")" || die "battlefield exited during startup; see $LOGS/battlefield.log"
    ((t++ >= HEALTH_WAIT)) && die "battlefield not healthy after ${HEALTH_WAIT}s; see $LOGS/battlefield.log"
    sleep 1
  done

  local a m port dry own
  for a in blue red green; do
    m="$(mode_of "$a")"; port="${AGENT_PORT[$a]}"
    dry="$(eval "printf '%s' \"\${DRY_RUN_${a^^}:-\${DRY_RUN:-true}}\"")"
    if [[ "$m" == real ]]; then say "starting $a (real, DRY_RUN=$dry) on :$port"; else say "starting $a (mock) on :$port"; fi
    # each agent process holds only its own token, as AGENT_TOKEN
    own="$(eval "printf '%s' \"\${AGENT_TOKEN_${a^^}}\"")"
    if [[ "$m" == mock ]]; then
      AGENT_NAME="$a" AGENT_TOKEN="$own" start_proc "$a" "$ROOT/battlefield" uv run --quiet uvicorn mock_agents.server:app --host 127.0.0.1 --port "$port"
    else
      AGENT_NAME="$a" AGENT_TOKEN="$own" PORT="$port" DRY_RUN="$dry" PYTHONPATH="." \
        DROID_MODEL="$(eval "printf '%s' \"\${DROID_MODEL_${a^^}:-}\"")" \
        DROID_REASONING="$(eval "printf '%s' \"\${DROID_REASONING_${a^^}:-}\"")" \
        start_proc "$a" "$ROOT/$a" uv run --quiet uvicorn server:app --host 127.0.0.1 --port "$port"
    fi
    wait_health "$a" "$A:$port/health"
  done
  say "up. API=http://127.0.0.1:8000; the make curl targets pick up the token automatically while the stack is up."
  cmd_status
}

cmd_status() {
  [[ -f "$ENVF" ]] || die "no local stack here (make local-stack)"
  set -a
  # shellcheck disable=SC1090
  . "$ENVF"
  set +a
  local name pid url ok=0
  for name in battlefield red green blue; do
    pid="$(cat "$PIDS/$name" 2>/dev/null || true)"
    if [[ "$name" == battlefield ]]; then url="http://127.0.0.1:8000/api/health"; else url="http://127.0.0.1:${AGENT_PORT[$name]}/health"; fi
    if pid_alive "$pid" && body="$(curl -fsS --max-time 5 -H "Authorization: Bearer $OPERATOR_TOKEN" "$url" 2>/dev/null)"; then
      printf '  %-11s ok    pid %-7s %s\n' "$name" "$pid" "$(printf '%s' "$body" | python3 -c 'import json,sys
d=json.load(sys.stdin)
print("dry_run=%s model=%s" % (d.get("dry_run"), d.get("model") or "-") if "agent" in d else "db=%s" % d.get("db"))' 2>/dev/null)"
    else
      printf '  %-11s DOWN  pid %s (log: .local-stack/logs/%s.log)\n' "$name" "${pid:--}" "$name"; ok=1
    fi
  done
  if [[ -n "$(pg_pid)" ]]; then
    printf '  %-11s ok\n' postgres
  else
    printf '  %-11s DOWN\n' postgres; ok=1
  fi
  return "$ok"
}

cmd_stop() {
  local name pid
  for name in green red blue battlefield; do
    pid="$(cat "$PIDS/$name" 2>/dev/null || true)"
    if pid_alive "$pid"; then kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true; fi
  done
  for name in green red blue battlefield; do
    pid="$(cat "$PIDS/$name" 2>/dev/null || true)"
    for _ in $(seq 1 20); do pid_alive "$pid" || break; sleep 0.5; done
    pid_alive "$pid" && { kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true; }
    rm -f "$PIDS/$name"
  done
  local ppid
  ppid="$(pg_pid || true)"
  if [[ -n "$ppid" ]]; then kill -INT "$ppid" 2>/dev/null || true; for _ in $(seq 1 30); do pid_alive "$ppid" || break; sleep 0.5; done; fi
  if [[ "${RESET:-}" == 1 ]]; then
    [[ "${CONFIRM:-}" == yes ]] || die "RESET=1 wipes .local-stack/pgdata and tokens; add CONFIRM=yes to proceed"
    rm -r -- "$PGDATA" "$ENVF" "$DIR/database_url" 2>/dev/null || true
    say "database and tokens wiped"
  fi
  say "stopped"
}

case "${1:-}" in
  up) cmd_up ;;
  status) cmd_status ;;
  stop) cmd_stop ;;
  *) die "usage: $0 up|status|stop" ;;
esac
