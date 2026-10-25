import asyncio

import httpx
import pytest
from fastapi import HTTPException
from server import extra

from agentkit import make_agent_app
from audit.agent import AuditAgent
from gate import engine


@pytest.mark.parametrize("mode", ["off", "shadow", "enforce"])
@pytest.mark.parametrize(
    "change",
    [
        {"action": "invoices.approve"},
        {"entity_type": "expense"},
        {"entity_id": "another-invoice"},
        {"entity_id": None},
        {"amount": 9000},
        {"amount": None},
    ],
)
async def test_retained_key_rejects_different_action(gate_request, mode, change):
    req = gate_request(mode=mode)
    retained = await engine.decide(req, dry_run=True)
    changed = req.model_copy(deep=True, update=change)
    with pytest.raises(HTTPException) as error:
        await engine.decide(changed, dry_run=True)
    assert error.value.status_code == 409
    assert error.value.detail == "idempotency key reused for a different action"
    assert await engine.decide(req, dry_run=True) == retained


@pytest.mark.parametrize("amount", [1199.991, 1200.0, 1200.009])
async def test_subcent_rounding_keeps_first_binding(gate_request, amount):
    req = gate_request()
    retained = await engine.decide(req, dry_run=True)
    req.amount = amount
    req.context["vendor"]["status"] = "frozen"
    assert await engine.decide(req, dry_run=True) == retained
    req.amount = 1200.02
    with pytest.raises(HTTPException) as error:
        await engine.decide(req, dry_run=True)
    assert error.value.status_code == 409


@pytest.mark.parametrize("amount", [1199.99, 1200.01])
async def test_a_full_cent_is_a_different_amount(gate_request, amount):
    req = gate_request()
    await engine.decide(req, dry_run=True)
    req.amount = amount
    with pytest.raises(HTTPException) as error:
        await engine.decide(req, dry_run=True)
    assert error.value.status_code == 409


async def test_context_mode_day_and_non_gl_args_do_not_rebind_action(gate_request):
    req = gate_request()
    retained = await engine.decide(req, dry_run=True)
    req.context["vendor"]["status"] = "frozen"
    req.controller_mode = "shadow"
    req.day += 1
    req.args = {"diagnostic": "later mirror"}
    assert await engine.decide(req, dry_run=True) == retained


async def test_pending_key_rejects_collision_without_disturbing_singleflight(gate_request, monkeypatch):
    ready, release = asyncio.Event(), asyncio.Event()
    compute = engine._compute
    calls = 0

    async def delayed(req, key, binding, dry_run=False, extra_hits=(), retired=frozenset()):
        nonlocal calls
        calls += 1
        ready.set()
        await release.wait()
        return await compute(req, key, binding, dry_run, extra_hits, retired)

    monkeypatch.setattr(engine, "_compute", delayed)
    req = gate_request()
    original = req.model_copy(deep=True)
    first = asyncio.create_task(engine.decide(req, dry_run=True))
    await asyncio.wait_for(ready.wait(), 1)
    req.amount += 1
    try:
        with pytest.raises(HTTPException) as error:
            await asyncio.wait_for(engine.decide(req, dry_run=True), 1)
        assert error.value.status_code == 409
        duplicate = asyncio.create_task(engine.decide(original, dry_run=True))
    finally:
        release.set()
        result = await first
    assert await duplicate == result
    assert await engine.decide(original, dry_run=True) == result
    assert calls == 1 and not engine._pending


def gl_request(gate_request):
    return gate_request(
        action="gl.post",
        amount=100,
        entity_type="gl_entry",
        entity_id="attempt-one",
        args={"account": "Cash", "debit": 100, "credit": 0, "memo": "Daily entry", "ref_type": None, "ref_id": None},
        context={},
    )


