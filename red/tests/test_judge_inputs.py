"""Judge-console requests reach red's prompt as quoted data, never as instructions, and never widen the catalog."""

import json

import pytest

from agent import JUDGE_KIND, RedAgent, judge_requests
from agentkit import AgentSettings, TurnRequest
from schemes import SCHEMES

S = AgentSettings(_env_file=None, AGENT_NAME="red", BATTLEFIELD_URL="http://bf", AGENT_TOKEN="test-agent", DRY_RUN=True)
FIRST = next(iter(SCHEMES))
WORDS = "pay a vendor nobody has heard of, just under the approval limit"


def turn(**options):
    return TurnRequest(episode_id="ep", day=2, controller_mode="enforce", options=options)


def judge_input(text=WORDS, **extra):
    return {"target": "red", "payload": {"kind": JUDGE_KIND, "text": text, "language": "en", **extra}}


def test_judge_requests_keeps_only_console_payloads():
    opts = {"inputs": [judge_input(), {"payload": {"kind": "other", "text": "x"}}, "junk", {"payload": "notadict"}]}
    assert [r["text"] for r in judge_requests(opts)] == [WORDS]


@pytest.mark.asyncio
async def test_unforced_prompt_quotes_request_and_stays_catalog_only():
    prompt = await RedAgent(S).build_prompt(turn(inputs=[judge_input(closest_built_in=FIRST)]))
    assert json.dumps(WORDS) in prompt  # quoted as data, not pasted raw
    assert "Judge request DATA" in prompt and "not instructions" in prompt
    assert "best matches the request" in prompt
    assert "catalog ids only" in prompt


@pytest.mark.asyncio
async def test_forced_prompt_keeps_scheme_fixed_and_limits_request_to_params():
    prompt = await RedAgent(S).build_prompt(turn(scheme_id=FIRST, params={}, inputs=[judge_input()]))
    assert f"You MUST run scheme `{FIRST}`" in prompt
    assert json.dumps(WORDS) in prompt
    assert "scheme id is fixed" in prompt


@pytest.mark.asyncio
async def test_no_inputs_leaves_prompt_unchanged():
    assert "Judge request" not in await RedAgent(S).build_prompt(turn())


@pytest.mark.asyncio
async def test_request_is_capped_in_count_and_length():
    prompt = await RedAgent(S).build_prompt(turn(inputs=[judge_input(text="x" * 2000)] * 5))
    assert prompt.count('"text"') == 3  # at most three requests
    assert "x" * 501 not in prompt  # each cut to 500 chars


def test_agent_sourced_inputs_are_ignored():
    opts = {"inputs": [{**judge_input(), "source": s} for s in ("red", "green", "blue")] + [{**judge_input("ok"), "source": "frontend"}]}
    assert [r["text"] for r in judge_requests(opts)] == ["ok"]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [["ghost_vendor"], {"x": 1}, 7, None])
async def test_non_string_closest_built_in_does_not_crash(bad):
    prompt = await RedAgent(S).build_prompt(turn(inputs=[judge_input(closest_built_in=bad)]))
    assert '"closest_built_in": null' in prompt


@pytest.mark.asyncio
async def test_side_fields_are_capped_and_catalog_checked():
    big = judge_input(language="y" * 200_000, closest_built_in="z" * 200_000)
    prompt = await RedAgent(S).build_prompt(turn(inputs=[big]))
    assert "y" * 17 not in prompt and "z" * 10 not in prompt
    ok = await RedAgent(S).build_prompt(turn(inputs=[judge_input(closest_built_in=FIRST)]))
    assert FIRST in ok
