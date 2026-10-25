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
    # Token scopes (contracts/agent-service.md "Tokens"). Each agent has its own token
    # (AGENT_TOKEN_<A>); unset or blank falls back to the shared AGENT_TOKEN, then the legacy
    # INTERNAL_TOKEN, then "change-me", so a single-token .env keeps working (separation off, warned).
    agent_token: str = Field("change-me", validation_alias=AliasChoices("AGENT_TOKEN", "INTERNAL_TOKEN"))
    agent_token_red: str | None = Field(None, alias="AGENT_TOKEN_RED")
    agent_token_green: str | None = Field(None, alias="AGENT_TOKEN_GREEN")
    agent_token_blue: str | None = Field(None, alias="AGENT_TOKEN_BLUE")
    operator_token: str = Field("change-me", validation_alias=AliasChoices("OPERATOR_TOKEN", "INTERNAL_TOKEN"))
    cors_origins: str = Field("http://localhost:3000", alias="CORS_ORIGINS")

    episode_default_days: int = Field(10, alias="EPISODE_DEFAULT_DAYS")
    turn_timeout_sec: int = Field(180, alias="TURN_TIMEOUT_SEC")
    gate_timeout_sec: int = Field(8, alias="GATE_TIMEOUT_SEC")
    escalation_timeout_sec: int = Field(90, alias="ESCALATION_TIMEOUT_SEC")
    fp_penalty_rate: float = Field(0.02, alias="FP_PENALTY_RATE")
    fp_flat_penalty: float = Field(50.0, alias="FP_FLAT_PENALTY")
    day_pause_sec: float = Field(0.0, alias="DAY_PAUSE_SEC")  # artificial pacing for demos
    max_credits_per_episode: float = Field(0.0, alias="MAX_CREDITS_PER_EPISODE")  # 0 = credit guard disabled

    fixtures_dir: str = Field("fixtures/episodes", alias="FIXTURES_DIR")
    schema_path: str = Field("db/schema.sql", alias="SCHEMA_PATH")
    log_level: str = Field("info", alias="LOG_LEVEL")

    def token_for(self, agent: str) -> str:
        """The token that authenticates `agent` (and that battlefield presents when calling it)."""
        own = getattr(self, f"agent_token_{agent}", None)
        return own or self.agent_token

    def token_warnings(self) -> list[str]:
        """Separation problems, naming tokens but never their values."""
        fallback = [a for a in AGENTS if not getattr(self, f"agent_token_{a}", None)]
        out: list[str] = []
        if fallback:
            names = ", ".join(f"AGENT_TOKEN_{a.upper()}" for a in fallback)
            out.append(f"{names} unset; {'/'.join(fallback)} use the shared AGENT_TOKEN (per-agent separation off)")
        # Equal resolved tokens, whatever their source. Agents sharing AGENT_TOKEN by fallback are
        # already reported above, so they are compared as one entry.
        named = [(f"AGENT_TOKEN_{a.upper()}", self.token_for(a)) for a in AGENTS if a not in fallback]
        if fallback:
            named.append(("AGENT_TOKEN (shared)", self.agent_token))
        named.append(("OPERATOR_TOKEN", self.operator_token))
        for i, (n1, v1) in enumerate(named):
            for n2, v2 in named[i + 1 :]:
                if v1 == v2:
                    out.append(f"{n1} equals {n2}; separation between them is off")
        return out

    @model_validator(mode="after")
    def _warn_on_shared_tokens(self) -> Settings:
        for w in self.token_warnings():
            log.warning("token_separation", detail=w)
        return self


AGENTS = ("red", "green", "blue")


settings = Settings()  # type: ignore[call-arg]
