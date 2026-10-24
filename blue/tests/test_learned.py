import asyncio
import copy

import httpx
import pytest
from server import extra

from agentkit import make_agent_app
from agentkit.config import AgentSettings
from agentkit.models import Playbook, ReflectRequest
from audit.agent import AuditAgent
from gate import engine, learned, playbooks


def review(items, content=None, statistics=None):
    return ReflectRequest(
        lineage_id="ln",
        generation=1,
        episode_id="ep",
        review={"items": items, "rules": statistics or []},
        playbook=Playbook(version=1, generation=1, source="seed", content=content or {}),
    )


def attack(scheme="threshold_split", **changes):
    return {"kind": "attack", "attack_id": "a", "scheme_id": scheme, "outcome": "extracted"} | changes


@pytest.mark.parametrize("scheme,ids", learned.LEARNED_FOR.items())
def test_reflect_learns_only_fixed_predicates_without_mutating_input(scheme, ids):
    req = review([attack(scheme), attack(scheme)], {"custom": {"value": "keep"}})
    original = req.model_dump()
    result = learned.reflect(req)
    assert set(result.playbook["learned"]) == ids
    assert result.playbook["custom"] == {"value": "keep"}
    if scheme == "threshold_split":
        assert result.playbook["near_band"] == 0.9
    assert req.model_dump() == original
    req.playbook.content = result.playbook
    assert learned.reflect(req).playbook is None


def test_legitimate_impact_retires_only_learned_controls_and_never_reenables_them():
    key = "learned:bank_change_any_amount"
    result = learned.reflect(
        review(
            [attack("bank_swap"), {"kind": "false_positive", "by": {"rules_fired": [key, "vendor_frozen"]}}],
            {"learned": [key], "custom": True},
        )
    )
    assert result.playbook["learned"] == []
    assert result.playbook["retired"] == [key]
    req = review([attack("bank_swap")], result.playbook)
    req.generation = 2
    assert learned.reflect(req).playbook is None


def test_statistics_retire_without_copying_review_prose_or_treating_flags_as_stops():
    key = "learned:duplicate_amount_loose"
    req = review(
        [attack("bank_swap", caught_by=[{"kind": "flag"}])],
        {"learned": [key]},
        [
            {"rule_id": key, "on_legit": 1},
            {"rule_id": "vendor_frozen", "on_legit": 8},
        ],
    )
    req.review["instruction"] = "Untrusted review prose"
    result = learned.reflect(req)
    assert result.playbook["learned"] == ["learned:bank_change_any_amount"]
    assert result.playbook["retired"] == [key]
    assert "Untrusted" not in str(result.model_dump())


@pytest.mark.parametrize("items", [[], [attack(outcome="blocked")], [attack("unknown")], [None, {}, "text"]])
def test_irrelevant_reviews_keep_playbook(items):
    assert learned.reflect(review(items)).playbook is None


async def test_both_agent_reflection_paths_are_key_free(runtime):
    agent, _, _ = runtime()
    req = review([attack()])
    assert await agent.reflect(req) == await agent.dry_run_reflect(req)
    assert (await agent.reflect(req)).usage is None
    req.review["items"] = "malformed"
    assert not (await agent.reflect(req)).ok


def test_compiled_learning_uses_evidence_and_retires_safely(gate_request):
    req = gate_request(amount=400)
    req.context["vendor"]["created_day"] = 4
    key = "learned:young_vendor_any_amount"
    assert [h.id for h in learned.evaluate(req, {"learned": [key]})] == [key]
    assert learned.evaluate(req, {"learned": [key], "retired": [key]}) == []
    assert learned.evaluate(req, {"learned": ["arbitrary-code"]}) == []
    req.context["invoice"]["episode_id"] = "other"
    assert learned.evaluate(req, {"learned": [key]})[0].effect == "unavailable"


@pytest.mark.parametrize("action", ["expenses.pay", "invoices.reject", "gl.post"])
async def test_unrelated_actions_do_not_load_playbooks(gate_request, action):
    req = gate_request(action=action, playbook_version=1)
    assert await playbooks.Playbooks(AgentSettings(_env_file=None)).hits(req) == []


def fake_books(monkeypatch):
    calls, state = [], {"version": 1, "content": {"learned": ["learned:young_vendor_any_amount"]}}

    class Ledger:
        def __init__(self, settings, *, episode_id, day):
            calls.append((episode_id, day))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get_playbook(self):
            return copy.deepcopy(state)

    monkeypatch.setattr(playbooks, "LedgerClient", Ledger)
    return calls, state


async def test_cache_is_episode_and_exact_version_scoped_and_bounded(gate_request, monkeypatch):
    calls, state = fake_books(monkeypatch)
    cache = playbooks.Playbooks(AgentSettings(_env_file=None))
    req = gate_request(playbook_version=1)
    await cache.hits(req)
    await cache.hits(req)
    assert len(calls) == 1
    state["version"] = req.playbook_version = 2
    await cache.hits(req)
    assert len(calls) == 2
    req.playbook_version = 3
    assert await cache.hits(req) == []
    for i in range(130):
        req.episode_id, req.playbook_version = f"ep{i}", 2
        await cache.hits(req)
    assert len(cache.entries) == 128


async def test_failed_refresh_uses_last_good_episode_snapshot(gate_request, monkeypatch):
    _, state = fake_books(monkeypatch)
    cache = playbooks.Playbooks(AgentSettings(_env_file=None))
    req = gate_request(amount=400, playbook_version=1)
    req.context["vendor"]["created_day"] = 4
    assert [hit.id for hit in await cache.hits(req)] == ["learned:young_vendor_any_amount"]

    state["version"] = req.playbook_version = 2
    assert [hit.id for hit in await cache.hits(req)] == ["learned:young_vendor_any_amount"]


