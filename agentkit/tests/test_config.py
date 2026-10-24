"""AgentSettings token alias precedence. Owner: Dev Ad."""

from __future__ import annotations

import pytest

from agentkit.config import AgentSettings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.delenv("AGENT_TOKEN", raising=False)
    monkeypatch.delenv("INTERNAL_TOKEN", raising=False)
    monkeypatch.chdir(tmp_path)  # no stray .env file
    monkeypatch.setenv("AGENT_NAME", "red")


def test_default_token() -> None:
    assert AgentSettings().internal_token == "change-me"


def test_internal_token_env_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTERNAL_TOKEN", "legacy")
    assert AgentSettings().internal_token == "legacy"


def test_agent_token_env_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_TOKEN", "new")
    assert AgentSettings().internal_token == "new"


def test_agent_token_wins_over_internal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTERNAL_TOKEN", "legacy")
    monkeypatch.setenv("AGENT_TOKEN", "new")
    assert AgentSettings().internal_token == "new"


def test_env_file_fallback(tmp_path) -> None:
    (tmp_path / ".env").write_text("INTERNAL_TOKEN=from-file\n")
    assert AgentSettings().internal_token == "from-file"


@pytest.mark.parametrize("kw", ["INTERNAL_TOKEN", "AGENT_TOKEN"])
def test_constructor_kwargs(kw: str) -> None:
    s = AgentSettings(AGENT_NAME="red", **{kw: "t"})
    assert s.internal_token == "t"
    assert s.agent_name == "red"
