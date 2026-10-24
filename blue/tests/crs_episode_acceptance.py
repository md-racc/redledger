"""CRS episode-level acceptance: pinned personas through a real stepped episode.

NOT collected by pytest (no test_ prefix). Opt-in live run: calls the CRS sponsor sandbox for
the pinned fictional personas P01/P12/P16 only, through blue's real keyless audit with
CRS_LIVE=true. Never prints credentials, tokens, request/response bodies, or provider prose.

Prereqs (all on a main that includes the operator fixtures route):
  - battlefield on $BATTLEFIELD_URL (default http://127.0.0.1:8000) with BLUE_URL pointing at
    --blue-port, DATABASE_URL set, mock red on :8001 and mock green on :8002 running.
  - blue venv synced (`uv sync --python 3.11 --extra dev` in blue/).
  - Env: OPERATOR_TOKEN, AGENT_TOKEN (battlefield's), CRS_USERNAME, CRS_PASSWORD.

Flow (deterministic via /step; the episode never free-runs):
  1. create episode (enforce, 2 days) -> fixtures: persona employees + day-0 expenses -> bind
     P01/P12/P16 via the operator extension route.
  2. step day 0: green pays the day-0 expenses (no flags exist yet); the keyless audit then
     checks the three employees live: P01 verified, P12 mismatch -> exactly one high-severity
     employee flag, P16 review (neutral, no flag).
  3. while paused, fixtures: a second expense per employee (the after-verdict expenses).
  4. step day 1: P12's expense is blocked by already_flagged_high; P01's and P16's pay.
  5. operator checks: flags, gate.verdict rules_fired, expense outcomes, report.posted events,
     and provider /users/logs all billable:false.

Exit 0 with {"acceptance_passed": true}; exit 2 with fixed failure codes otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

BLUE_DIR = Path(__file__).resolve().parents[1]
PERSONAS_PATH = BLUE_DIR / "audit" / "crs_personas.json"
CRS_BASE = "https://api-sandbox.stitchcredit.com/api"

EXPECT_FLAG = {"P12"}  # mismatch -> exactly one high employee flag; P01/P16 stay flag-free


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"env_missing: {name}")
    return value


class Operator:
    """Operator-token client; agent tokens are never used here."""

    def __init__(self, base: str, token: str) -> None:
        self._client = httpx.Client(
            base_url=base,
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(30.0, read=300.0),
            trust_env=False,
        )

    def call(self, method: str, path: str, code: str, **kwargs) -> httpx.Response:
        try:
            resp = self._client.request(method, f"/api{path}", **kwargs)
        except httpx.HTTPError as exc:
            raise AssertionError(f"{code}: request error {type(exc).__name__}") from exc
        return resp

    def json(self, method: str, path: str, code: str, expect: int = 200, **kwargs):
        resp = self.call(method, path, code, **kwargs)
        if resp.status_code != expect:
            raise AssertionError(f"{code}: {method} {path} -> {resp.status_code}")
        return resp.json()


def wait_health(url: str, timeout: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if httpx.get(url, timeout=3.0, trust_env=False).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    return False


def start_blue(port: int, battlefield_url: str, agent_token: str, log_path: Path) -> subprocess.Popen:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "AGENT_NAME": "blue",
        "BATTLEFIELD_URL": battlefield_url,
        "AGENT_TOKEN": agent_token,
        "DRY_RUN": "true",
        "CRS_LIVE": "true",
        "CRS_USERNAME": _env("CRS_USERNAME"),
        "CRS_PASSWORD": _env("CRS_PASSWORD"),
        "PORT": str(port),
        "LOG_LEVEL": "warning",
        "UV_NO_SYNC": "1",
        "UV_NO_ENV_FILE": "1",
    }  # FACTORY_API_KEY deliberately absent: keyless audit, live CRS only.
    log = log_path.open("w")
    proc = subprocess.Popen(
        [str(BLUE_DIR / ".venv" / "bin" / "python"), "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=BLUE_DIR,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    if not wait_health(f"http://127.0.0.1:{port}/health"):
        proc.terminate()
        raise AssertionError("blue_unhealthy")
    return proc


def provider_log_summary() -> dict:
    """Login and summarize /users/logs without printing any secret or payload."""
    with httpx.Client(base_url=CRS_BASE, timeout=10.0, trust_env=False) as client:
        login = client.post("/users/login", json={"username": _env("CRS_USERNAME"), "password": _env("CRS_PASSWORD")})
        if login.status_code != 200:
            raise AssertionError("provider_login_failed")
        token = login.json().get("token", "")
        logs = client.get("/users/logs", headers={"Authorization": f"Bearer {token}"})
        if logs.status_code != 200:
            raise AssertionError("provider_logs_missing")
    entries = logs.json().get("content", [])
    return {
        "entries": len(entries),
        "identity_checks": sum("identity-manager-verification" in str(e.get("url", "")) for e in entries),
        "all_billable_false": all(e.get("billable") is False for e in entries) and len(entries) > 0,
    }


def run() -> dict:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-provider-call", action="store_true", help="required: calls the CRS sandbox")
    parser.add_argument("--battlefield-url", default=os.environ.get("BATTLEFIELD_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--blue-port", type=int, default=8003)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument(
        "--blue-external",
        action="store_true",
        help="blue is already running on --blue-port (e.g. make local-stack BLUE=real with CRS_LIVE/creds exported)",
    )
    args = parser.parse_args()
    if not args.allow_provider_call:
        raise SystemExit("flag_not_given: pass --allow-provider-call (sponsor sandbox, pinned personas only)")

    failures: list[str] = []
    out: dict = {"scenario": "crs_episode", "acceptance_passed": False, "failure_codes": failures}
    suffix = secrets.token_hex(3)
    seed = args.seed if args.seed is not None else secrets.randbelow(90000) + 1000
    personas = json.loads(PERSONAS_PATH.read_text())

    op = Operator(args.battlefield_url, _env("OPERATOR_TOKEN"))
    if op.call("GET", "/health", "battlefield_unreachable").status_code != 200:
        raise AssertionError("battlefield_unreachable")

    blue = None
    if args.blue_external:
        if not wait_health(f"http://127.0.0.1:{args.blue_port}/health", timeout=10):
            raise AssertionError("blue_unhealthy: --blue-external but nothing healthy on the port")
    else:
        log_dir = Path(tempfile.mkdtemp(prefix="crs-accept-"))
        blue = start_blue(args.blue_port, args.battlefield_url, _env("AGENT_TOKEN"), log_dir / "blue.log")
        out["blue_log"] = str(log_dir / "blue.log")
    try:
        episode = op.json(
            "POST",
            "/episodes",
            "episode_create_failed",
            expect=201,
            json={"controller_mode": "enforce", "days": 2, "seed": seed},
        )
        ep = episode["id"]
        out["episode_id"] = ep

        def employee(pid: str) -> dict:
            p = personas[pid]
            return {
                "name": f"{p['firstName']} {p['lastName']}",
                "role": "Engineer",
                "salary": 120000,
                "bank_account": f"FXT-{pid}-{suffix}",
                "start_day": 0,
                "hr_record": True,
                "status": "active",
            }

        def expense(ref, amount: float, day: int) -> dict:
            return {"employee_ref": ref, "amount": amount, "category": "meals", "submitted_day": day, "memo": "acceptance"}

        seeded = op.json(
            "POST",
            f"/episodes/{ep}/fixtures",
            "fixtures_rejected",
            expect=201,
            json={
                "employees": [employee(pid) for pid in ("P01", "P12", "P16")],
                "expenses": [expense(0, 42.0, 0), expense(1, 87.0, 0), expense(2, 63.0, 0)],
            },
        )
        emp_ids = {pid: seeded["employees"][i]["id"] for i, pid in enumerate(("P01", "P12", "P16"))}
        day0_expense = {pid: seeded["expenses"][i]["id"] for i, pid in enumerate(("P01", "P12", "P16"))}

        for pid, emp_id in emp_ids.items():
            op.json("PUT", f"/x/blue/crs/episodes/{ep}/employees/{emp_id}", "bind_failed", json={"persona_id": pid})

        op.call("POST", f"/episodes/{ep}/pause", "step_failed")  # pause-then-step: never free-runs
        if op.call("POST", f"/episodes/{ep}/step", "step_failed").status_code != 200:
            raise AssertionError("step_failed: day 0")

        flags0 = op.json("GET", f"/flags?episode_id={ep}", "flags_read_failed")
        emp_flags = {f["entity_id"] for f in flags0 if f.get("entity_type") == "employee" and f.get("severity") == "high"}
        flagged = {pid for pid, eid in emp_ids.items() if eid in emp_flags}
        if flagged != EXPECT_FLAG:
            failures.append(f"flag_mismatch_day0: expected {sorted(EXPECT_FLAG)}, got {sorted(flagged)}")

        after = op.json(
            "POST",
            f"/episodes/{ep}/fixtures",
            "fixtures_rejected",
            expect=201,
            json={"employees": [], "expenses": [expense(emp_ids["P01"], 55.0, 1), expense(emp_ids["P12"], 91.0, 1), expense(emp_ids["P16"], 48.0, 1)]},
        )
        day1_expense = {pid: after["expenses"][i]["id"] for i, pid in enumerate(("P01", "P12", "P16"))}

        if op.call("POST", f"/episodes/{ep}/step", "step_failed").status_code != 200:
            raise AssertionError("step_failed: day 1")

        expenses = {e["id"]: e for e in op.json("GET", f"/expenses?episode_id={ep}", "expenses_read_failed")}
        out["expense_status"] = {pid: expenses[day1_expense[pid]].get("status") for pid in emp_ids}
        if expenses[day1_expense["P12"]].get("status") == "paid":
            failures.append("expense_not_blocked: P12 day-1 expense paid despite the high flag")
        for pid in ("P01", "P16"):
            if expenses[day1_expense[pid]].get("status") != "paid":
                failures.append(f"expense_blocked_wrongly: {pid} day-1 expense status {expenses[day1_expense[pid]].get('status')}")

        events = op.json("GET", f"/events?episode_id={ep}&limit=5000", "events_read_failed")
        verdicts = [e["payload"] for e in events if e.get("type") == "gate.verdict"]
        p12_blocks = [v for v in verdicts if v.get("entity_id") == day1_expense["P12"] and v.get("verdict") == "block"]
        out["p12_block_rules"] = sorted({r for v in p12_blocks for r in v.get("rules_fired", [])})
        if not any("already_flagged_high" in v.get("rules_fired", []) for v in p12_blocks):
            failures.append("verdict_rule_missing: no block verdict on P12 expense naming already_flagged_high")
        wrong_blocks = [v for v in verdicts if v.get("entity_id") in {day1_expense["P01"], day1_expense["P16"]} and v.get("verdict") == "block"]
        if wrong_blocks:
            failures.append("verdict_unexpected_block: P01/P16 day-1 expense blocked")
        out["reports_posted"] = sum(e.get("type") == "report.posted" for e in events)
        if out["reports_posted"] < 2:
            failures.append("report_missing: audit report not posted for both days")

        flags1 = op.json("GET", f"/flags?episode_id={ep}", "flags_read_failed")
        emp_flags1 = [f for f in flags1 if f.get("entity_type") == "employee" and f.get("severity") == "high"]
        if len(emp_flags1) != 1 or emp_flags1[0].get("entity_id") != emp_ids["P12"]:
            failures.append("flag_mismatch_final: expected exactly one high employee flag (P12) after day 1")

        out["day0_expense_status"] = {pid: expenses[day0_expense[pid]].get("status") for pid in emp_ids}
        unpaid0 = [pid for pid in emp_ids if expenses[day0_expense[pid]].get("status") != "paid"]
        if unpaid0:
            failures.append(f"day0_expense_blocked: {sorted(unpaid0)} — the check itself must never block a payment")
    finally:
        if blue is not None:
            blue.send_signal(signal.SIGTERM)
            try:
                blue.wait(timeout=10)
            except subprocess.TimeoutExpired:
                blue.kill()

    provider = provider_log_summary()
    out["provider_logs"] = provider
    if not provider["all_billable_false"]:
        failures.append("billable_true: provider log entry with billable != false")
    if provider["identity_checks"] < 3:
        failures.append("provider_logs_missing: fewer than 3 identity-verification entries")

    out["acceptance_passed"] = not failures
    return out


def main() -> int:
    try:
        result = run()
    except AssertionError as exc:
        result = {"scenario": "crs_episode", "acceptance_passed": False, "failure_codes": [str(exc)]}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["acceptance_passed"] else 2


if __name__ == "__main__":
    sys.exit(main())
