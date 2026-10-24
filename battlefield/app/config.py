"""Battlefield settings. Environment only. Owner: Dev Ad."""

from __future__ import annotations

import structlog
from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

log = structlog.get_logger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field("postgresql://redledger:redledger@postgres:5432/redledger", alias="DATABASE_URL")
    red_url: str = Field("http://red:8001", alias="RED_URL")
    green_url: str = Field("http://green:8002", alias="GREEN_URL")
    blue_url: str = Field("http://blue:8003", alias="BLUE_URL")
    # Two token scopes (contracts/agent-service.md). Each falls back to the legacy INTERNAL_TOKEN,
    # then to "change-me", so a stale single-token .env keeps working (with separation disabled).
    agent_token: str = Field("change-me", validation_alias=AliasChoices("AGENT_TOKEN", "INTERNAL_TOKEN"))
    operator_token: str = Field("change-me", validation_alias=AliasChoices("OPERATOR_TOKEN", "INTERNAL_TOKEN"))
    cors_origins: str = Field("http://localhost:3000", alias="CORS_ORIGINS")

    episode_default_days: int = Field(10, alias="EPISODE_DEFAULT_DAYS")
    turn_timeout_sec: int = Field(180, alias="TURN_TIMEOUT_SEC")
    gate_timeout_sec: int = Field(8, alias="GATE_TIMEOUT_SEC")
    escalation_timeout_sec: int = Field(90, alias="ESCALATION_TIMEOUT_SEC")
    fp_penalty_rate: float = Field(0.02, alias="FP_PENALTY_RATE")
    fp_flat_penalty: float = Field(50.0, alias="FP_FLAT_PENALTY")
    approval_threshold: float = Field(5000.0, alias="APPROVAL_THRESHOLD")  # the auto-approve line red aims under
    day_pause_sec: float = Field(0.0, alias="DAY_PAUSE_SEC")  # artificial pacing for demos
    max_credits_per_episode: float = Field(0.0, alias="MAX_CREDITS_PER_EPISODE")  # 0 = credit guard disabled

    fixtures_dir: str = Field("fixtures/episodes", alias="FIXTURES_DIR")
    schema_path: str = Field("db/schema.sql", alias="SCHEMA_PATH")
    log_level: str = Field("info", alias="LOG_LEVEL")

    @model_validator(mode="after")
    def _warn_if_tokens_equal(self) -> Settings:
        if self.agent_token == self.operator_token:
            log.warning("tokens equal; agent/operator separation disabled")
        return self


settings = Settings()  # type: ignore[call-arg]
