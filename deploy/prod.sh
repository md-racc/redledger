#!/usr/bin/env bash
# Drive the prod stack from your laptop without the operator token ever leaving the VM.
# Owner: Dev Ad. Guide: OPERATIONS.md. Make wrappers: `make help | grep prod-`.
#
#   deploy/prod.sh health | ps | logs [SVC]
#   deploy/prod.sh episode MODE SEED DAYS [ATTACK_PLAN_JSON]    # create + start; stdout = episode id
#   deploy/prod.sh step|pause|resume|score|wait|credits EP
#   deploy/prod.sh toggle EP off|shadow|enforce
#   deploy/prod.sh attack EP SCHEME [PARAMS_JSON]
#   deploy/prod.sh fixtures EP FILE           seed operator fixtures (legit employees/expenses) from a local JSON file
#   deploy/prod.sh crs-episode SEED [DAYS]    # blue's CRS identity scenario (P01/P12/P16), stepped; summary + PASS/FAIL
#   deploy/prod.sh escalations [EP]
#   deploy/prod.sh resolve ESC approve|block
#   deploy/prod.sh record EP [NAME]          # -> battlefield/fixtures/episodes/<NAME or EP>.jsonl
#   deploy/prod.sh evolve GENS DAYS MODE SEED REVEAL_DAYS REVEAL_GENERATIONS MAX_CREDITS  # stdout = lineage id
#   deploy/prod.sh lineage-status|lineage-pause|lineage-resume|lineage-wait LN
#   deploy/prod.sh lineage-export LN [GEN]   # -> runs/<LN>/{lineage.json,playbooks/,gen-<g>/...} (ground truth)
#   deploy/prod.sh evolution-report LN       # -> runs/<LN>/report.json + report.md
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
#   PROD_HOST (required for ssh; else first line of $PROD_HOST_FILE, default ~/.config/redledger/prod_host —
#     kept out of this public repo)  PROD_USER (deploy)  PROD_KEY (~/.ssh/redledger_deploy)
#   PROD_DIR (/opt/redledger)  PROD_COMPOSE ("docker compose -f docker-compose.yml -f docker-compose.prod.yml")
#   PROD_BF_EXEC ("$PROD_COMPOSE exec -T battlefield") — prefix that runs argv inside battlefield
#   PROD_SSH  — transport override: a command that takes ONE argument, the shell command to run
#               on the VM. Default is ssh to $PROD_USER@$PROD_HOST. Local test: PROD_SSH="bash -c".
#   PROD_DRY=1 — print what would run (program elided, arguments decoded) and exit 0.
#   PROD_HTTP_TIMEOUT (30)  PROD_STEP_TIMEOUT (900: one live day is up to 3 turns + escalations)
#   PROD_WAIT_TIMEOUT (3600)  PROD_WAIT_INTERVAL (5)  PROD_CONNECT_TIMEOUT (10)  PROD_LOG_TAIL (200)
#   PROD_RESOLVE_BY (judge)  PROD_RECORD_OVERWRITE=1 — let `record` replace an existing fixture.
#   PROD_LINEAGE_WAIT_TIMEOUT (7200)  PROD_LINEAGE_WAIT_INTERVAL (30): lineage-wait polls less often (each poll
#     scores every generation server-side). RUNS_DIR (<repo>/runs) — where lineage-export/evolution-report write.
set -euo pipefail

PROD_HOST_FILE="${PROD_HOST_FILE:-$HOME/.config/redledger/prod_host}"
if [[ -z "${PROD_HOST:-}" && -r "$PROD_HOST_FILE" ]]; then PROD_HOST="$(head -n1 "$PROD_HOST_FILE" | tr -d "[:space:]")"; fi
PROD_HOST="${PROD_HOST:-}"
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
LINEAGE_WAIT_TIMEOUT="${PROD_LINEAGE_WAIT_TIMEOUT:-7200}"
LINEAGE_WAIT_INTERVAL="${PROD_LINEAGE_WAIT_INTERVAL:-30}"

REPO_ROOT="$(cd "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
FIXTURES_DIR="$REPO_ROOT/battlefield/fixtures/episodes"

die() { printf 'prod: %s\n' "$*" >&2; exit 1; }
usage() { sed -n '2,18p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' >&2; exit 2; }

