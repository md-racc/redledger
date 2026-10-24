"""Environment-only configuration shared by red/green/blue. No config files."""

from __future__ import annotations

from decimal import Decimal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Values droid_sdk.ReasoningEffort accepts (droid-sdk 0.5.0). Kept here so a bad DROID_REASONING
# fails at startup instead of raising inside every turn, and so DRY_RUN needs no droid_sdk.
REASONING_EFFORTS = ("none", "off", "minimal", "low", "medium", "high", "xhigh", "max")


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    agent_name: str = Field(..., alias="AGENT_NAME")  # red | green | blue
    battlefield_url: str = Field("http://battlefield:8000", alias="BATTLEFIELD_URL")
    blue_url: str = Field("http://blue:8003", alias="BLUE_URL")  # only green uses it
    # Bearer token for agent <-> battlefield calls. AGENT_TOKEN wins; INTERNAL_TOKEN is the legacy
    # name kept as a fallback so stale .env files and `AgentSettings(INTERNAL_TOKEN=...)` still work.
    internal_token: str = Field("change-me", validation_alias=AliasChoices("AGENT_TOKEN", "INTERNAL_TOKEN"))

    factory_api_key: str | None = Field(None, alias="FACTORY_API_KEY")
    droid_model: str | None = Field(None, alias="DROID_MODEL")
    droid_reasoning: str | None = Field(None, alias="DROID_REASONING")  # none|off|minimal|low|medium|high|xhigh|max
    dry_run: bool = Field(False, alias="DRY_RUN")

    turn_timeout_sec: int = Field(180, alias="TURN_TIMEOUT_SEC")
    gate_timeout_sec: int = Field(8, alias="GATE_TIMEOUT_SEC")
    # battlefield's hold on an escalated gated call; agents only use it to sanity-check the tool cap
    escalation_timeout_sec: int = Field(90, alias="ESCALATION_TIMEOUT_SEC")
    http_timeout_sec: float = Field(15.0, alias="HTTP_TIMEOUT_SEC")
    # The auto-approve line red aims under (battlefield's APPROVAL_THRESHOLD). The single agent-side default.
    approval_threshold: Decimal = Field(Decimal("5000"), alias="APPROVAL_THRESHOLD")
    log_level: str = Field("info", alias="LOG_LEVEL")

    port: int = Field(8001, alias="PORT")

    @field_validator("droid_reasoning", mode="before")
    @classmethod
    def _check_reasoning(cls, v: object) -> str | None:
        if v is None:
            return None
        if not isinstance(v, str):
            raise ValueError(f"DROID_REASONING must be a string, one of {'|'.join(REASONING_EFFORTS)}")
        v = v.strip().lower()
        if not v:
            return None  # blank = model default (compose passes DROID_REASONING_<AGENT>:-)
        if v not in REASONING_EFFORTS:
            raise ValueError(f"DROID_REASONING={v!r} is not one of {'|'.join(REASONING_EFFORTS)} (or blank)")
        return v
