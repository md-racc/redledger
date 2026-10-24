import asyncio
import time

import pytest

from gate import engine


async def test_episode_namespace_and_richer_context_replay(gate_request):
    req = gate_request(idempotency_key="same")
    first = await engine.decide(req)
    req.context["vendor"]["status"] = "frozen"
    assert await engine.decide(req) == first
    req.episode_id = "ep2"
    req.context["vendor"]["episode_id"] = req.context["invoice"]["episode_id"] = "ep2"
    assert (await engine.decide(req)).verdict == "block"


async def test_singleflight_survives_first_caller_cancellation(gate_request, monkeypatch):
    ready = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    class SlowAdvisory:
        enabled = True

        async def judge(self, req, hits):
            nonlocal calls
            calls += 1
            ready.set()
            await release.wait()

    monkeypatch.setattr(engine, "_llm", SlowAdvisory())
    req = gate_request(amount=3000)
    req.context["vendor_recent_changes"] = [
        {
            "vendor_id": "v",
            "field": "bank_account",
            "old_value": "a",
            "new_value": "b",
            "requested_day": 5,
            "status": "approved",
        }
    ]
    first = asyncio.create_task(engine.decide(req))
    await ready.wait()
    others = [asyncio.create_task(engine.decide(req)) for _ in range(10)]
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    req.context["vendor"]["status"] = "frozen"
    release.set()
    results = await asyncio.gather(*others)
    assert calls == 1 and all(r == results[0] for r in results)
    assert await engine.decide(req) == results[0]
    assert not engine._pending


async def test_cache_ttl_and_over_5000_retention(gate_request, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(engine.time, "monotonic", lambda: clock[0])
    first = gate_request(idempotency_key="first")
    response = await engine.decide(first)
    for i in range(5010):
        await engine.decide(gate_request(idempotency_key=f"key-{i}"))
    first.context["vendor"]["status"] = "frozen"
    clock[0] += 119
    assert await engine.decide(first) == response
    clock[0] += 2
    assert (await engine.decide(first)).verdict == "block"


async def test_fixture_gate_latency_under_50ms(gate_request):
    samples = []
    for _ in range(100):
        started = time.perf_counter()
        await engine.decide(gate_request())
        samples.append((time.perf_counter() - started) * 1000)
    assert max(samples) < 50


async def test_response_copies_do_not_poison_retention(gate_request):
    req = gate_request()
    response = await engine.decide(req)
    response.reason = "poison"
    assert (await engine.decide(req)).reason != "poison"


async def test_capacity_rejects_new_admission_without_evicting_promise(gate_request, monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(engine, "MAX_ENTRIES", 2)
    first = gate_request(idempotency_key="first")
    retained = await engine.decide(first)
    await engine.decide(gate_request())
    with pytest.raises(HTTPException) as error:
        await engine.decide(gate_request())
    assert error.value.status_code == 503
    assert await engine.decide(first) == retained


async def test_explicit_dry_run_never_consults_provider(gate_request, monkeypatch):
    class ForbiddenAdvisory:
        enabled = True

        async def judge(self, req, hits):
            raise AssertionError("provider consulted in dry-run")

    monkeypatch.setattr(engine, "_llm", ForbiddenAdvisory())
    req = gate_request(amount=3000)
    req.context["vendor_recent_changes"] = [
        {
            "vendor_id": "v",
            "field": "bank_account",
            "old_value": "a",
            "new_value": "b",
            "requested_day": 5,
            "status": "approved",
        }
    ]
    assert (await engine.decide(req, dry_run=True)).verdict == "escalate"