is_uint() { [[ "$1" =~ ^[0-9]+$ ]]; }
for _n in HTTP_TIMEOUT STEP_TIMEOUT WAIT_TIMEOUT WAIT_INTERVAL CONNECT_TIMEOUT LOG_TAIL LINEAGE_WAIT_TIMEOUT LINEAGE_WAIT_INTERVAL; do
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
_raw = [v for k, v in os.environ.items() if re.search(r"TOKEN|KEY|SECRET|PASS", k) and len(v) >= 8]
# also the escaped forms a repr() in an error message would show (str and bytes)
SECRETS = sorted({f for v in _raw for f in (v, repr(v)[1:-1], repr(v.encode())[2:-1])}, key=len, reverse=True)


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


def _hook(t, v, tb):  # an uncaught traceback can quote env values (e.g. a malformed token)
    import traceback

    err("".join(traceback.format_exception(t, v, tb)))


sys.excepthook = _hook


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


def _open(method, path, body=None, query=None, timeout=None):
    url = API + "/api" + path + ("?" + urllib.parse.urlencode(query) if query else "")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", "Bearer " + TOKEN)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout or HTTP_TIMEOUT) as r:
        return r.read().decode()


def call(method, path, body=None, query=None, timeout=None):
    try:
        raw = _open(method, path, body, query, timeout)
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


def episode_credits(ep):
    """Summed turn.ended factory_credits of one episode, total and per agent (missing/null = 0)."""
    total, per = 0.0, {}
    for e in events(ep):
        if e.get("type") != "turn.ended":
            continue
        p = e.get("payload") or {}
        c = num(p.get("factory_credits"))
        if c is None:
            continue
        total += c
        a = p.get("agent") or "?"
        per[a] = per.get(a, 0.0) + c
    return total, per


SCORE_KEYS = ("dollars_extracted", "dollars_blocked", "false_positive_cost", "attacks_launched", "attacks_caught", "legit_blocked")
CONFIG_KEYS = ("generations", "days", "controller_mode", "reveal_days", "reveal_generations", "max_credits")


SUMMARY_BUDGET = 480.0  # seconds; the shell's kill timeout for lineage-status is 600 + 45


def lineage_summary(ln, with_credits=True):
    """Bounded: once SUMMARY_BUDGET is spent, remaining generations are listed without credits."""
    started = time.monotonic()
    l = call("GET", "/lineages/%s" % seg(ln))
    cfg = l.get("config") or {}
    gens, total, partial = [], 0.0, False
    for g in l.get("generations") or []:
        ep = call("GET", "/episodes/%s" % seg(g["episode_id"]))
        row = {
            "generation": g.get("generation"),
            "episode_id": g.get("episode_id"),
            "seed": g.get("seed"),
            "status": g.get("status"),
            "day": "%s/%s" % (ep.get("current_day"), ep.get("days")),
            "score": {k: (g.get("score") or {}).get(k) for k in SCORE_KEYS},
        }
        if with_credits and time.monotonic() - started < SUMMARY_BUDGET:
            row["turn_credits"], row["turn_credits_by_agent"] = episode_credits(g["episode_id"])
            total += row["turn_credits"]
        elif with_credits:
            row["turn_credits"] = None  # budget spent: credits omitted, totals below are partial
            partial = True
        gens.append(row)
    s = {
        "id": l.get("id"),
        "status": l.get("status"),
        "current_generation": l.get("current_generation"),
        "base_seed": l.get("base_seed"),
        "config": {k: cfg.get(k) for k in CONFIG_KEYS},
        "playbook_versions": l.get("playbook_versions"),
        "generations": gens,
    }
    if with_credits:
        mc = num(cfg.get("max_credits")) or 0.0
        # /reflect usage also counts toward max_credits but is not in turn.ended: this is a lower bound
        s["turn_credits_total"] = total
        s["max_credits"] = mc
        s["remaining_at_most"] = (mc - total) if mc > 0 else None
        s["credits_partial"] = partial
    return s


# ---- crs-episode: blue's CRS identity scenario, stepped (mirrors blue/tests/crs_episode_acceptance.py) ----
# Prints only ids, statuses, severities, rule names, counts and credits: never a request/response body,
# a flag reason, a persona name, provider prose or a credential.
CRS_PERSONAS = ("P01", "P12", "P16")
CRS_DAY1_AMOUNT = {"P01": 55.0, "P12": 91.0, "P16": 48.0}  # the driver's after-verdict expenses
CRS_STATUSES = ("verified", "mismatch", "review", "unknown")
# A CRS mismatch flag carries blue's evidence text (blue/audit/evidence.py), not the internal finding code.
CRS_FLAG_MARKERS = ("crs_employee_identity_mismatch", "CRS reports an employee identity inconsistency")


