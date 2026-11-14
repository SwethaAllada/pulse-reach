from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "PulseReach API"
    database_url: str = "postgresql+psycopg://pulsereach:change-me@localhost:5432/pulsereach"
    cors_origins: str = "http://localhost:3000"


settings = Settings()