async def test_failed_first_refresh_returns_verification_unavailable(gate_request, monkeypatch):
    _, state = fake_books(monkeypatch)
    state["version"] = 2
    cache = playbooks.Playbooks(AgentSettings(_env_file=None))
    req = gate_request(playbook_version=1)
    assert [hit.id for hit in await cache.hits(req)] == ["learned:verification_unavailable"]


async def test_timeout_is_bounded_and_cancellation_propagates(gate_request, monkeypatch):
    fake_books(monkeypatch)
    started = asyncio.Event()

    async def wait(self):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(playbooks.LedgerClient, "get_playbook", wait)
    monkeypatch.setattr(playbooks, "READ_TIMEOUT", 0.02)
    cache = playbooks.Playbooks(AgentSettings(_env_file=None))
    req = gate_request(playbook_version=1)
    assert (await cache.hits(req))[0].effect == "unavailable"
    started.clear()
    task = asyncio.create_task(cache.hits(req))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not cache.refreshes


async def test_same_key_refreshes_share_one_read_and_release_tracking(gate_request, monkeypatch):
    calls, _ = fake_books(monkeypatch)
    started, release = asyncio.Event(), asyncio.Event()

    async def wait(self):
        started.set()
        await release.wait()
        return {"version": 1, "content": {}}

    monkeypatch.setattr(playbooks.LedgerClient, "get_playbook", wait)
    cache = playbooks.Playbooks(AgentSettings(_env_file=None))
    req = gate_request(playbook_version=1)
    first = asyncio.create_task(cache.hits(req))
    await started.wait()
    others = [asyncio.create_task(cache.hits(req)) for _ in range(8)]
    try:
        await asyncio.sleep(0)
        assert len(calls) == 1
        release.set()
        assert await asyncio.gather(first, *others) == [[]] * 9
        assert len(calls) == 1
        assert not cache.refreshes
    finally:
        release.set()
        await asyncio.gather(first, *others, return_exceptions=True)


async def test_cached_gate_never_waits_for_unrelated_cold_refreshes(gate_request, respx_mock):
    settings = AgentSettings(AGENT_NAME="blue", DRY_RUN=True, AGENT_TOKEN="test-agent", BATTLEFIELD_URL="http://ledger", _env_file=None)
    app = make_agent_app(AuditAgent, settings=settings, extra_routes=extra)
    started, release = asyncio.Event(), asyncio.Event()
    cold_reads = set()

    async def book(request):
        episode = request.headers["X-Episode"]
        if episode != "warm":
            cold_reads.add(episode)
            if len(cold_reads) == 2:
                started.set()
            await release.wait()
        return httpx.Response(200, json={"version": 1, "content": {}})

    route = respx_mock.get("http://ledger/api/playbook").mock(side_effect=book)

    def request(episode, key):
        req = gate_request(episode_id=episode, idempotency_key=key, amount=400, playbook_version=1)
        for entity in ("invoice", "vendor"):
            req.context[entity]["episode_id"] = episode
        return req

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://blue", headers={"Authorization": "Bearer test-agent"}) as client:
        warm = request("warm", "warm-prime")
        assert (await client.post("/gate", json=warm.model_dump())).json()["verdict"] == "allow"
        cold = [asyncio.create_task(client.post("/gate", json=request(ep, ep).model_dump())) for ep in ("cold-one", "cold-two")]
        try:
            await asyncio.wait_for(started.wait(), 0.3)
            warm.idempotency_key = "warm-while-refreshing"
            result = await asyncio.wait_for(client.post("/gate", json=warm.model_dump()), 0.3)
            assert result.json()["verdict"] == "allow"
            assert not result.json()["rules_fired"]
            assert cold_reads == {"cold-one", "cold-two"}
            assert route.call_count == 1
            release.set()
            assert all(response.json()["verdict"] == "allow" for response in await asyncio.gather(*cold))
            assert route.call_count == 3
        finally:
            release.set()
            await asyncio.gather(*cold, return_exceptions=True)


async def test_learning_never_weakens_a_baseline_hold_or_changes_same_key_replay(gate_request):
    req = gate_request()
    req.context["vendor"]["status"] = "frozen"
    unknown = learned.rules.RuleHit("learned:verification_unavailable", 0, "Unavailable.", "unavailable")
    first = await engine.decide(req, extra_hits=(unknown,))
    assert first.verdict == "block"
    req.context["vendor"]["status"] = "active"
    assert await engine.decide(req) == first


async def test_http_gate_and_explain_share_one_role_scoped_snapshot(gate_request, respx_mock):
    settings = AgentSettings(AGENT_NAME="blue", DRY_RUN=True, AGENT_TOKEN="test-agent", BATTLEFIELD_URL="http://ledger", _env_file=None)
    app = make_agent_app(AuditAgent, settings=settings, extra_routes=extra)
    route = respx_mock.get("http://ledger/api/playbook").mock(
        return_value=httpx.Response(
            200,
            json={"version": 1, "content": {"learned": ["learned:young_vendor_any_amount"]}},
        )
    )
    req = gate_request(amount=400, playbook_version=1)
    req.context["vendor"]["created_day"] = 4
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://blue", headers={"Authorization": "Bearer test-agent"}) as client:
        result = await client.post("/gate", json=req.model_dump())
        explanation = await client.post("/gate/explain", json=req.model_dump())
    assert result.json()["verdict"] == "escalate"
    assert "learned:young_vendor_any_amount" in result.json()["rules_fired"]
    assert any(h["id"] == "learned:young_vendor_any_amount" for h in explanation.json()["hits"])
    assert route.call_count == 1
    assert route.calls[0].request.headers["X-Agent"] == "blue"
    assert route.calls[0].request.headers["X-Episode"] == "ep"