def is_crs_flag(reason):
    return any(m in str(reason or "") for m in CRS_FLAG_MARKERS)
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class StepFailed(Exception):
    def __init__(self, msg, code=1):
        super().__init__(msg)
        self.code = code


def quiet_call(method, path, body=None, query=None, timeout=None):
    """call() without echoing response bodies (they hold fixture rows): status only, plus battlefield's own
    short error string on 404/409 and the blocking run's ids when the single-active-run guard says 409."""
    try:
        raw = _open(method, path, body, query, timeout)
    except urllib.error.HTTPError as e:
        msg, code = "%s %s -> HTTP %s" % (method, path, e.code), 1
        if e.code in (404, 409):
            try:
                b = json.loads(e.read().decode(errors="replace") or "{}")
            except ValueError:
                b = {}
            b = b if isinstance(b, dict) else {}
            if b.get("error") == "another run is active":
                ids = [b[k] for k in ("episode_id", "lineage_id") if isinstance(b.get(k), str) and ID_RE.match(b[k])]
                msg += ": another run is active (%s); one run at a time" % (", ".join(ids) or "id not given")
                code = 3
            else:
                detail = b.get("error") or b.get("detail")
                if isinstance(detail, str) and len(detail) <= 160:
                    msg += ": " + detail
        raise StepFailed(msg, code) from None
    except (urllib.error.URLError, OSError) as e:
        raise StepFailed("%s %s -> %s" % (method, path, getattr(e, "reason", type(e).__name__))) from None
    return json.loads(raw) if raw else None


def quiet_events(ep):
    after = 0
    while True:
        page = quiet_call("GET", "/events", query={"episode_id": ep, "after_id": after, "limit": 5000})
        yield from page
        if len(page) < 5000:
            return
        after = page[-1]["id"]


def is_crs_tool(name):  # dry-run dispatch says crs_identity_check; Droid may report the MCP id blue-ledger___crs_identity_check
    return isinstance(name, str) and (name == "crs_identity_check" or name.endswith("___crs_identity_check"))


def crs_counts(summary):
    """The tool's own result is {verified, mismatch, review, unknown: int}; anything else is ignored, never shown."""
    try:
        v = json.loads(summary)
    except (TypeError, ValueError):
        return None
    if not isinstance(v, dict) or set(v) != set(CRS_STATUSES) or not all(type(v[k]) is int for k in CRS_STATUSES):
        return None
    return {k: v[k] for k in CRS_STATUSES}


