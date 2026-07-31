"""Central application settings, loaded from environment variables."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://agenteval:agenteval@localhost:5432/agenteval"
    redis_url: str = "redis://localhost:6379/0"

    secret_key: str = "change-me-in-production"  # used to sign JWTs
    access_token_expire_minutes: int = 60 * 24

    api_key_prefix: str = "ae_live_"

    judge_provider: str = "openai"  # openai | anthropic | ollama
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434"
    judge_model: str = "gpt-4o-mini"

    cors_origins: list[str] = ["http://localhost:5173"]

    rate_limit_per_minute: int = 120

    max_inline_payload_bytes: int = 256_000


settings = Settings()
