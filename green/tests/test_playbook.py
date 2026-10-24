"""Green reflection acceptance: local ASGI only, no SDK/model/ledger traffic."""

import builtins
import json
from copy import deepcopy

import httpx
import pytest
from playbook import MAX_CONTENT_BYTES, MAX_REVIEW_ITEMS, MEMORY_KEY, OUTCOMES, PROCEDURES, reflect_playbook

from agent import PREREQUISITE, GreenAgent
from agentkit import AgentSettings, EventEmitter, LedgerClient, TurnRequest, make_agent_app
from agentkit.models import ReflectRequest


def fraud(outcome="paid", entity_id="private-invoice", entity_type="invoice", **extra):
    action = {"invoice": "invoices.pay", "expense": "expenses.pay", "vendor_change": "vendor_changes.approve"}[entity_type]
    return dict(kind="fraud", entity_type=entity_type, entity_id=entity_id, green_action=action, outcome=outcome, day=2, new=True) | extra


def legitimate(**extra):
    return dict(kind="legit_blocked", entity_type="invoice", entity_id="private-legit", action="invoices.pay", verdict_id="private-verdict", day=2) | extra


def request(items=None, content=None, **review):
    return ReflectRequest(
        lineage_id="private-lineage",
        generation=2,
        episode_id="private-episode",
        review={"items": items or []} | review,
        playbook={"version": 7, "generation": 2, "source": "operator", "content": content or {}, "rationale": "private-operator-prose"},
    )


def settings(dry_run):
    return AgentSettings(
        _env_file=None,
        AGENT_NAME="green",
        AGENT_TOKEN="test-agent",
        FACTORY_API_KEY=None,
        DROID_MODEL=None,
        DROID_REASONING=None,
        DRY_RUN=dry_run,
        TURN_TIMEOUT_SEC=180,
    )


@pytest.mark.parametrize("dry_run", [False, True])
async def test_hooks_dispatch_and_authenticated_endpoint_without_sdk_or_io(monkeypatch, dry_run):
    attempts = []
    original_import = builtins.__import__

    def no_sdk(name, *args, **kwargs):
        if name == "droid_sdk" or name.startswith("droid_sdk."):
            attempts.append(name)
            raise AssertionError("reflection must not import the SDK")
        return original_import(name, *args, **kwargs)

    def forbidden(*args, **kwargs):
        attempts.append("I/O or SDK construction")
        raise AssertionError("reflection must not perform I/O or construct a session")

    monkeypatch.setattr(builtins, "__import__", no_sdk)
    monkeypatch.setattr(LedgerClient, "__init__", forbidden)
    monkeypatch.setattr(EventEmitter, "__init__", forbidden)
    monkeypatch.setattr(GreenAgent, "_droid_available", staticmethod(forbidden))
    monkeypatch.setattr(GreenAgent, "_mcp_server", forbidden)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)
    app = make_agent_app(GreenAgent, settings=settings(dry_run))
    agent, req = app.state.agent, request([fraud()])
    expected = reflect_playbook(req)
    assert await agent.reflect(req) == await agent.dry_run_reflect(req) == expected
    selected = "dry_run_reflect" if dry_run else "reflect"
    hook, calls = getattr(agent, selected), []

    async def tracked(req):
        calls.append(req)
        return await hook(req)

    monkeypatch.setattr(agent, selected, tracked)
    monkeypatch.setattr(agent, "reflect" if dry_run else "dry_run_reflect", forbidden)
    assert await agent.run_reflect(req) == expected
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://green") as client:
        for token in (None, "test-operator", "wrong"):
            headers = {} if token is None else {"Authorization": f"Bearer {token}"}
            assert (await client.post("/reflect", json=req.model_dump(mode="json"), headers=headers)).status_code == 401
        response = await client.post("/reflect", json=req.model_dump(mode="json"), headers={"Authorization": "Bearer test-agent"})
        assert response.status_code == 200 and response.json() == expected.model_dump(mode="json")
        req.playbook.content = response.json()["playbook"]
        req.playbook.version += 1
        replay = await client.post("/reflect", json=req.model_dump(mode="json"), headers={"Authorization": "Bearer test-agent"})
        assert replay.status_code == 200 and replay.json()["ok"] and replay.json()["playbook"] is None
    assert len(calls) == 3 and attempts == []
    assert expected.usage is None


def test_counts_distinguish_disclosures_deduplicate_and_ignore_conflicts():
    items = [fraud(outcome, f"i-{outcome}") for outcome in ("paid", "approved", "blocked", "rejected")]
    items += [fraud(entity_id="e", entity_type="expense"), fraud("approved", "c", "vendor_change"), legitimate()]
    items += [deepcopy(item) for item in items]
    items += [legitimate(day=3, verdict_id="different-verdict"), fraud("paid", "conflict"), fraud("blocked", "conflict")]
    items += [fraud("paid", "mixed"), legitimate(entity_id="mixed")]
    result = reflect_playbook(request(items))
    memory = result.playbook[MEMORY_KEY]
    assert memory["last_review_counts"] == dict(fraud_paid=2, fraud_approved=2, fraud_blocked=1, fraud_rejected=1, legit_blocked=1)
    assert memory["procedure_reminders"] == list(PROCEDURES)
    assert memory["schema_version"] == 1
    assert reflect_playbook(request(list(reversed(items)))) == result