def crs_summary(ep, days, emp_ids, day1):
    ep_row = quiet_call("GET", "/episodes/%s" % seg(ep))
    flags = quiet_call("GET", "/flags", query={"episode_id": ep})
    expenses = quiet_call("GET", "/expenses", query={"episode_id": ep})
    evs = list(quiet_events(ep))
    day1_pid = {x: p for p, x in day1.items()}

    verdicts = {}  # day-1 expense id -> [{action, verdict, rules_fired, enforced}]
    crs_calls, crs_uses, crs_results, reports = {}, {}, {}, 0
    blue_credits, blue_turns = {}, {}
    for e in evs:
        t, p, day = e.get("type"), e.get("payload") or {}, str(e.get("day"))
        if t == "gate.verdict" and p.get("entity_id") in day1_pid:
            verdicts.setdefault(p["entity_id"], []).append({
                "action": p.get("action"),
                "verdict": p.get("verdict"),
                "rules_fired": [r for r in p.get("rules_fired") or [] if isinstance(r, str)],
                "enforced": p.get("enforced"),
            })
        elif t == "agent.tool_call" and e.get("agent") == "blue" and is_crs_tool(p.get("tool")):
            crs_calls[day] = crs_calls.get(day, 0) + 1
            crs_uses[p.get("tool_use_id")] = day
        elif t == "agent.tool_result" and e.get("agent") == "blue" and p.get("tool_use_id") in crs_uses:
            c = crs_counts(p.get("summary"))
            if c is not None:
                crs_results[crs_uses[p["tool_use_id"]]] = c  # the latest result of the day (repeat calls reuse it)
        elif t == "report.posted":
            reports += 1
        elif t == "turn.ended" and p.get("agent") == "blue":
            blue_turns[day] = blue_turns.get(day, 0) + 1
            c = num(p.get("factory_credits"))
            if c is not None:
                blue_credits[day] = blue_credits.get(day, 0.0) + c

    personas = {}
    for pid in CRS_PERSONAS:
        eid = emp_ids[pid]
        mine = [f for f in flags if f.get("entity_type") == "employee" and f.get("entity_id") == eid]
        crs_flagged = any(is_crs_flag(f.get("reason")) for f in mine)
        personas[pid] = {
            "employee_id": eid,
            "crs_status": "mismatch (flagged)" if crs_flagged else "no CRS finding (verified/review/unknown raise none)",
            "flags": [{"day": f.get("day"), "severity": f.get("severity"), "crs": is_crs_flag(f.get("reason"))} for f in mine],
            "expenses": [
                {"id": x.get("id"), "added_for_day": 1 if x.get("id") in day1_pid else 0, "status": x.get("status")}
                for x in expenses
                if x.get("employee_id") == eid
            ],
        }

    reasons, notes = [], []
    p12 = personas["P12"]
    if not any(f["severity"] == "high" for f in p12["flags"]):
        reasons.append("P12 has no high-severity employee flag")
    p12_day1 = day1["P12"]
    if not any(v["verdict"] == "block" and "already_flagged_high" in v["rules_fired"] for v in verdicts.get(p12_day1, [])):
        reasons.append("no block verdict naming already_flagged_high on P12's day-1 expense")
    if any(x["status"] == "paid" for x in p12["expenses"] if x["id"] == p12_day1):
        reasons.append("P12's day-1 expense was paid")
    for pid in ("P01", "P16"):
        unpaid = [x for x in personas[pid]["expenses"] if x["status"] != "paid"]
        if unpaid or not personas[pid]["expenses"]:
            reasons.append("%s expense(s) not paid: %s" % (pid, ", ".join("%s=%s" % (x["id"], x["status"]) for x in unpaid) or "none found"))
    if any(x["status"] != "paid" for x in p12["expenses"] if x["added_for_day"] == 0):
        notes.append("P12's day-0 expense is not paid: the check itself should never block a payment")
    if not crs_calls:
        notes.append("blue made no crs_identity_check tool call")
    if not blue_credits or not sum(blue_credits.values()):
        notes.append("blue's turns reported no factory_credits: its audit ran keyless (DRY_RUN_BLUE?)")
    if reports < days:
        notes.append("%d report.posted for %d days" % (reports, days))

    return {
        "episode_id": ep,
        "episode": {k: ep_row.get(k) for k in ("status", "current_day", "days", "controller_mode", "seed")},
        "personas": personas,
        "day1_gate_verdicts": {pid: verdicts.get(x, []) for pid, x in day1.items()},
        "reports_posted": reports,
        "blue_crs_identity_check": {"calls_by_day": crs_calls, "result_counts_by_day": crs_results},
        "blue_turns_by_day": blue_turns,
        "blue_credits": {"total": sum(blue_credits.values()), "by_day": blue_credits},
        "notes": notes,
        "result": "FAIL" if reasons else "PASS",
        "fail_reasons": reasons,
    }


