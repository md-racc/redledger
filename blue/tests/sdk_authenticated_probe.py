"""Manual, billable SDK probe. All Ledger HTTP is intercepted; never runs in pytest."""

import argparse
import asyncio
import contextlib
import io
import json
import math
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any


def _binding_matches(
    permissions: list[tuple[str, str]], writes: list[dict[str, Any]], calls: list[dict[str, Any]], results: list[dict[str, Any]], receipts: list[Any]
) -> bool:
    if not len(writes) == len(calls) == len(results) == len(receipts) == len(permissions) == 1:
        return False
    write, call, result, receipt = writes[0], calls[0], results[0], receipts[0]
    key = write.get("key")
    return bool(
        isinstance(key, str)
        and key
        and write.get("verified") is True
        and write.get("source") in {"permission", "stream", "mcp_meta"}
        and write.get("bound_id") == key
        and write.get("role") == "blue"
        and permissions == [(key, "post_report")]
        and call.get("tool") == "post_report"
        and call.get("tool_use_id") == result.get("tool_use_id") == getattr(receipt, "tool_use_id", None) == key
        and result.get("ok") is True
        and getattr(receipt, "kind", None) == "report"
        and getattr(receipt, "state", None) == "confirmed"
    )


def _turn_failure(result: Any) -> str | None:
    if result is None:
        return "turn_not_returned"
    if isinstance(result, TimeoutError):
        return "turn_timeout"
    if not isinstance(result, Exception) and result.ok:
        return None
    summary = (str(result) if isinstance(result, Exception) else result.summary).lower()
    for marker, code in (
        ("timed out", "turn_timeout"),
        ("strict identity", "strict_identity_failure"),
        ("droid turn ended:", "sdk_unsuccessful_result"),
        ("live audit unavailable", "runtime_guard_reached"),
    ):
        if marker in summary:
            return code
    return "turn_not_successful"


