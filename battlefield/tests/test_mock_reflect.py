"""Unit: the mock agents' deterministic adaptation across generations (/reflect, daily debriefs, learned
gate rules). No database; the mocks only ever see debrief/review items and their own playbook."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from mock_agents import server as mock


def atk(aid: str, scheme: str, outcome: str, caught_by: list | None = None) -> dict[str, Any]:
    return {"kind": "attack", "attack_id": aid, "scheme_id": scheme, "outcome": outcome, "caught_by": caught_by or []}


def test_red_drops_a_scheme_caught_twice_and_favours_what_paid() -> None:
    items = [atk("a1", "bank_swap", "blocked"), atk("a2", "bank_swap", "flagged"), atk("a3", "ghost_vendor", "extracted")]
    pb, why = mock.red_adapt({}, items)
    assert pb["dropped"] == ["bank_swap"] and pb["won"] == {"ghost_vendor": 1}
    assert "bank_swap" in why and "ghost_vendor" in why
    picks = [mock.red_choose(pb, d) for d in range(8)]
    assert "bank_swap" not in picks and picks.count("ghost_vendor") > picks.count("duplicate_invoice")


def test_red_counts_each_attack_once_and_is_deterministic() -> None:
    items = [atk("a1", "bank_swap", "blocked")]
    once, _ = mock.red_adapt({}, items)
    twice, _ = mock.red_adapt(once, items)  # the same item again (window overlap, then the review)
    assert once == twice and once["caught"] == {"bank_swap": 1} and once["dropped"] == []
    assert mock.red_adapt({}, items) == mock.red_adapt({}, items)


def test_red_never_drops_every_scheme() -> None:
    items = [atk(f"{sid}{i}", sid, "blocked") for sid in mock.SCHEME_IDS for i in range(2)]
    pb, _ = mock.red_adapt({}, items)
    assert len(pb["dropped"]) == len(mock.SCHEME_IDS) - 1
    assert {mock.red_choose(pb, d) for d in range(4)} == {mock.SCHEME_IDS[0]}


def test_empty_playbook_is_the_plain_rotation() -> None:
    assert [mock.red_choose({}, d) for d in range(8)] == [mock.SCHEMES[d % len(mock.SCHEMES)]["id"] for d in range(8)]


def test_blue_learns_from_misses_only() -> None:
    caught = atk("a1", "ghost_vendor", "blocked", caught_by=[{"kind": "verdict", "id": "v1", "day": 2}])
    pb, _ = mock.blue_adapt({}, [caught])
    assert pb["learned"] == [] and pb["near_band"] == mock.NEAR_BAND
    pb, _ = mock.blue_adapt(pb, [caught, atk("a2", "threshold_split", "extracted"), atk("a3", "ghost_vendor", "extracted")])
    assert pb["learned"] == ["learned:near_threshold_wide", "learned:young_vendor_any_amount"] and pb["near_band"] == 0.9
    again, _ = mock.blue_adapt(pb, [atk("a2", "threshold_split", "extracted")])
    assert again == pb  # a2 already counted: the band does not keep widening


class FakeLedger:
    def __init__(self, pb: dict | None) -> None:
        self.pb, self.puts = pb, []

    async def get_playbook(self) -> dict | None:
        return self.pb

    async def put_playbook(self, content: dict, rationale: str, base_version: int) -> dict:
        self.puts.append((content, base_version))
        return {}


async def test_adapt_playbook_writes_only_in_lineages_and_only_on_change() -> None:
    plain = FakeLedger(None)
    assert await mock.adapt_playbook(plain, {"items": [atk("a1", "bank_swap", "blocked")]}, mock.red_adapt) == {} and not plain.puts
    ln = FakeLedger({"version": 4, "content": {}})
    content = await mock.adapt_playbook(ln, {"items": [atk("a1", "bank_swap", "blocked")]}, mock.red_adapt)
    assert ln.puts == [(content, 4)] and content["caught"] == {"bank_swap": 1}
    quiet = FakeLedger({"version": 5, "content": content})
    await mock.adapt_playbook(quiet, {"items": [atk("a1", "bank_swap", "blocked")]}, mock.red_adapt)
    assert not quiet.puts


def _reflect_body(content: dict, items: list) -> dict[str, Any]:
    return {
        "lineage_id": "ln_1",
        "generation": 1,
        "episode_id": "ep_1",
        "review": {"items": items},
        "playbook": {"version": 3, "generation": 1, "source": "turn", "content": content},
    }


@pytest.mark.parametrize("agent", ["red", "blue", "green"])
async def test_reflect_endpoint(monkeypatch: pytest.MonkeyPatch, agent: str) -> None:
    monkeypatch.setattr(mock.s, "agent_name", agent)
    monkeypatch.setattr(mock.s, "internal_token", "tok")
    items = [atk("a1", "threshold_split", "extracted"), atk("a2", "threshold_split", "extracted")]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=mock.app), base_url="http://agent") as cl:
        assert (await cl.post("/reflect", json=_reflect_body({}, items))).status_code == 401
        r = await cl.post("/reflect", json=_reflect_body({}, items), headers={"Authorization": "Bearer tok"})
        assert r.status_code == 200 and r.json()["ok"] is True
        if agent == "green":
            assert r.json()["playbook"] is None
            return
        learned = r.json()["playbook"]
        assert learned is not None
        same = await cl.post("/reflect", json=_reflect_body(learned, items), headers={"Authorization": "Bearer tok"})
        assert same.json()["playbook"] is None  # nothing new: keep the current version


def _gate_req(**kw: Any) -> dict[str, Any]:
    body = {
        "idempotency_key": "tu_1",
        "episode_id": "ep_1",
        "day": 10,
        "controller_mode": "enforce",
        "agent": "green",
        "action": "invoices.approve",
        "entity_type": "invoice",
        "entity_id": "inv_1",
        "amount": 800.0,
        "context": {"vendor": {"created_day": 8}, "invoice": {"invoice_number": "A-1"}},
    }
    return {**body, **kw}


async def _gate(monkeypatch: pytest.MonkeyPatch, body: dict[str, Any]) -> dict[str, Any]:
    monkeypatch.setattr(mock.s, "internal_token", "tok")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=mock.app), base_url="http://blue") as cl:
        r = await cl.post("/gate", json=body, headers={"Authorization": "Bearer tok"})
    assert r.status_code == 200, r.text
    return r.json()


async def test_gate_applies_learned_rules_from_the_playbook(monkeypatch: pytest.MonkeyPatch) -> None:
    async def pb(req: Any) -> dict:
        return {"learned": ["learned:young_vendor_any_amount", "learned:near_threshold_wide"], "near_band": 0.9}

    monkeypatch.setattr(mock, "blue_playbook", pb)
    young = await _gate(monkeypatch, _gate_req(playbook_version=2))  # $800 from a 2-day-old vendor: under the base rule
    assert young["verdict"] == "block" and young["rules_fired"] == ["learned:young_vendor_any_amount"]
    wide = await _gate(monkeypatch, _gate_req(playbook_version=2, amount=4600.0, context={"vendor": {"created_day": -100}, "invoice": {}}))
    assert wide["rules_fired"] == ["learned:near_threshold_wide"]


async def test_gate_without_a_lineage_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    j = await _gate(monkeypatch, _gate_req())  # no playbook_version: never reads a playbook
    assert (j["verdict"], j["rules_fired"]) == ("allow", [])