def crs_episode(seed, days, raw_fixtures, step_timeout):
    days, step_timeout = int(days), float(step_timeout)
    fx = parse_json(raw_fixtures, dict, "battlefield/fixtures/crs-personas.json")
    names = {}  # persona -> exact employee name, from the fixture's CRS-<persona>-... bank account
    for e in fx.get("employees") or []:
        m = re.match(r"^CRS-(P\d\d)-", str(e.get("bank_account", ""))) if isinstance(e, dict) else None
        if m and m.group(1) in CRS_PERSONAS and isinstance(e.get("name"), str):
            names[m.group(1)] = e["name"]
    if sorted(names) != list(CRS_PERSONAS) or len(set(names.values())) != len(CRS_PERSONAS):
        fail("the fixture must hold one employee per persona P01/P12/P16 (bank_account CRS-<persona>-...) with distinct names", 2)

    ep, stage = None, "1/8 preflight"
    try:
        # 1. one run at a time: say who holds it before creating anything (battlefield's guard 409s anyway)
        busy = [x.get("id") for x in quiet_call("GET", "/lineages") if x.get("status") == "running"]
        busy += [x.get("id") for x in quiet_call("GET", "/episodes") if x.get("status") == "running" and not str(x.get("id", "")).startswith("replay_")]
        if busy:
            raise StepFailed("another run is active (%s); one run at a time" % ", ".join(str(b) for b in busy), 3)
        # 2. create the enforce episode; never started, so it only advances by /step
        stage = "2/8 create episode"
        body = {"controller_mode": "enforce", "days": days}
        if seed.strip():
            body["seed"] = int(seed)
        created = quiet_call("POST", "/episodes", body)
        ep = created["id"]
        err("crs-episode: created %s (enforce, seed %s, %s days, not started)" % (ep, created.get("seed"), created.get("days")))
        # 3. persona employees + their first expense
        stage = "3/8 seed fixtures"
        seeded = quiet_call("POST", "/episodes/%s/fixtures" % seg(ep), fx)
        seeded_ids = {x["id"] for x in seeded["employees"]}
        # 4. bind each persona employee, found by exact name among the rows just seeded
        stage = "4/8 bind personas"
        rows = quiet_call("GET", "/employees", query={"episode_id": ep})
        emp_ids = {}
        for pid in CRS_PERSONAS:
            hits = [r["id"] for r in rows if r.get("name") == names[pid] and r.get("id") in seeded_ids]
            if len(hits) != 1:
                raise StepFailed("%s: expected one seeded employee with the persona's name, found %d" % (pid, len(hits)))
            emp_ids[pid] = hits[0]
        for pid in CRS_PERSONAS:
            quiet_call("PUT", "/x/blue/crs/episodes/%s/employees/%s" % (seg(ep), seg(emp_ids[pid])), {"persona_id": pid})
        err("crs-episode: %s: bound %s" % (ep, ", ".join("%s=%s" % (p, emp_ids[p]) for p in CRS_PERSONAS)))
        day1 = {}
        for day in range(days):
            if day == 1:
                # 6. paused between days: the second (after-verdict) expense per employee
                stage = "6/8 add day-1 expenses"
                extra = [
                    {"employee_ref": emp_ids[p], "amount": CRS_DAY1_AMOUNT[p], "category": "meals", "submitted_day": 1, "memo": "acceptance"}
                    for p in CRS_PERSONAS
                ]
                after = quiet_call("POST", "/episodes/%s/fixtures" % seg(ep), {"employees": [], "expenses": extra})
                day1 = {p: after["expenses"][i]["id"] for i, p in enumerate(CRS_PERSONAS)}
            # 5. / 7. one day per /step (the first step also marks the episode started)
            stage = "%s step day %d" % ("5/8" if day == 0 else "7/8", day)
            err("crs-episode: %s: stepping day %d (days 0..%d; up to %ss)" % (ep, day, days - 1, int(step_timeout)))
            if (quiet_call("POST", "/episodes/%s/step" % seg(ep), timeout=step_timeout) or {}).get("done"):
                raise StepFailed("the episode finished before day %d" % day)
        stage = "8/8 summary"
        summary = crs_summary(ep, days, emp_ids, day1)
    except StepFailed as e:
        err("crs-episode: FAILED at step %s%s: %s" % (stage, " (episode %s)" % ep if ep else "", e))
        if ep:
            err("crs-episode: nothing was deleted; inspect with make prod-score/prod-credits EP=%s" % ep)
        sys.exit(e.code)
    except (KeyError, IndexError, TypeError, ValueError, AttributeError) as e:
        err("crs-episode: FAILED at step %s%s: unexpected response shape (%s)" % (stage, " (episode %s)" % ep if ep else "", type(e).__name__))
        sys.exit(1)
    show(summary)
    out("crs-episode %s: %s%s" % (ep, summary["result"], "" if not summary["fail_reasons"] else ": " + "; ".join(summary["fail_reasons"])))
    sys.exit(0 if summary["result"] == "PASS" else 2)


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
elif OP == "fixtures":
    ep, raw = ARGS
    show(call("POST", "/episodes/%s/fixtures" % seg(ep), parse_json(raw, dict, "FILE")))
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
elif OP == "evolve":
    gens, days, mode, seed, reveal_days, reveal_gens, max_credits = ARGS
    config = {"generations": int(gens), "days": int(days), "controller_mode": mode, "max_credits": float(max_credits)}
    if reveal_days.strip():
        config["reveal_days"] = int(reveal_days)
    if reveal_gens.strip():
        config["reveal_generations"] = int(reveal_gens)
    # checked first so a refused start doesn't leave an orphaned `created` lineage behind; battlefield
    # also refuses (409 "another run is active"), this just says why before anything is created
    busy = [x.get("id") for x in call("GET", "/lineages") if x.get("status") == "running"]
    if busy:
        fail("lineage %s is running; one run at a time (wait for it, or prod-lineage-pause it)" % ", ".join(busy), 3)
    eps = [x.get("id") for x in call("GET", "/episodes") if x.get("status") == "running" and not str(x.get("id", "")).startswith("replay_")]
    if eps:
        fail("episode %s is running; one run at a time (wait for it, or make prod-pause EP=%s)" % (", ".join(eps), eps[0]), 3)
    ln = call("POST", "/lineages", {"base_seed": int(seed), "config": config})
    err("created %s: generations=%s days=%s mode=%s base_seed=%s max_credits=%s" % (ln["id"], gens, days, mode, ln.get("base_seed"), max_credits))
    call("POST", "/lineages/%s/start" % seg(ln["id"]))  # on failure the lineage stays `created`; it can be started later
    err("started %s" % ln["id"])
    out(ln["id"])
