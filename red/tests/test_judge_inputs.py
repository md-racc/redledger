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
