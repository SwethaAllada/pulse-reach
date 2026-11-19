from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "PulseReach API"
    # Explicit data source for read APIs: 'memory' (default demo) or 'db' (PostgreSQL).
    data_source: Literal["memory", "db"] = "memory"

    @field_validator("data_source", mode="before")
    @classmethod
    def _normalize_data_source(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip().lower()
        return v
    # No default: credentials come from the environment (.env is git-ignored).
    # When unset the API still starts; database features report "not configured".
    database_url: SecretStr | None = None
    cors_origins: str = "http://localhost:3000"
    rules_dir: str | None = None
    data_dir: str | None = None
    log_level: str = "INFO"
    # Refuse to start when the clinical bundle (and, in db mode, the matching seeded load) is
    # unavailable (BE-22). Disable only for tooling that imports the app without serving it.
    startup_validation: bool = True

    # AI assistance (explanations, outreach drafts, population summaries). Off by default; the
    # deterministic templates are always used when disabled, misconfigured or failing.
    llm_enabled: bool = False
    llm_provider: Literal["openai_compatible", "anthropic"] = "openai_compatible"
    llm_api_key: SecretStr | None = None
    llm_base_url: str | None = None  # default per provider
    llm_model: str | None = None
    llm_timeout_seconds: float = 20.0
    llm_max_output_tokens: int = 400

    # Connection pool (SQLAlchemy QueuePool)
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout: int = 30  # seconds to wait for a pooled connection
    db_pool_recycle: int = 1800  # seconds before a connection is replaced
    db_connect_timeout: int = 5  # seconds to wait for the server to accept a connection


settings = Settings()