@pytest.mark.parametrize(
    "items",
    [
        [],
        None,
        {},
        "private-prose",
        [None, 1, [], "private-prose", {}],
        [fraud(kind="attack"), fraud(kind="false_positive"), fraud(outcome="pending")],
        [fraud(entity_id=[]), fraud(entity_id=""), fraud(entity_id=" " * 4), fraud(entity_id="x" * 129)],
        [fraud() | {"entity_type": []}, fraud() | {"entity_type": "employee"}, fraud(green_action={}), fraud(outcome=[])],
        [fraud(day=True), fraud(day=-1), fraud(day="2"), fraud(day=None)],
        [fraud("paid", entity_type="vendor_change"), legitimate(verdict_id=None), legitimate(action="gl.post")],
    ],
)
def test_empty_malformed_or_non_green_items_keep_playbook(items):
    req = request(content={"operator": {"note": "keep"}})
    req.review["items"] = items
    before = req.model_dump()
    result = reflect_playbook(req)
    assert result.ok and result.playbook is None and result.usage is None
    assert req.model_dump() == before
    assert "private-prose" not in result.rationale


def test_replay_is_idempotent_with_new_previous_version_and_lessons_persist():
    req = request([fraud()], content={"operator": {"procedure": "private-operator-prose"}})
    result = reflect_playbook(req)
    assert reflect_playbook(req) == result  # Same request, same new content.
    replay = req.model_copy(deep=True)
    replay.playbook.content = result.playbook
    replay.playbook.version += 1
    assert reflect_playbook(replay).playbook is None
    replay.review["items"] = [legitimate()]
    updated = reflect_playbook(replay).playbook[MEMORY_KEY]
    assert updated["last_review_counts"] == dict.fromkeys(OUTCOMES, 0) | {"legit_blocked": 1}
    assert updated["procedure_reminders"] == [PROCEDURES[0], PROCEDURES[2]]
    replay.playbook.content = reflect_playbook(replay).playbook
    replay.playbook.version += 1
    assert reflect_playbook(replay).playbook is None
    replay.review["items"] = []
    assert reflect_playbook(replay).playbook is None  # Empty review does not erase prior memory.


def test_unknown_operator_content_is_preserved_without_input_or_output_aliasing():
    content = {"operator": {"free_text": ["private-note"]}, MEMORY_KEY: {"operator_extension": {"x": [1]}}}
    req = request([fraud()], content=content)
    before = req.model_dump()
    result = reflect_playbook(req)
    assert req.model_dump() == before
    assert result.playbook["operator"] == content["operator"]
    assert result.playbook[MEMORY_KEY]["operator_extension"] == content[MEMORY_KEY]["operator_extension"]
    result.playbook["operator"]["free_text"].append("changed")
    result.playbook[MEMORY_KEY]["operator_extension"]["x"].append(2)
    assert req.model_dump() == before and content == before["playbook"]["content"]


@pytest.mark.parametrize("namespace", [None, "private-note", [], {"schema_version": 2}, {"schema_version": True}])
def test_incompatible_namespace_is_not_overwritten(namespace):
    req = request([fraud()], {MEMORY_KEY: namespace})
    before = req.model_dump()
    assert reflect_playbook(req).playbook is None
    assert req.model_dump() == before


def test_no_input_prose_identifiers_or_other_agent_data_in_learned_content():
    private = "private-pii-and-instructions"
    items = [fraud(entity_id=private, amount=private, field=private, reason=private, controls=[private]), legitimate()]
    req = request(items, score={"dollars_extracted": private}, history=[private], rules=[private], instructions=private)
    result = reflect_playbook(req)
    assert private not in json.dumps(result.model_dump())
    for source in ("private-invoice", "private-legit", "private-verdict", "private-lineage", "private-episode", "private-operator-prose"):
        assert source not in json.dumps(result.model_dump())
    assert set(result.playbook[MEMORY_KEY]) == {"schema_version", "last_review_counts", "procedure_reminders"}
    assert len(result.rationale) < 256 and len(json.dumps(result.playbook)) < 1500
    assert result == reflect_playbook(request(items))  # Only the allowed items matter.
    previous = {MEMORY_KEY: {"schema_version": 1, "procedure_reminders": [private, {}, PROCEDURES[1]]}}
    safe = reflect_playbook(request([fraud()], previous))
    assert safe.playbook[MEMORY_KEY]["procedure_reminders"] == list(PROCEDURES[:2])
    assert private not in json.dumps(safe.model_dump())


def test_limits_keep_content_instead_of_truncating_or_dropping_operator_fields():
    assert reflect_playbook(request([fraud()] * (MAX_REVIEW_ITEMS + 1))).playbook is None
    for size in (MAX_CONTENT_BYTES, MAX_CONTENT_BYTES - 100):
        req = request([fraud()], {"operator": "x" * size})
        before = req.model_dump()
        assert reflect_playbook(req).playbook is None
        assert req.model_dump() == before
    result = reflect_playbook(request([fraud(entity_id=f"i-{i}") for i in range(MAX_REVIEW_ITEMS)]))
    assert result.playbook[MEMORY_KEY]["last_review_counts"]["fraud_paid"] == MAX_REVIEW_ITEMS
    assert len(result.rationale) < 256 and len(json.dumps(result.playbook)) < 1500


async def test_plain_and_lineage_prompts_do_not_consume_memory_or_enable_live_turn():
    agent = GreenAgent(settings(False))
    req = TurnRequest(episode_id="ep", day=3, controller_mode="off")
    expected = "Day 3. Follow the AP procedure in your system prompt. Start with ap_queue."
    assert await agent.build_prompt(req) == expected
    req.options = {"lineage": {"id": "ln", "playbook_version": 7}, "debrief": {"items": [legitimate()]}}
    assert await agent.build_prompt(req) == expected
    assert agent.autonomy == "off"
    with pytest.raises(RuntimeError, match=PREREQUISITE):
        await agent._droid_turn(req, None)