def _failure_codes(output: dict[str, Any]) -> list[str]:
    """Fixed reason codes only. Neither model output nor exception prose is published."""
    codes = []
    if output.get("error_type"):
        codes.append("probe_exception")
    if output.get("cleanup_pending"):
        codes.append("turn_cleanup_incomplete")
    if "actual_session_ids_matched" not in output.get("stages", []):
        codes.append("session_ids_unverified")
    if output.get("turn_ok") is not True:
        codes.append(output.get("turn_failure") or "turn_not_successful")
    for field in ("permission_count", "intercepted_report_writes", "tool_calls", "tool_results"):
        if output.get(field) != 1:
            codes.append(f"{field}_not_one")
    for field in ("authenticated_id_binding", "gate_during_intercepted_write"):
        if output.get(field) is not True:
            codes.append(f"{field}_unverified")
    if output.get("gate_http_status") != 200 or output.get("gate_verdict") != "allow":
        codes.append("gate_not_allowed")
    latency, credits = output.get("gate_ms"), output.get("factory_credits")
    for value, maximum, code in ((latency, 8000, "gate_latency_unqualified"), (credits, math.inf, "usage_unavailable")):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value < maximum:
            codes.append(code)
    if output.get("runtime_guard_changed") is not False or output.get("real_ledger_or_crs_access") is not False:
        codes.append("probe_isolation_unqualified")
    return codes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-model-call", action="store_true", help="Allow one bounded, billable Factory SDK turn using CLI authentication.")
    if not parser.parse_args(argv).allow_model_call:
        parser.error("--allow-model-call is required; this probe can consume Factory credits")
    blue = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(blue), str(blue.parent / "agentkit")]
    import httpx
    import respx

    from agentkit import DroidAgent, make_agent_app
    from agentkit.config import AgentSettings

    AgentSettings.model_config["env_file"] = None
    os.environ.update(AGENT_NAME="blue", DRY_RUN="false", BLUE_GATE_LLM_PROVIDER="", BLUE_GATE_LLM_API_KEY="", CRS_USERNAME="", CRS_PASSWORD="")
    os.environ.pop("FACTORY_API_KEY", None)  # Use existing CLI authentication, not ambient keys.
    from server import extra

    from agentkit.invocation import current_invocation
    from agentkit.models import GateRequest, TurnRequest
    from agentkit.sync import TurnLock
    from audit import tools
    from audit.agent import AUDIT_TOOL_IDS, AuditAgent
    from audit.models import Coverage, Snapshot

    permissions, writes, events, stages = [], [], [], []
    in_write, write_done = threading.Event(), threading.Event()
    snapshot = Snapshot(
        "ep",
        5,
        datasets={k: [] for k in ("vendors", "employees", "invoices", "payments", "flags", "changes", "activity", "purchase_orders")},
        coverage=[Coverage(dataset="controlled_fixture", status="complete")],
    )

    class ProbeAudit(AuditAgent):
        # Test-only guard bypass and synthetic prompt; the real AuditAgent is unchanged.
        system_prompt = "Call post_report exactly once, then say done. Do not call any other tool."

        def __init__(self, settings):
            super().__init__(settings)
            if self.autonomy != "off" or self.identity_policy() != "strict" or not isinstance(self.audit_lock, TurnLock):
                raise RuntimeError("Merge the strict policy and shared adapter prerequisites first")
            assert self._tool_ids == list(AUDIT_TOOL_IDS)

        async def on_permission(self, request):
            stages.append("permission_callback")
            permissions.extend((u.tool_use_id, u.tool) for u in self.tool_uses(request))
            return await super().on_permission(request)

        async def _learn_tool_ids(self, session):
            stages.append("checking_actual_session_ids")
            await super()._learn_tool_ids(session)
            stages.append("actual_session_ids_matched")

        async def build_prompt(self, req):
            session = tools.SESSION.get()
            assert session is not None
            session.snapshot = snapshot
            stages.append("synthetic_prompt_ready")
            return "Isolated contract test with synthetic empty books. Call post_report exactly once, then stop."

        async def _droid_turn(self, req, emitter):
            stages.append("shared_sdk_entry")
            try:
                return await DroidAgent._droid_turn(self, req, emitter)
            except Exception as exc:
                # AuditAgent rewrites the returned summary, so retain a fixed SDK failure code here.
                stages.append(_turn_failure(exc))
                raise

    def forbid_provider():
        raise AssertionError("Sponsor/provider construction is forbidden")

    tools.crs_client = forbid_provider

    async def report(request):
        inv = current_invocation()
        writes.append(
            {
                "key": request.headers.get("X-Tool-Use-Id"),
                "verified": bool(inv and inv.verified),
                "source": inv.source if inv else None,
                "bound_id": inv.tool_use_id if inv else None,
                "role": request.headers.get("X-Agent"),
            }
        )
        in_write.set()
        await asyncio.sleep(2)
        write_done.set()
        return httpx.Response(200, json={"id": "synthetic-report-receipt"})

    def narration(request):
        events.extend(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    async def probe():
        settings = AgentSettings(
            AGENT_NAME="blue",
            DRY_RUN=False,
            AGENT_TOKEN="synthetic-test-agent",
            BATTLEFIELD_URL="http://ledger.invalid",
            FACTORY_API_KEY=None,
            DROID_MODEL="gemini-3.8-flash",
            DROID_REASONING="low",
            TURN_TIMEOUT_SEC=45,
            HTTP_TIMEOUT_SEC=4,
            ESCALATION_TIMEOUT_SEC=1,
            _env_file=None,
        )
        app = make_agent_app(ProbeAudit, settings=settings, extra_routes=extra)
        agent = app.state.agent
        gate_ms, overlapping, verdict, gate_status = None, False, None, None
        result, error_type, cleanup_pending = None, None, False
        with respx.mock(assert_all_mocked=True, assert_all_called=False) as router:
            router.post("http://ledger.invalid/api/reports").mock(side_effect=report)
            router.post("http://ledger.invalid/api/events").mock(side_effect=narration)
            task = asyncio.create_task(agent.run_turn(TurnRequest(episode_id="ep", day=5, controller_mode="enforce")))
            try:
                async with asyncio.timeout(55):
                    while not in_write.is_set() and not task.done():
                        await asyncio.sleep(0.005)
                    if in_write.is_set() and not write_done.is_set():
                        req = GateRequest(
                            episode_id="ep",
                            day=5,
                            controller_mode="enforce",
                            agent="green",
                            idempotency_key="synthetic-concurrent-gate",
                            action="invoices.pay",
                            entity_type="invoice",
                            entity_id="i",
                            amount=400,
                            context={
                                "vendor": {"id": "v", "episode_id": "ep", "created_day": -100, "status": "active"},
                                "invoice": {
                                    "id": "i",
                                    "episode_id": "ep",
                                    "vendor_id": "v",
                                    "amount": 400,
                                    "invoice_number": "INV-2",
                                    "po_id": None,
                                    "received_day": 5,
                                    "status": "approved",
                                },
                                "po": None,
                                "vendor_paid_invoices": [],
                                "vendor_recent_changes": [],
                                "flags": [],
                            },
                        )
                        async with httpx.AsyncClient(
                            transport=httpx.ASGITransport(app), base_url="http://blue", headers={"Authorization": "Bearer synthetic-test-agent"}
                        ) as client:
                            start = time.perf_counter()
                            async with asyncio.timeout(8):
                                response = await client.post("/gate", json=req.model_dump())
                            gate_ms = round((time.perf_counter() - start) * 1000, 3)
                            gate_status = response.status_code
                            overlapping, verdict = not write_done.is_set(), response.json().get("verdict")
                    result = await task
                    stages.append("turn_returned")
            except Exception as exc:
                # Preserve partial observations; never print raw SDK/HTTP/model errors.
                error_type = type(exc).__name__
            finally:
                if not task.done():
                    task.cancel()
                _, pending = await asyncio.wait({task}, timeout=3)
                cleanup_pending = bool(pending)
                if not pending:
                    await asyncio.gather(task, return_exceptions=True)
        calls = [e["payload"] for e in events if e["type"] == "agent.tool_call"]
        results = [e["payload"] for e in events if e["type"] == "agent.tool_result"]
        matched = _binding_matches(permissions, writes, calls, results, agent.receipts.get(("ep", 5), []))
        return {
            "model": settings.droid_model,
            "autonomy": agent.autonomy,
            "identity": agent.identity_policy(),
            "turn_ok": result.ok if result else False,
            "turn_failure": _turn_failure(result),
            "error_type": error_type,
            "cleanup_pending": cleanup_pending,
            "factory_credits": float(result.usage.factory_credits) if result and result.usage else None,
            "permission_count": len(permissions),
            "intercepted_report_writes": len(writes),
            "tool_calls": len(calls),
            "tool_results": len(results),
            "authenticated_id_binding": matched,
            "invocation_source": writes[0]["source"] if writes else None,
            "stages": stages,
            "gate_ms": gate_ms,
            "gate_http_status": gate_status,
            "gate_during_intercepted_write": overlapping,
            "gate_verdict": verdict,
            "real_ledger_or_crs_access": False,
            "runtime_guard_changed": False,
        }

    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        try:
            with tempfile.TemporaryDirectory(prefix="blue-isolated-sdk-") as cwd:
                previous_cwd = Path.cwd()
                try:
                    os.chdir(cwd)
                    output = asyncio.run(probe())
                finally:
                    os.chdir(previous_cwd)
        except Exception as exc:
            output = {
                "error_type": type(exc).__name__,
                "stages": stages,
                "permission_count": len(permissions),
                "intercepted_report_writes": len(writes),
                "runtime_guard_changed": False,
                "real_ledger_or_crs_access": False,
            }
    output["failure_codes"] = _failure_codes(output)
    output["controlled_probe_passed"] = not output["failure_codes"]
    output["ready"] = False
    print(json.dumps(output, sort_keys=True))
    return 0 if output["controlled_probe_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