elif OP == "lineage_post":  # pause / resume
    ln, action = ARGS
    show(call("POST", "/lineages/%s/%s" % (seg(ln), action)))
elif OP == "lineage_status":
    (ln,) = ARGS
    show(lineage_summary(ln))
elif OP == "lineage_wait":
    ln, total, interval = ARGS
    deadline = time.monotonic() + float(total)
    last = None
    while True:
        l = call("GET", "/lineages/%s" % seg(ln))
        cfg = l.get("config") or {}
        cur = (l.get("generations") or [{}])[-1]
        ep = call("GET", "/episodes/%s" % seg(cur["episode_id"])) if cur.get("episode_id") else {}
        day = ep.get("current_day")
        now = (l.get("status"), l.get("current_generation"), cur.get("episode_id"), day)
        if now != last:
            err("%s: %s, generation %s/%s, %s day %s/%s" % (ln, now[0], now[1], cfg.get("generations"), now[2] or "-", day, cfg.get("days")))
            last = now
        if now[0] == "finished":
            show(lineage_summary(ln, with_credits=False))
            sys.exit(0)
        if now[0] in ("failed", "paused", "created"):
            show(lineage_summary(ln, with_credits=False))
            fail("lineage is %s; nothing will advance it (credit cap? run lineage-status, then lineage-resume)" % now[0], 3)
        if now[0] == "running" and ep.get("status") == "paused":
            # MAX_CREDITS_PER_EPISODE (or a manual episode pause) pauses only the episode; the lineage keeps
            # "running" and waits on it forever, so say so instead of sitting out the whole timeout.
            fail("episode %s paused (per-episode credit cap?) -> make prod-credits EP=%s, then make prod-resume EP=%s" % (now[2], now[2], now[2]), 3)
        if time.monotonic() >= deadline:
            fail("timed out after %ss (the lineage keeps running; wait again or check lineage-status)" % total, 124)
        time.sleep(float(interval))
elif OP == "lineage_export":
    ln, gen, timeout = ARGS
    q = {"generation": int(gen)} if gen.strip() else None
    out(json.dumps(call("GET", "/lineages/%s/export" % seg(ln), query=q, timeout=float(timeout)), separators=(",", ":"), default=str))
elif OP == "lineage_report":
    ln, timeout = ARGS
    out(json.dumps(call("GET", "/fe/lineages/%s/report" % seg(ln), timeout=float(timeout)), separators=(",", ":"), default=str))
elif OP == "crs_episode":
    crs_episode(*ARGS)
else:
    fail("unknown op %r" % OP, 2)
PY

b64() { printf '%s' "$1" | base64 | tr -d '\n'; }

