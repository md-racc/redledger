"""Playbook-aware lineage turn prompts: keyless, no SDK, model or ledger traffic."""

from typing import Any

from playbook import MAX_PROMPT_SECTION_BYTES, MEMORY_KEY, PROCEDURES, playbook_prompt_section

from agent import GreenAgent
from agentkit import AgentSettings, TurnRequest, ctx

S = AgentSettings(
    _env_file=None,
    AGENT_NAME="green",
    AGENT_TOKEN="test-agent",
    FACTORY_API_KEY=None,
    DROID_MODEL=None,
    DROID_REASONING=None,
    DRY_RUN=True,
    TURN_TIMEOUT_SEC=180,
)
STATIC = "Day 2. Follow the AP procedure in your system prompt. Start with ap_queue."
LINEAGE = {"id": "ln_private", "generation": 2, "playbook_version": 7}
REQ = TurnRequest(episode_id="private-episode", day=2, controller_mode="enforce", options={"lineage": LINEAGE})


class FakeLedger:
    def __init__(self, playbook: dict[str, Any] | None = None, error: Exception | None = None):
        self.playbook, self.error, self.calls = playbook, error, 0

    async def get_playbook(self) -> dict[str, Any] | None:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.playbook


def playbook_with(reminders: list[Any], **extra: Any) -> dict[str, Any]:
    content = {MEMORY_KEY: {"schema_version": 1, "procedure_reminders": reminders}, **extra}
    return {"version": 7, "generation": 2, "source": "operator", "content": content, "rationale": "private-operator-prose"}


async def prompt(agent: GreenAgent, ledger: FakeLedger, req: TurnRequest = REQ) -> str:
    tokens = ctx.bind(ledger, None, req)
    try:
        return await agent.build_prompt(req)
    finally:
        ctx.unbind(tokens)


async def test_lineage_playbook_procedures_reach_the_prompt() -> None:
    agent, ledger = GreenAgent(S), FakeLedger(playbook_with(list(PROCEDURES)))
    result = await prompt(agent, ledger)
    assert result.startswith(STATIC)
    assert ledger.calls == 1
    assert "Lineage generation 2, playbook version 7" in result
    for procedure in PROCEDURES:
        assert procedure in result


async def test_lineage_with_no_playbook_keeps_the_static_prompt() -> None:
    result = await prompt(GreenAgent(S), FakeLedger(None))
    assert result == STATIC


async def test_lineage_playbook_read_failure_keeps_the_static_prompt() -> None:
    result = await prompt(GreenAgent(S), FakeLedger(error=RuntimeError("boom")))
    assert result == STATIC


async def test_plain_episode_never_reads_the_playbook() -> None:
    ledger = FakeLedger(playbook_with(list(PROCEDURES)))
    req = TurnRequest(episode_id="private-episode", day=2, controller_mode="enforce")
    result = await prompt(GreenAgent(S), ledger, req)
    assert result == STATIC
    assert ledger.calls == 0


async def test_rationale_and_operator_prose_never_reach_the_prompt() -> None:
    playbook = playbook_with(list(PROCEDURES), operator_note="private operator prose")
    result = await prompt(GreenAgent(S), FakeLedger(playbook))
    assert "private operator prose" not in result
    assert "private-operator-prose" not in result
    assert "rationale" not in result


async def test_unusable_memory_renders_no_section() -> None:
    for memory in (None, {}, {"procedure_reminders": "not-a-list"}, {"procedure_reminders": ["invented non-procedure"]}):
        playbook = {"version": 7, "content": {MEMORY_KEY: memory}, "rationale": "x"}
        assert await prompt(GreenAgent(S), FakeLedger(playbook)) == STATIC


def test_prompt_section_stays_bounded(monkeypatch) -> None:
    huge = ["x" * 512 for _ in range(20)]
    monkeypatch.setattr("playbook.PROCEDURES", tuple(huge))
    section = playbook_prompt_section(playbook_with(huge), LINEAGE)
    assert section and len(section.encode("utf-8")) <= MAX_PROMPT_SECTION_BYTES
    assert section.endswith('"') is False  # lines are plain text, no quoting artifacts


def test_prompt_section_is_deterministic() -> None:
    playbook = playbook_with([PROCEDURES[1], PROCEDURES[0], PROCEDURES[1]])
    first = playbook_prompt_section(playbook, LINEAGE)
    assert first == playbook_prompt_section(playbook, LINEAGE)
    assert first.count(PROCEDURES[1]) == 1  # duplicates collapse, stored order kept
    assert first.index(PROCEDURES[1]) < first.index(PROCEDURES[0])


def test_prompt_section_empty_without_lineage_or_playbook() -> None:
    assert playbook_prompt_section(None, LINEAGE) == ""
    assert playbook_prompt_section(playbook_with(list(PROCEDURES)), None) == ""
