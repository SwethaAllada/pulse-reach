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

    # Connection pool (SQLAlchemy QueuePool)
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout: int = 30  # seconds to wait for a pooled connection
    db_pool_recycle: int = 1800  # seconds before a connection is replaced
    db_connect_timeout: int = 5  # seconds to wait for the server to accept a connection


settings = Settings()