# transport: the argv that runs one shell command string on the VM
transport() {
  if [[ -n "${PROD_SSH:-}" ]]; then
    read -r -a TRANSPORT <<<"$PROD_SSH"
  else
    [[ -n "$PROD_HOST" ]] || die "PROD_HOST is not set: export PROD_HOST=<vm ip or host>, or put it in $PROD_HOST_FILE"
    [[ "$PROD_HOST" =~ ^[A-Za-z0-9][A-Za-z0-9.:-]*$ ]] || die "PROD_HOST has unexpected characters"
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
  ((${#enc} <= 65536)) || die "arguments too large (${#enc} bytes encoded; limit 64 KiB)"
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

need() { [[ $# -ge 2 && -n "$2" ]] || die "$1 is required (no defaults on prod; see: deploy/prod.sh --help)"; }
check_id() { [[ "$2" =~ ^[A-Za-z0-9_-]{1,64}$ ]] || die "$1 must match [A-Za-z0-9_-]{1,64}"; }
check_mode() { [[ "$1" =~ ^(off|shadow|enforce)$ ]] || die "MODE must be off|shadow|enforce"; }
# check_int NAME VALUE LO HI
check_int() { { is_uint "$2" && ((${#2} <= 10)) && ((10#$2 >= $3 && 10#$2 <= $4)); } || die "$1 must be an integer $3..$4"; }

# ---------------------------------------------------------------------------------------------
# record: secret scan. Fixtures get committed and replayed publicly, so a key in one is a leak.
# HARD patterns refuse the fixture (it is moved out of the repo); SOFT ones warn. Matches are
# printed redacted (first 4 chars + length), never in full.
# ---------------------------------------------------------------------------------------------
HARD_PATTERNS=(
  # prefix patterns need a left boundary, else prose like "task-assessment_for_vendor_x" hits sk-
  '(^|[^A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}'            # OpenAI / Anthropic style
  '(^|[^A-Za-z0-9])fk-[A-Za-z0-9_-]{20,}'            # Factory style
  '(^|[^A-Za-z0-9])gh[pousr]_[A-Za-z0-9]{30,}'
  '(^|[^A-Za-z0-9])github_pat_[A-Za-z0-9_]{30,}'
  'AKIA[0-9A-Z]{16}'
  'AIza[0-9A-Za-z_-]{35}'            # Google / Gemini
  '(^|[^A-Za-z0-9])xox[abprs]-[A-Za-z0-9-]{10,}'     # Slack
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
      [[ "$p" != '(^|'* ]] || m="${m#[^A-Za-z0-9]}"  # drop the left-boundary char it matched
      [[ -n "$m" ]] || continue
      # soft base64 rule: random strings have digits; prose identifiers like
      # task-assessment_for_vendor_onboarding_q3 don't (>= 4 digits), and skip URL paths
      if [[ "$p" == '[A-Za-z0-9+/_-]{40,}={0,2}' ]]; then
        local digits="${m//[^0-9]/}"
        [[ ${#digits} -ge 4 && "$m" =~ [A-Za-z] && "$m" != /* ]] || continue
      fi
      printf '  line %s: %s... (%d chars, pattern %s)\n' "$ln" "${m:0:4}" "${#m}" "$p" >&2
      hit=0
    done < <(grep -noE -e "$p" "$file" | head -n 20 || true)
  done
  return "$hit"
}

# a fresh temp dir that is guaranteed not to be inside the repo (even if $TMPDIR is)
quarantine_dir() {
  local base
  base="$(cd "${TMPDIR:-/tmp}" 2>/dev/null && pwd -P)" || base=/tmp
  case "$base/" in "$REPO_ROOT"/*) base=/tmp ;; esac
  mktemp -d "$base/redledger-quarantine.XXXXXX"
}

RECORD_TMP=""
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
  RECORD_TMP="$tmp"  # global: the EXIT trap runs after this function's locals are gone
  trap 'rm -f -- "$RECORD_TMP"' EXIT
  py 600 events "$ep" >"$tmp" || die "fetching events for $ep failed (nothing written)"
  [[ -s "$tmp" ]] || die "no events for $ep"
  if scan "$tmp" "${HARD_PATTERNS[@]}"; then
    local q
    q="$(quarantine_dir)/$name.jsonl"
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
# lineage-export / evolution-report: fetch the JSON over the same token-free channel into a temp dir
# outside the repo (the export holds ground truth), then let battlefield/scripts/evolution_report.py
# write runs/<LN>/ through its secret scan (a hard hit writes nothing and exits 3).
# ---------------------------------------------------------------------------------------------
FETCH_TMP=""
cmd_lineage_fetch() {
  local kind="$1" ln="$2" gen="${3:-}"
  check_id LN "$ln"
  [[ -z "$gen" ]] || check_int GEN "$gen" 1 100000
  if [[ "${PROD_DRY:-}" == 1 ]]; then
    if [[ "$kind" == export ]]; then py 900 lineage_export "$ln" "$gen" 840; else py 600 lineage_report "$ln" 540; fi
    return
  fi
  command -v python3 >/dev/null 2>&1 || die "needs python3 locally to write runs/$ln/"
  FETCH_TMP="$(quarantine_dir)"  # global: the EXIT trap runs after this function's locals are gone
  trap 'rm -rf -- "$FETCH_TMP"' EXIT
  local f="$FETCH_TMP/$kind.json"
  if [[ "$kind" == export ]]; then
    py 900 lineage_export "$ln" "$gen" 840 >"$f" || die "fetching the export of $ln failed (nothing written)"
  else
    py 600 lineage_report "$ln" 540 >"$f" || die "fetching the report of $ln failed (nothing written)"
  fi
  [[ -s "$f" ]] || die "empty $kind for $ln (nothing written)"
  local rc=0
  RUNS_DIR="${RUNS_DIR:-$REPO_ROOT/runs}" python3 "$REPO_ROOT/battlefield/scripts/evolution_report.py" "$kind-file" "$ln" "$f" || rc=$?
  if ((rc == 3)); then  # hard secret hit: keep the evidence outside the repo, like `record`
    trap - EXIT
    printf 'prod: REFUSED: the %s of %s looks like it contains a key or token (hits above).\n' "$kind" "$ln" >&2
    printf 'prod: quarantined outside the repo at %s; inspect it, do not commit or share it.\n' "$f" >&2
  fi
  return "$rc"
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
      check_mode "$1"
      { is_uint "$2" && ((${#2} <= 10)) && ((10#$2 <= 2147483647)); } || die "SEED must be an integer 0..2147483647"
      { is_uint "$3" && ((${#3} <= 3)) && ((10#$3 >= 1 && 10#$3 <= 365)); } || die "DAYS must be 1..365"
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
    fixtures)
      need EP "${1:-}"; need FILE "${2:-}"; check_id EP "$1"
      [[ -f "$2" && -r "$2" ]] || die "FILE must be a readable local JSON file"
      (( $(wc -c <"$2") <= 65536 )) || die "FILE must be at most 64 KiB"
      py "$HTTP_TIMEOUT" fixtures "$1" "$(cat -- "$2")" ;;
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
    evolve)
      need GENS "${1:-}"; need DAYS "${2:-}"; need MODE "${3:-}"; need SEED "${4:-}"
      [[ -n "${7:-}" ]] || die "MAX_CREDITS is required on prod (red is live; every turn and reflection costs Factory credits), e.g. MAX_CREDITS=1000000"
      check_int GENS "$1" 1 50; check_int DAYS "$2" 1 365; check_mode "$3"; check_int SEED "$4" 0 2147483647
      [[ -z "${5:-}" ]] || check_int REVEAL_DAYS "$5" 0 365
      [[ -z "${6:-}" ]] || check_int REVEAL_GENERATIONS "$6" 0 50
      check_int MAX_CREDITS "$7" 1 9999999999
      py "$((3 * HTTP_TIMEOUT))" evolve "$1" "$2" "$3" "$4" "${5:-}" "${6:-}" "$7" ;;  # 3 calls: list, create, start
    lineage-status) need LN "${1:-}"; check_id LN "$1"; py 600 lineage_status "$1" ;;
    lineage-pause)  need LN "${1:-}"; check_id LN "$1"; py "$HTTP_TIMEOUT" lineage_post "$1" pause ;;
    lineage-resume) need LN "${1:-}"; check_id LN "$1"; py "$HTTP_TIMEOUT" lineage_post "$1" resume ;;
    lineage-wait)
      need LN "${1:-}"; check_id LN "$1"
      py "$((LINEAGE_WAIT_TIMEOUT + 4 * HTTP_TIMEOUT))" lineage_wait "$1" "$LINEAGE_WAIT_TIMEOUT" "$LINEAGE_WAIT_INTERVAL" ;;
    crs-episode)  # SEED [DAYS]: SEED required (a live, credit-spending run never starts on defaults); DAYS defaults to 2
      local seed="${1:-}" days="${2:-2}" fx="$REPO_ROOT/battlefield/fixtures/crs-personas.json"
      need SEED "$seed"; check_int SEED "$seed" 0 2147483647
      check_int DAYS "$days" 2 30
      [[ -f "$fx" && -r "$fx" ]] || die "missing $fx"
      # budget: one STEP_TIMEOUT per day plus ~16 ordinary calls (preflight, create, fixtures x2, binds, reads)
      py "$((days * STEP_TIMEOUT + 16 * HTTP_TIMEOUT))" crs_episode "$seed" "$days" "$(cat -- "$fx")" "$STEP_TIMEOUT" ;;
    lineage-export)   need LN "${1:-}"; cmd_lineage_fetch export "$1" "${2:-}" ;;
    evolution-report) need LN "${1:-}"; cmd_lineage_fetch report "$1" ;;
    -h|--help|help) usage ;;
    *) printf 'prod: unknown subcommand %q\n' "$sub" >&2; usage ;;
  esac
}

main "$@"
