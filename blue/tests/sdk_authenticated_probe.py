"""Manual, billable SDK probe. All Ledger HTTP is intercepted; never runs in pytest."""

import argparse
import asyncio
import contextlib
import io
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-model-call", action="store_true", help="Allow one bounded, billable Factory SDK turn using CLI authentication.")
    if not parser.parse_args().allow_model_call:
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
            return await DroidAgent._droid_turn(self, req, emitter)

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
        gate_ms, overlapping, verdict = None, False, None
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
                            overlapping, verdict = not write_done.is_set(), response.json().get("verdict")
                    result = await task
            finally:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        calls = [e["payload"] for e in events if e["type"] == "agent.tool_call"]
        results = [e["payload"] for e in events if e["type"] == "agent.tool_result"]
        key = writes[0]["key"] if len(writes) == 1 else None
        matched = bool(
            key
            and writes[0]["verified"]
            and writes[0]["bound_id"] == key
            and writes[0]["role"] == "blue"
            and (key, "post_report") in permissions
            and [c["tool_use_id"] for c in calls if c["tool"] == "post_report"] == [key]
            and len([r for r in results if r["tool_use_id"] == key and r["ok"]]) == 1
            and agent.receipts[("ep", 5)][0].tool_use_id == key
        )
        return {
            "model": settings.droid_model,
            "autonomy": agent.autonomy,
            "identity": agent.identity_policy(),
            "turn_ok": result.ok,
            "factory_credits": float(result.usage.factory_credits) if result.usage else None,
            "permission_count": len(permissions),
            "intercepted_report_writes": len(writes),
            "tool_calls": len(calls),
            "tool_results": len(results),
            "authenticated_id_binding": matched,
            "invocation_source": writes[0]["source"] if writes else None,
            "stages": stages,
            "gate_ms": gate_ms,
            "gate_during_intercepted_write": overlapping,
            "gate_verdict": verdict,
            "real_ledger_or_crs_access": False,
            "runtime_guard_changed": False,
        }

    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        try:
            with tempfile.TemporaryDirectory(prefix="blue-isolated-sdk-") as cwd:
                os.chdir(cwd)
                output = asyncio.run(probe())
        except Exception as exc:
            output = {"error_type": type(exc).__name__, "runtime_guard_changed": False, "real_ledger_or_crs_access": False}
    print(json.dumps(output, sort_keys=True))
    passed = (
        output.get("turn_ok")
        and output.get("authenticated_id_binding")
        and output.get("gate_during_intercepted_write")
        and output.get("gate_verdict") == "allow"
        and output.get("gate_ms", 8000) < 8000
        and output.get("permission_count") == output.get("tool_calls") == output.get("tool_results") == 1
    )
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
