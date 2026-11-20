from typing import Literal

from pydantic import Field, SecretStr, field_validator
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
    # Shared demo access code required on state-changing requests (`X-PulseReach-Write-Key`).
    # Without it writes are refused, unless unprotected writes are explicitly allowed (local only).
    write_api_key: SecretStr | None = None
    allow_unprotected_writes: bool = False
    rules_dir: str | None = None
    data_dir: str | None = None
    log_level: str = "INFO"
    # Refuse to start when the clinical bundle (and, in db mode, the matching seeded load) is
    # unavailable (BE-22). Disable only for tooling that imports the app without serving it.
    startup_validation: bool = True

    # AI assistance (explanations, outreach drafts, population summaries). Off by default; the
    # deterministic templates are always used when disabled, misconfigured or failing.
    llm_enabled: bool = False
    llm_provider: Literal["openai_compatible", "anthropic", "gemini"] = "openai_compatible"
    llm_api_key: SecretStr | None = None  # openai_compatible / anthropic only
    llm_base_url: str | None = None  # default per provider (not used by gemini)
    llm_model: str | None = None  # overrides GEMINI_MODEL when LLM_PROVIDER=gemini
    llm_timeout_seconds: float = Field(default=20.0, gt=0, le=120)  # per attempt
    llm_max_retries: int = Field(default=2, ge=0, le=5)  # transient failures only (timeouts, 429, 5xx)
    llm_total_timeout_seconds: float = Field(default=45.0, gt=0, le=300)  # all attempts + backoff
    llm_max_output_tokens: int = Field(default=400, ge=64, le=8192)
    # Google Gemini API (LLM_PROVIDER=gemini). The key comes from its own secret (Secret Manager
    # `pulsereach-gemini-api-key` on Cloud Run); it is never sent to the frontend.
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    # Optional `thinkingConfig.thinkingLevel` (minimal|low|medium|high); empty = model default.
    gemini_thinking_level: Literal["", "minimal", "low", "medium", "high"] = ""

    # Identity and access control (docs/authentication-and-rbac.md).
    # 'users': per-user bearer tokens, RBAC and organization isolation on every /api/v1 route.
    # 'legacy': previous behaviour (public reads + shared write key) for migration only; never
    # use it for a deployment with real user accounts.
    auth_mode: Literal["users", "legacy"] = "users"
    access_token_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    refresh_token_ttl_seconds: int = Field(default=7 * 24 * 3600, ge=300)
    session_max_age_seconds: int = Field(default=30 * 24 * 3600, ge=300)
    password_reset_ttl_seconds: int = Field(default=1800, ge=300, le=86400)
    account_activation_ttl_seconds: int = Field(default=3 * 24 * 3600, ge=300)
    patient_invitation_ttl_seconds: int = Field(default=7 * 24 * 3600, ge=300)
    patient_invitation_max_attempts: int = Field(default=5, ge=1, le=20)
    password_min_length: int = Field(default=12, ge=8, le=128)
    # scrypt cost (N = 2**k). OWASP minimum is N=2**17, r=8, p=1. Lower only for tests.
    password_scrypt_n: int = Field(default=2**17, ge=2**10)
    login_max_failures: int = Field(default=5, ge=1)
    login_lockout_seconds: int = Field(default=900, ge=1)
    auth_rate_limit_per_minute: int = Field(default=10, ge=1)
    # Proxies in front of the API that append to X-Forwarded-For (Cloud Run: 1; behind an external
    # load balancer as well: 2). 0 = use the socket peer. Only the entries those proxies appended
    # are trusted, so a client-supplied X-Forwarded-For prefix cannot pick a rate-limit bucket.
    trusted_proxy_hops: int = Field(default=0, ge=0, le=5)
    # Largest accepted request body (declared Content-Length); larger requests get 413.
    max_request_body_bytes: int = Field(default=1_048_576, ge=1024)
    self_registration_enabled: bool = True
    default_locale: Literal["en", "ar"] = "en"
    # Memory mode only: seed clearly synthetic demo organizations/users at startup with this
    # password (never a production password). Ignored unless both are set.
    demo_identity_seed: bool = False
    demo_identity_password: SecretStr | None = None

    # Geospatial population intelligence (docs/geospatial-population-intelligence.md).
    # Minimum reportable cell size; system-level (not editable by organizations).
    population_min_cell_size: int = Field(default=5, ge=3, le=50)
    # How often a request may re-check whether the underlying data changed (cheap query).
    population_freshness_check_seconds: int = Field(default=15, ge=0, le=3600)
    # A snapshot older than this is refreshed in the background even if no change was detected.
    population_max_snapshot_age_seconds: int = Field(default=3600, ge=60)
    # A `running` aggregation older than this is treated as abandoned (crashed worker).
    population_refresh_timeout_seconds: int = Field(default=600, ge=30)
    population_runs_retained: int = Field(default=10, ge=1, le=1000)

    # Connection pool (SQLAlchemy QueuePool)
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout: int = 30  # seconds to wait for a pooled connection
    db_pool_recycle: int = 1800  # seconds before a connection is replaced
    db_connect_timeout: int = 5  # seconds to wait for the server to accept a connection


settings = Settings()
