"""Manual, billable SDK acceptance against a real local Ledger. Never runs in pytest.

Proves, against the Docker-free local stack (battlefield + Postgres, mock red/green):
  happy       - one orchestrator-driven live audit turn: real Ledger commit with receipt bound to the
                SDK permission/event ID, exactly one agent.tool_call/tool_result pair per call, no
                duplicate execution (audit_log keyed by tool_use_id), /gate < 8s under live audit load.
  interrupted - battlefield is killed before the report write is sent; the receipt must record
                "unknown" (never assumed), no blind retry, and no duplicate commit after recovery.

The audit agent here subclasses AuditAgent with a test-only guard bypass (the shipped guard is
unchanged); everything else - orchestrator, turn guard, gate, ledger, SDK session - is real.

Run (stack up, tokens in .local-stack/env):
  set -a; . ../.local-stack/env; set +a
  BATTLEFIELD_URL=http://127.0.0.1:8000 BATTLEFIELD_PID_FILE=../.local-stack/pids/battlefield \
  AGENT_TOKEN="$AGENT_TOKEN_BLUE" OPERATOR_TOKEN="$OPERATOR_TOKEN" \
  uv run --no-sync python tests/sdk_real_ledger_acceptance.py --allow-model-call --scenario happy
"""

import argparse
import asyncio
import contextlib
import io
import json
import math
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

HARD_CAP_SEC = 900


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)]


def _rows(body: Any) -> list[dict[str, Any]]:
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("events", "audit_log", "rows", "items", "results"):
            if isinstance(body.get(key), list):
                return body[key]
    return []