@pytest.mark.parametrize(
    "change",
    [
        {"account": "Revenue"},
        {"debit": 101},
        {"debit": True},
        {"credit": 100},
        {"memo": "Different entry"},
        {"ref_type": "invoice"},
        {"ref_id": "other-reference"},
    ],
)
async def test_gl_key_is_bound_to_posted_fields(gate_request, change):
    req = gl_request(gate_request)
    retained = await engine.decide(req, dry_run=True)
    changed = req.model_copy(deep=True)
    changed.args.update(change)
    with pytest.raises(HTTPException) as error:
        await engine.decide(changed, dry_run=True)
    assert error.value.status_code == 409
    assert await engine.decide(req, dry_run=True) == retained


async def test_gl_identity_ignores_generated_id_and_numeric_json_formatting(gate_request):
    req = gl_request(gate_request)
    retained = await engine.decide(req, dry_run=True)
    original = req.model_copy(deep=True)
    req.entity_id = "attempt-two"
    req.args = dict(reversed(list(req.args.items())))
    req.args["debit"] = 100.0
    assert await engine.decide(req, dry_run=True) == retained
    req.args["memo"] = "Changed after admission"
    with pytest.raises(HTTPException) as error:
        await engine.decide(req, dry_run=True)
    assert error.value.status_code == 409
    assert await engine.decide(original, dry_run=True) == retained


async def test_binding_expires_with_verdict_across_cache_generations(gate_request, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(engine.time, "monotonic", lambda: clock[0])
    req = gate_request(idempotency_key="oldest")
    retained = await engine.decide(req, dry_run=True)
    for i in range(5001):
        await engine.decide(gate_request(idempotency_key=f"filler-{i}"), dry_run=True)
    changed = gate_request(idempotency_key="oldest", amount=9000)
    changed.context["vendor"]["status"] = "frozen"
    clock[0] += 119
    with pytest.raises(HTTPException) as error:
        await engine.decide(changed, dry_run=True)
    assert error.value.status_code == 409
    assert await engine.decide(req, dry_run=True) == retained
    clock[0] += 2
    assert (await engine.decide(changed, dry_run=True)).verdict == "block"
    assert len(engine._cache.generations) == 1


@pytest.mark.parametrize("failure", ["capacity", "compute"])
async def test_unsuccessful_admission_does_not_reserve_action(gate_request, monkeypatch, failure):
    req = gate_request()
    if failure == "capacity":
        monkeypatch.setattr(engine, "MAX_PENDING", 0)
        with pytest.raises(HTTPException) as error:
            await engine.decide(req, dry_run=True)
        assert error.value.status_code == 503
        monkeypatch.setattr(engine, "MAX_PENDING", 256)
    else:
        evaluate = engine.evaluate

        def broken(_):
            raise RuntimeError("offline computation failed")

        monkeypatch.setattr(engine, "evaluate", broken)
        with pytest.raises(RuntimeError, match="offline computation failed"):
            await engine.decide(req, dry_run=True)
        monkeypatch.setattr(engine, "evaluate", evaluate)
    changed = gate_request(idempotency_key=req.idempotency_key, amount=1800)
    assert (await engine.decide(changed, dry_run=True)).verdict == "allow"
    assert not engine._pending


async def test_http_mirror_cannot_lend_cached_allow_to_changed_payment(runtime, gate_request):
    prototype, _, _ = runtime()
    app = make_agent_app(AuditAgent, settings=prototype.s, extra_routes=extra)
    req = gate_request()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://blue", headers={"Authorization": "Bearer test-agent"}) as client:
        first = await client.post("/gate", json=req.model_dump())
        assert first.status_code == 200 and first.json()["verdict"] == "allow"
        req.amount = req.context["invoice"]["amount"] = 9000
        req.context["vendor"]["status"] = "frozen"
        conflict = await client.post("/gate", json=req.model_dump())
        assert conflict.status_code == 409
        assert conflict.json() == {"detail": "idempotency key reused for a different action"}
        req.idempotency_key = "fresh-payment"
        fresh = await client.post("/gate", json=req.model_dump())
        assert fresh.status_code == 200 and fresh.json()["verdict"] == "block"
