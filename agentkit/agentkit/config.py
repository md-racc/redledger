"""Environment-only configuration shared by red/green/blue. No config files."""

from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    dry_run: bool = Field(False, alias="DRY_RUN")

    turn_timeout_sec: int = Field(180, alias="TURN_TIMEOUT_SEC")
    gate_timeout_sec: int = Field(8, alias="GATE_TIMEOUT_SEC")
    http_timeout_sec: float = Field(15.0, alias="HTTP_TIMEOUT_SEC")
    log_level: str = Field("info", alias="LOG_LEVEL")

    port: int = Field(8001, alias="PORT")
