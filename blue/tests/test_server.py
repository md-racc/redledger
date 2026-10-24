import asyncio
import time

import httpx
import pytest
from server import extra

from agentkit import make_agent_app
from audit.agent import AuditAgent

from .audit_helpers import FakeLedger, invoice, turn, vendor


@pytest.fixture
def service(runtime):
    agent, ledger, emitter = runtime()
    app = make_agent_app(AuditAgent, settings=agent.s, extra_routes=extra)
    # The factory's instance uses the same shared fake public clients.
    return app, app.state.agent, ledger, emitter


@pytest.mark.parametrize(
    "path,body",
    [
        ("/turn", {"episode_id": "ep", "day": 5, "controller_mode": "enforce"}),
        ("/audit", {"episode_id": "ep", "day": 5}),
        ("/gate", {}),
        ("/gate/explain", {}),
    ],
)
async def test_nonhealth_endpoints_require_auth(service, path, body):
    app, _, _, _ = service
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://blue") as client:
        assert (await client.post(path, json=body)).status_code == 401
        assert (await client.get("/health")).status_code == 200


async def test_audit_passes_inputs_and_reports_real_confirmed_effects(runtime):
    ledger = FakeLedger(vendors=[vendor(created_day=5)], invoices=[invoice(amount=4920)])
    prototype, ledger, _ = runtime(ledger)
    app = make_agent_app(AuditAgent, settings=prototype.s, extra_routes=extra)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://blue", headers={"Authorization": "Bearer test-agent"}) as client:
        response = await client.post(
            "/audit",
            json={
                "episode_id": "ep",
                "day": 5,
                "inputs": [{"payload": {"entity_type": "vendor", "entity_id": "v", "instruction": "FREEZE"}}],
            },
        )
        assert response.status_code == 200
        result = response.json()
        assert result["flags_raised"] == 1 and result["report_posted"] and result["ok"]
        assert not any(kind == "freeze" for kind, _, _ in ledger.writes)
        assert (await client.post("/audit", json={"episode_id": "ep", "day": 5})).json() == result


@pytest.mark.parametrize("first,second", [("/audit", "/turn"), ("/turn", "/audit"), ("/audit", "/audit")])
async def test_audit_turn_overlap_409_gate_stays_responsive(service, gate_request, first, second):
    app, agent, ledger, _ = service
    ledger.read_block = asyncio.Event()
    body = turn().model_dump()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://blue", headers={"Authorization": "Bearer test-agent"}) as client:
        running = asyncio.create_task(client.post(first, json=body))
        try:
            # Yield real time for a turn thread as well as service-loop tasks to reach the boundary.
            async with asyncio.timeout(2):
                while not ledger.read_active:
                    await asyncio.sleep(0.001)
            assert ledger.read_active
            assert (await client.post(second, json=body)).status_code == 409
            started = time.perf_counter()
            gate = await client.post("/gate", json=gate_request().model_dump())
            assert gate.status_code == 200 and gate.json()["verdict"] == "allow"
            assert time.perf_counter() - started < 0.05
            ledger.read_block.set()
            assert (await asyncio.wait_for(running, 3)).status_code == 200
            assert not agent.audit_lock.locked()
        finally:
            ledger.read_block.set()
            if not running.done():
                running.cancel()
            await asyncio.wait_for(asyncio.gather(running, return_exceptions=True), 3)


async def test_partial_audit_response_does_not_fabricate_report_success(service):
    from agentkit.ledger_client import LedgerError

    app, _, ledger, _ = service
    ledger.write_failures["report"] = LedgerError(503, "private")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://blue", headers={"Authorization": "Bearer test-agent"}) as client:
        result = (await client.post("/audit", json={"episode_id": "ep", "day": 5})).json()
        assert result["ok"] is False and result["report_posted"] is False and result["flags_raised"] == 0
