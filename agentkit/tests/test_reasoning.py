"""DROID_REASONING is validated at startup, not on every turn. Owner: Dev Ad."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentkit.config import REASONING_EFFORTS, AgentSettings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.delenv("DROID_REASONING", raising=False)
    monkeypatch.chdir(tmp_path)  # no stray .env file
    monkeypatch.setenv("AGENT_NAME", "green")


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_unset_or_blank_means_model_default(monkeypatch: pytest.MonkeyPatch, raw: str | None) -> None:
    if raw is not None:
        monkeypatch.setenv("DROID_REASONING", raw)
    assert AgentSettings().droid_reasoning is None


@pytest.mark.parametrize("raw,want", [("HIGH", "high"), (" Low ", "low"), ("xhigh", "xhigh"), ("None", "none")])
def test_valid_values_are_normalised(monkeypatch: pytest.MonkeyPatch, raw: str, want: str) -> None:
    monkeypatch.setenv("DROID_REASONING", raw)
    assert AgentSettings().droid_reasoning == want


@pytest.mark.parametrize("raw", ["hgih", "auto", "dynamic", "3"])
def test_bad_value_fails_at_startup(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("DROID_REASONING", raw)
    with pytest.raises(ValidationError, match="DROID_REASONING"):
        AgentSettings()


def test_allowed_values_are_all_accepted_by_the_sdk() -> None:
    droid_sdk = pytest.importorskip("droid_sdk")
    for v in REASONING_EFFORTS:
        droid_sdk.ReasoningEffort(v)
