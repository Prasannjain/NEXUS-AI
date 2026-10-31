from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT_DEFAULT = "sqlite:///./data/nexus.db"


class Settings(BaseSettings):
    """Environment-driven configuration. Secrets are never hardcoded."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "NEXUS AI"
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = True

    # --- Database -----------------------------------------------------------
    # PostgreSQL in docker-compose; SQLite keeps the local demo runnable
    # without a database server.
    database_url: str = Field(default=PROJECT_ROOT_DEFAULT)
    sqlalchemy_echo: bool = False

    # --- Redis (optional task queue / cache) --------------------------------
    redis_url: str | None = None
    redis_max_concurrency: int = 4

    # --- Auth ---------------------------------------------------------------
    secret_key: str = Field(default="")
    access_token_expire_minutes: int = 720
    jwt_algorithm: str = "HS256"

    # --- LLM providers ------------------------------------------------------
    llm_provider: Literal["auto", "gemini", "openai", "ollama", "none"] = "auto"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"
    # Empty means "not configured"; the Ollama default port is applied in _ollama().
    ollama_base_url: str = ""
    ollama_model: str = "llama3.1"
    llm_timeout_seconds: int = 60

    # --- Orchestration ------------------------------------------------------
    checkpoint_database_path: str = "./data/nexus_checkpoints.db"
    generated_documents_dir: str = "./data/generated_documents"
    max_task_attempts: int = 3
    retry_base_delay_seconds: float = 0.5
    retry_backoff_factor: float = 2.0
    workflow_escalation_email: str = "it-administrator@nexus-ai.example"

    # --- CORS ---------------------------------------------------------------
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:4173",
            "http://localhost:3000",
        ]
    )

    seed_demo_data: bool = True

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value):
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("secret_key", mode="before")
    @classmethod
    def _default_secret(cls, value):
        if value:
            return value
        # A generated dev key keeps local runs working while making it obvious
        # that production must supply SECRET_KEY.
        import secrets

        return secrets.token_urlsafe(32)

    @property
    def redis_enabled(self) -> bool:
        return bool(self.redis_url)

    def resolved_llm_provider(self) -> str:
        """Pick a usable provider, degrading to the deterministic planner."""
        if self.llm_provider != "auto":
            return self.llm_provider
        if self.gemini_api_key:
            return "gemini"
        if self.openai_api_key:
            return "openai"
        if self.ollama_base_url:
            return "ollama"
        return "none"

    def provider_available(self, provider: str) -> bool:
        if provider == "gemini":
            return bool(self.gemini_api_key)
        if provider == "openai":
            return bool(self.openai_api_key)
        if provider == "ollama":
            return bool(self.ollama_base_url)
        return provider == "none"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
