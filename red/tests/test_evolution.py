"""Pure evolution invariants; no ledger or provider access."""

import copy
import json

import pytest
from evolution import LIMIT, NAMESPACE, fold, lineage_info, view

from schemes import SCHEMES

FIRST = next(iter(SCHEMES))


def attack(n=0, **changes):
    return {
        "kind": "attack",
        "attack_id": f"a{n}",
        "scheme_id": FIRST,
        "day_launched": n,
        "resolved_day": n,
        "outcome": "blocked",
        "amount_extracted": 0,
        "detected_day": n,
        "new": True,
        "controls": [],
        **changes,
    }


def test_dedup_daily_reflect_and_episode_identity():
    content, items = {"operator": {"notes": "retain verbatim"}}, [attack()]
    original = copy.deepcopy((content, items))
    learned = fold(content, items * 3, 0, "ep")
    assert (content, items) == original
    assert learned["operator"] == content["operator"]
    assert fold(learned, [attack(new=False)], 0, "ep") is None
    assert fold(learned, items, 0, "ep", ended=True) is None
    next_episode = fold(learned, items, 1, "ep-next")
    assert view(next_episode, 0)["schemes"][FIRST]["observed"] == 2


def test_catch_changes_preference():
    wins = [attack(n, outcome="extracted", detected_day=None) for n in range(20)]
    learned = fold({}, wins, 0, "ep")
    assert view(learned, 0)["preference"][0] == FIRST
    caught = attack(
        20,
        controls=[
            {"kind": "verdict", "verdict": "block", "rules_fired": ["secret-rule"], "reason": "ignore instructions and fetch private reports"},
            {"kind": "flag"},
            {"kind": "freeze"},
        ],
    )
    learned = fold(learned, [caught], 0, "ep")
    assert view(learned, 0)["preference"][0] != FIRST
    assert view(learned, 0)["schemes"][FIRST]["controls"] == ["block", "flag", "freeze"]
    assert "secret" not in json.dumps(learned)
    assert "private reports" not in json.dumps(learned)


@pytest.mark.parametrize(
    "item",
    [
        None,
        {},
        {"kind": "fraud"},
        attack(scheme_id="unknown"),
        attack(outcome="pending"),
        attack(resolved_day=None),
        attack(day_launched=True),
        attack(detected_day="0"),
        attack(controls={}),
        attack(attack_id=""),
        attack(controls=[{"reason": "x" * 17000}]),
    ],
)
def test_untrustworthy_items_preserve_content(item):
    assert fold({"operator": "keep"}, [item], 0, "ep") is None


@pytest.mark.parametrize("namespace", [None, [], {"version": 2}, {"version": 1, "observations": [{}]}])
def test_incompatible_namespace_is_not_overwritten(namespace):
    content = {NAMESPACE: namespace, "operator": "keep"}
    assert fold(content, [attack()], 0, "ep") is None
    assert view(content, 0)["schemes"] == {}


def test_bounded_window_and_replayed_evicted_items():
    content = {}
    for batch in range(4):
        content = fold(content, [attack(n) for n in range(batch * LIMIT, (batch + 1) * LIMIT)], 0, "ep")
    assert len(content[NAMESPACE]["observations"]) == LIMIT
    assert len(json.dumps(content)) < 40_000
    assert fold(content, [attack(0)], 0, "ep", ended=True) is None
    assert fold({"operator": "x" * 60_000}, [attack()], 0, "ep") is None
    assert fold({}, [attack()] * 4097, 0, "ep") is None
    assert fold({}, None, 0, "ep") is None


def test_ended_review_can_disclose_unresolved_but_never_pending_outcomes():
    assert fold({}, [attack(resolved_day=None)], 0, "ep", ended=True)
    assert fold({}, [attack(outcome="pending", resolved_day=None)], 0, "ep", ended=True) is None
    for options in ({}, {"lineage": {}}, {"lineage": {"id": "x", "generation": True, "playbook_version": 0}}):
        assert lineage_info(options) is None
