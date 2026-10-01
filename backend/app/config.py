"""Validated settings (docs/01 configuration contract).

Every value comes from the environment or the repository's `.env`. Live mode
fails fast when a required setting is missing; fixture mode is explicit and can
never publish (D09, docs/01). Provider keys are optional: a missing key means
the connector stays `access_pending` (D06).
"""

from __future__ import annotations

import secrets
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Mode(StrEnum):
    LIVE = "live"
    FIXTURE = "fixture"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env",),
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        hide_input_in_errors=True,  # a failed start must not echo credentials into logs
    )

    app_mode: Mode = Mode.FIXTURE
    log_level: str = "INFO"

    mongodb_uri: str = "mongodb://localhost:27017/?replicaSet=rs0&directConnection=true"
    mongodb_db: str = "sy_poc"

    session_secret: SecretStr | None = None
    session_ttl_hours: int = Field(default=12, ge=1, le=168)
    cookie_secure: bool = False
    web_origin: str = "http://localhost:3000"
    login_attempts_per_window: int = Field(default=10, ge=1)
    login_window_minutes: int = Field(default=15, ge=1)

    anthropic_api_key: SecretStr | None = None
    # Only for an organisation-level key: the workspace its requests run in (sent as anthropic-workspace-id).
    anthropic_workspace_id: str | None = Field(default=None, pattern=r"^wrkspc_[A-Za-z0-9]+$")
    model_routine: str = "claude-sonnet-5"
    model_reasoning: str = "claude-sonnet-5"
    model_difficult: str = "claude-opus-5-5"
    model_max_output_tokens: int = Field(default=16000, ge=256)
    model_max_attempts: int = Field(default=3, ge=1, le=6)

    job_lease_seconds: int = Field(default=60, ge=5)
    job_max_attempts: int = Field(default=5, ge=1)
    job_poll_seconds: float = Field(default=2.0, gt=0)
    run_budget_usd: float = Field(default=5.0, ge=0)

    # Collection (Step 05, docs/06). The crawler identifies itself honestly; limits are per host and per provider.
    crawler_user_agent: str = "ProjectIntelligenceBot/0.1 (project research POC)"  # no claim it cannot keep (D46)
    crawler_min_seconds_per_host: float = Field(default=3.0, ge=0)
    crawler_max_bytes: int = Field(default=3_000_000, ge=10_000)
    crawler_max_redirects: int = Field(default=5, ge=0, le=10)
    crawler_timeout_seconds: float = Field(default=20.0, gt=0)
    brave_monthly_queries: int = Field(default=2000, ge=0)
    brave_pages_per_query: int = Field(default=2, ge=1, le=10)
    youtube_daily_searches: int = Field(default=100, ge=0)
    youtube_daily_units: int = Field(default=10_000, ge=0)
    youtube_searches_per_project: int = Field(default=4, ge=0)
    youtube_comment_pages_per_video: int = Field(default=3, ge=0)
    web_pages_per_run: int = Field(default=40, ge=0)
    identity_agent_tasks_per_run: int = Field(default=10, ge=0)
    recheck_per_job: int = Field(default=200, ge=0)

    public_base_url: str = "http://localhost:3000"
    revalidation_secret: SecretStr | None = None

    brave_search_api_key: SecretStr | None = None
    firecrawl_api_key: SecretStr | None = None
    youtube_api_key: SecretStr | None = None
    reddit_client_id: SecretStr | None = None
    reddit_client_secret: SecretStr | None = None
    x_bearer_token: SecretStr | None = None
    meta_access_token: SecretStr | None = None
    listening_provider_api_key: SecretStr | None = None

    contracts_dir: Path = REPO_ROOT / "contracts"
    seed_dir: Path = REPO_ROOT / "seed"

    @model_validator(mode="after")
    def _required_in_live_mode(self) -> Settings:
        if self.app_mode is Mode.LIVE:
            missing = [
                name
                for name in ("session_secret", "revalidation_secret")
                if getattr(self, name) is None or len(getattr(self, name).get_secret_value()) < 32
            ]
            if missing:
                raise ValueError(
                    f"live mode needs {', '.join(n.upper() for n in missing)} set to at least 32 characters"
                )
        elif self.session_secret is None:
            # Fixture mode only: an ephemeral secret, so sessions end when the process restarts.
            self.session_secret = SecretStr(secrets.token_urlsafe(48))
        return self

    def model_for_role(self, role: str) -> str:
        return {"routine": self.model_routine, "reasoning": self.model_reasoning, "difficult": self.model_difficult}[
            role
        ]

    def credential_present(self, env_name: str) -> bool:
        value = getattr(self, env_name.lower(), None)
        return isinstance(value, SecretStr) and bool(value.get_secret_value())

    def secret_values(self) -> list[str]:
        """Every configured secret, for log redaction."""
        return [
            value.get_secret_value()
            for value in self.__dict__.values()
            if isinstance(value, SecretStr) and len(value.get_secret_value()) >= 8
        ]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