def _failure_codes(o: dict[str, Any]) -> list[str]:
    """Fixed reason codes only. Neither model output nor exception prose is published."""
    codes = []
    if o.get("error_type"):
        codes.append("acceptance_exception")
    if o.get("cleanup_pending"):
        codes.append("cleanup_incomplete")
    if o.get("episode_status") != o.get("episode_status_expected"):
        codes.append("episode_unexpected_status")
    interrupted = o.get("scenario") == "interrupted"
    if not interrupted and o.get("turn_returned") is not True:
        codes.append("turn_not_returned")
    if not interrupted and o.get("unresolved_writes"):
        codes.append("writes_unresolved")
    if not o.get("permission_count"):
        codes.append("no_permission_requests")
    # Killing battlefield mid-turn legitimately drops the killed call's result event; pair checks
    # and report-commit proofs only apply to the happy path.
    if not interrupted and (o.get("pairs_matched") is not True or not o.get("blue_tool_calls")):
        codes.append("narration_pair_mismatch")
    if o.get("audit_rows_unbound"):
        codes.append("ledger_write_not_sdk_bound")
    if o.get("duplicate_audit_rows"):
        codes.append("duplicate_ledger_execution")
    if interrupted:
        if o.get("battlefield_killed") is not True:
            codes.append("interruption_not_triggered")
        if o.get("interrupted_receipt_state") != "unknown":
            codes.append("receipt_state_untruthful")
        if o.get("interrupted_commit_count") not in (0, 1):
            codes.append("duplicate_ledger_execution")
    else:
        if o.get("report_committed") is not True or o.get("report_fetchable") is not True:
            codes.append("report_commit_unproven")
        if o.get("report_receipt_state") != "confirmed":
            codes.append("receipt_state_untruthful")
    if o.get("replay_http_status") is not None and (o.get("replayed_ok") is True or o.get("replay_second_commit") is not False):
        codes.append("replay_executed")
    gate_max = o.get("gate_max_ms")
    if not isinstance(gate_max, (int, float)) or isinstance(gate_max, bool) or not 0 <= gate_max < 8000:
        codes.append("gate_latency_unqualified")
    if o.get("gate_errors"):
        codes.append("gate_errors_under_load")
    credits = o.get("factory_credits")
    if not interrupted and (not isinstance(credits, (int, float)) or isinstance(credits, bool) or not math.isfinite(credits) or credits < 0):
        codes.append("usage_unavailable")
    if o.get("runtime_guard_changed") is not False or o.get("crs_or_provider_access") is not False:
        codes.append("isolation_unqualified")
    return codes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-model-call", action="store_true", help="Required; this runs billable Factory SDK turns.")
    parser.add_argument("--scenario", choices=("happy", "interrupted"), default="happy")
    parser.add_argument("--seed", type=int, default=47)
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--port", type=int, default=8013)
    args = parser.parse_args(argv)
    if not args.allow_model_call:
        parser.error("--allow-model-call is required; this acceptance can consume Factory credits")

    blue = Path(__file__).resolve().parents[1]
    root = blue.parent
    sys.path[:0] = [str(blue), str(root / "agentkit")]
    import httpx
    import uvicorn

    from agentkit import DroidAgent, make_agent_app
    from agentkit.config import AgentSettings

    AgentSettings.model_config["env_file"] = None
    os.environ.update(AGENT_NAME="blue", DRY_RUN="false", BLUE_GATE_LLM_PROVIDER="", BLUE_GATE_LLM_API_KEY="", CRS_USERNAME="", CRS_PASSWORD="")
    base = os.environ.get("BATTLEFIELD_URL", "http://127.0.0.1:8000")
    agent_token = os.environ["AGENT_TOKEN"]  # blue's own per-agent token
    op_token = os.environ["OPERATOR_TOKEN"]

    from server import extra

    import agentkit.ledger_client as ledger_mod
    from agentkit.models import GateRequest
    from agentkit.sync import TurnLock
    from audit import tools
    from audit.agent import AUDIT_TOOL_IDS, AuditAgent

    stages: list[str] = []
    permissions: list[tuple[str, str]] = []
    turns: list[Any] = []
    gate_samples: list[dict[str, Any]] = []
    write_started = threading.Event()  # live turns run on their own thread/loop
    stop_hammer = threading.Event()
    killed = {"done": False, "key": None, "kind": None}
    restarted: list[subprocess.Popen[bytes]] = []

    class AcceptanceAudit(AuditAgent):
        # Test-only guard bypass inside the coordinated sandbox; the shipped AuditAgent guard is unchanged.

        def __init__(self, settings):
            super().__init__(settings)
            if self.autonomy != "off" or self.identity_policy() != "strict" or not isinstance(self.audit_lock, TurnLock):
                raise RuntimeError("Merge the strict policy and shared adapter prerequisites first")
            assert self._tool_ids == list(AUDIT_TOOL_IDS)

        async def on_permission(self, request):
            permissions.extend((u.tool_use_id, u.tool) for u in self.tool_uses(request))
            return await super().on_permission(request)

        async def _droid_turn(self, req, emitter):
            stages.append("shared_sdk_entry")
            return await DroidAgent._droid_turn(self, req, emitter)

        async def run_turn(self, req, *a, **kw):
            try:
                result = await super().run_turn(req, *a, **kw)
            except Exception as exc:  # keep the failure, never the prose
                turns.append(exc)
                raise
            turns.append(result)
            return result

    def forbid_provider():
        raise AssertionError("Sponsor/provider construction is forbidden")

    tools.crs_client = forbid_provider

    def kill_battlefield() -> None:
        pid_file = os.environ.get("BATTLEFIELD_PID_FILE")
        if pid_file:
            with contextlib.suppress(Exception):
                os.kill(int(Path(pid_file).read_text().strip()), signal.SIGKILL)
        deadline = time.monotonic() + 5
        self_pid = os.getpid()
        while time.monotonic() < deadline:  # reap any orphaned child still LISTENING on :8000
            with contextlib.suppress(Exception):
                # -sTCP:LISTEN is load-bearing: without it lsof also returns processes (like this
                # one) that merely hold client connections TO :8000, and the reaper kills itself.
                out = subprocess.run(["lsof", "-ti", "tcp:8000", "-sTCP:LISTEN"], capture_output=True, text=True, timeout=5).stdout.split()
                if not out:
                    return
                for pid in out:
                    if int(pid) != self_pid:
                        os.kill(int(pid), signal.SIGKILL)
            time.sleep(0.2)

    def start_battlefield() -> None:
        env = dict(os.environ, SCHEMA_PATH=str(root / "contracts" / "schema.sql"), UV_NO_SYNC="1", UV_NO_ENV_FILE="1")
        log = open(root / ".local-stack" / "logs" / "battlefield.log", "ab")
        restarted.append(
            subprocess.Popen(
                ["uv", "run", "--quiet", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
                cwd=root / "battlefield",
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        )

    def wrap_write(name: str) -> None:
        original = getattr(ledger_mod.LedgerClient, name)

        async def probe(self, *a, _original=original, **kw):
            write_started.set()
            if args.scenario == "interrupted" and not killed["done"]:
                killed["done"] = True
                killed["key"] = kw.get("tool_use_id")
                killed["kind"] = name
                stages.append("battlefield_killed_before_report_send")
                kill_battlefield()
            return await _original(self, *a, **kw)

        setattr(ledger_mod.LedgerClient, name, probe)

    # Kill on the FIRST write of any kind (flag, freeze, or report): model latency variance means
    # a turn may not reach post_report inside the audit budget, and the receipt-under-interruption
    # proof holds for any write kind.
    for write_name in ("raise_flag", "freeze_vendor", "post_report"):
        wrap_write(write_name)

    def gate_payload(episode_id: str, day: int) -> dict[str, Any]:
        return GateRequest(
            episode_id=episode_id,
            day=day,
            controller_mode="enforce",
            agent="green",
            idempotency_key=uuid4().hex,
            action="invoices.pay",
            entity_type="invoice",
            entity_id="i",
            amount=400,
            context={
                "vendor": {"id": "v", "episode_id": episode_id, "created_day": -100, "status": "active"},
                "invoice": {
                    "id": "i",
                    "episode_id": episode_id,
                    "vendor_id": "v",
                    "amount": 400,
                    "invoice_number": "INV-2",
                    "po_id": None,
                    "received_day": day,
                    "status": "approved",
                },
                "po": None,
                "vendor_paid_invoices": [],
                "vendor_recent_changes": [],
                "flags": [],
            },
        ).model_dump()

    async def hammer() -> None:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{args.port}", headers={"Authorization": f"Bearer {agent_token}"}, timeout=8) as client:
            while not stop_hammer.is_set():
                start = time.perf_counter()
                try:
                    response = await client.post("/gate", json=gate_payload(EPISODE[0], DAY[0]))
                    gate_samples.append({"ts": time.time(), "ms": round((time.perf_counter() - start) * 1000, 2), "status": response.status_code})
                except Exception:
                    gate_samples.append({"ts": time.time(), "ms": 8000.0, "status": 0})
                await asyncio.sleep(0.05)

    EPISODE: list[str] = ["pending"]
    DAY: list[int] = [1]

    async def wait_health(url: str, token: str | None, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        async with httpx.AsyncClient(headers=headers, timeout=3) as client:
            while time.monotonic() < deadline:
                with contextlib.suppress(Exception):
                    if (await client.get(url)).status_code == 200:
                        return True
                await asyncio.sleep(0.5)
        return False

    async def run() -> dict[str, Any]:
        settings = AgentSettings(
            AGENT_NAME="blue",
            DRY_RUN=False,
            AGENT_TOKEN=agent_token,
            BATTLEFIELD_URL=base,
            DROID_MODEL=os.environ.get("DROID_MODEL", "gemini-3.8-flash"),
            DROID_REASONING="low",
            TURN_TIMEOUT_SEC=int(os.environ.get("ACCEPTANCE_TURN_TIMEOUT_SEC", "360")),  # battlefield waits its own TURN_TIMEOUT_SEC + 5
            _env_file=None,
        )
        app = make_agent_app(AcceptanceAudit, settings=settings, extra_routes=extra)
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="warning"))
        serve = asyncio.create_task(server.serve())
        try:
            if not await wait_health(f"http://127.0.0.1:{args.port}/health", None, 30):
                return {"error_type": "acceptance_blue_not_healthy", "stages": stages}
            stages.append("acceptance_blue_serving")
            async with httpx.AsyncClient(base_url=base, headers={"Authorization": f"Bearer {op_token}"}, timeout=15) as op:
                episode = (await op.post("/api/episodes", json={"controller_mode": "enforce", "seed": args.seed, "days": args.days})).json()
                ep = episode["id"]
                EPISODE[0], DAY[0] = ep, 1
                hammer_task = asyncio.create_task(hammer())
                try:
                    await op.post(f"/api/episodes/{ep}/start")
                    stages.append("episode_started")
                    status, deadline = "running", time.monotonic() + 480
                    while time.monotonic() < deadline:
                        if args.scenario == "interrupted" and killed["done"]:
                            await asyncio.sleep(5)  # let the dying turn settle its receipts
                            break
                        try:
                            status = (await op.get(f"/api/episodes/{ep}")).json().get("status", "unknown")
                        except Exception:
                            status = "unreachable"
                        if status in {"finished", "failed", "paused"}:
                            break
                        await asyncio.sleep(2)
                finally:
                    stop_hammer.set()
                    await asyncio.gather(hammer_task, return_exceptions=True)
                if args.scenario == "interrupted" and killed["done"]:
                    start_battlefield()
                    if not await wait_health(f"{base}/api/health", op_token, 90):
                        return {"error_type": "battlefield_restart_failed", "stages": stages, "episode_id": ep}
                    stages.append("battlefield_restarted")
                    with contextlib.suppress(Exception):
                        status = (await op.get(f"/api/episodes/{ep}")).json().get("status", "unknown")
                return await verify(op, app, ep, status)
        finally:
            server.should_exit = True
            await asyncio.wait({serve}, timeout=5)

    async def verify(op, app, ep: str, status: str) -> dict[str, Any]:
        agent = app.state.agent
        events = _rows((await op.get("/api/events", params={"episode_id": ep, "limit": 5000})).json())
        perm_ids = {pid for pid, _ in permissions}
        calls = [e["payload"] for e in events if e.get("type") == "agent.tool_call" and e.get("payload", {}).get("tool_use_id") in perm_ids]
        results = [e["payload"] for e in events if e.get("type") == "agent.tool_result" and e.get("payload", {}).get("tool_use_id") in perm_ids]
        call_ids = sorted(p.get("tool_use_id") for p in calls)
        result_ids = sorted(p.get("tool_use_id") for p in results)
        pairs_matched = bool(call_ids) and call_ids == result_ids and len(set(call_ids)) == len(call_ids)

        audit_rows = [r for r in _rows((await op.get("/api/audit_log", params={"episode_id": ep, "limit": 5000})).json()) if r.get("agent") == "blue"]
        # Only sub-300 rows are executions; the turn guard's audited 409 rejections share the key but commit nothing.
        executions = [r for r in audit_rows if isinstance(r.get("http_status"), int) and 200 <= r["http_status"] < 300]
        rejections = len(audit_rows) - len(executions)
        seen: dict[tuple[str, str], int] = {}
        unbound = 0
        for row in executions:
            key = row.get("tool_use_id")
            if key not in perm_ids:
                unbound += 1
            seen[(row.get("action", ""), key or "")] = seen.get((row.get("action", ""), key or ""), 0) + 1
        duplicates = sum(1 for n in seen.values() if n > 1)

        receipts = [r for (episode_id, _), rs in agent.receipts.items() if episode_id == ep for r in rs]
        report_receipt = next((r for r in receipts if r.kind == "report"), None)
        report_id = report_receipt.receipt_id if report_receipt else None
        report_committed = any(r.get("action", "").startswith("reports") for r in executions)
        report_fetchable = False
        if report_id:
            with contextlib.suppress(Exception):
                report_fetchable = (await op.get(f"/api/reports/{report_id}")).status_code == 200

        # Interrupted scenario: prove truthfulness for the write that was actually interrupted
        # (flag, freeze, or report), identified by the key captured in the wrap.
        interrupted_receipt_state = None
        interrupted_commit_count = None
        if args.scenario == "interrupted" and killed["done"] and killed["key"]:
            receipt = next((r for r in receipts if r.tool_use_id == killed["key"]), None)
            interrupted_receipt_state = getattr(receipt, "state", None)
            interrupted_commit_count = sum(1 for r in executions if r.get("tool_use_id") == killed["key"])

        replay_status, replay_second_commit = None, False
        replay_kind = killed["kind"] if (args.scenario == "interrupted" and killed["done"]) else "post_report"
        replay_key = (
            killed["key"] if (args.scenario == "interrupted" and killed["done"]) else next((pid for pid, tool in permissions if tool == "post_report"), None)
        )
        if replay_kind and replay_key and replay_kind != "freeze_vendor":
            day = next((d for (e, d), rs in agent.receipts.items() if e == ep for r in rs), 1)
            route, body = (
                (
                    "/api/flags",
                    {
                        "entity_type": "vendor",
                        "entity_id": "vnd_acceptance_replay",
                        "severity": "low",
                        "reason": "acceptance replay probe",
                    },
                )
                if replay_kind == "raise_flag"
                else ("/api/reports", {"day": day, "markdown": "acceptance replay probe"})
            )
            before = sum(1 for r in executions if r.get("tool_use_id") == replay_key)
            replay = await op.post(
                route,
                json=body,
                headers={
                    "X-Agent": "blue",
                    "X-Episode": ep,
                    "X-Day": str(day),
                    "X-Tool-Use-Id": replay_key,
                    "Authorization": f"Bearer {agent_token}",
                },
            )
            replay_status = replay.status_code
            after = _rows((await op.get("/api/audit_log", params={"episode_id": ep, "limit": 5000})).json())
            replay_second_commit = (
                sum(
                    1
                    for r in after
                    if r.get("agent") == "blue"
                    and r.get("tool_use_id") == replay_key
                    and isinstance(r.get("http_status"), int)
                    and 200 <= r["http_status"] < 300
                )
                > before
            )

        gaps = [g for sess in getattr(agent, "_sessions", {}).values() for g in getattr(sess, "gaps", [])]
        latencies = [s["ms"] for s in gate_samples]
        turn = turns[-1] if turns else None
        turn_returned = turn is not None and not isinstance(turn, Exception)
        turn_ok_raw = bool(turn_returned and getattr(turn, "ok", False))
        # CRS credentials are deliberately empty here (separate acceptance), so a "partial" turn whose
        # only deficit is crs_identity_check unavailable is still a complete ledger-side audit.
        unresolved = sum(1 for r in receipts if r.state in {"unknown", "failed"})
        return {
            "scenario": args.scenario,
            "model": app.state.settings.droid_model,
            "episode_id": ep,
            "episode_status": status,
            "episode_status_expected": ("paused" if args.scenario == "interrupted" else "finished") if status != "failed" else status,
            "turn_returned": turn_returned,
            "turn_ok_raw": turn_ok_raw,
            "unresolved_writes": unresolved,
            "factory_credits": float(turn.usage.factory_credits) if turn_returned and turn.usage else None,
            "permission_count": len(permissions),
            "blue_tool_calls": len(calls),
            "blue_tool_results": len(results),
            "pairs_matched": pairs_matched,
            "audit_rows": len(audit_rows),
            "audit_rejection_rows": rejections,
            "audit_rows_unbound": unbound,
            "duplicate_audit_rows": duplicates,
            "report_committed": report_committed,
            "report_fetchable": report_fetchable,
            "report_receipt_state": getattr(report_receipt, "state", None),
            "receipt_states": sorted({f"{r.kind}:{r.state}" for r in receipts}),
            "gaps_count": len(gaps),
            "replay_http_status": replay_status,
            "replayed_ok": isinstance(replay_status, int) and replay_status < 300,
            "replay_second_commit": replay_second_commit,
            "gate_samples": len(gate_samples),
            "gate_max_ms": max(latencies) if latencies else None,
            "gate_p95_ms": _p95(latencies),
            "gate_errors": sum(1 for s in gate_samples if s["status"] != 200),
            "battlefield_killed": killed["done"],
            "interrupted_write_kind": killed["kind"] if args.scenario == "interrupted" else None,
            "interrupted_receipt_state": interrupted_receipt_state,
            "interrupted_commit_count": interrupted_commit_count,
            "stages": stages,
            "runtime_guard_changed": False,
            "crs_or_provider_access": False,
            "ready": False,
        }

    output: dict[str, Any]
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        try:
            with tempfile.TemporaryDirectory(prefix="blue-ledger-acceptance-") as cwd:
                previous = Path.cwd()
                try:
                    os.chdir(cwd)
                    output = asyncio.run(asyncio.wait_for(run(), HARD_CAP_SEC))
                finally:
                    os.chdir(previous)
        except Exception as exc:
            output = {"error_type": type(exc).__name__, "stages": stages, "runtime_guard_changed": False, "crs_or_provider_access": False}
    for proc in restarted:
        with contextlib.suppress(Exception):
            proc.terminate()
    output["failure_codes"] = _failure_codes(output)
    output["acceptance_passed"] = not output["failure_codes"]
    print(json.dumps(output, sort_keys=True))
    return 0 if output["acceptance_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
