"""Typed runtime configuration via Pydantic Settings.

The :data:`settings` singleton is created at module import time. Callers
should ``from app.core.config import settings`` and read attributes; do not
call ``Settings()`` again or read ``os.environ`` directly elsewhere.

Defaults are safe for development. Production deployments must override:
  * ``APP_ENV=production``
  * ``DATABASE_URL`` (Postgres)
  * ``SECRET_KEY`` (32+ random bytes hex)
  * ``ALLOW_EXTERNAL_LLM`` is False by default; flip with explicit env.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """All runtime configuration. Read once, used everywhere."""

    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # --- Application ---
    APP_ENV: Literal["development", "staging", "production"] = "development"
    APP_NAME: str = "cti-extractor"
    APP_HOST: str = "0.0.0.0"  # noqa: S104 - dev default, prod uses reverse proxy
    APP_PORT: int = 8000
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    SECRET_KEY: SecretStr = SecretStr("change-me-32-bytes-hex")

    # --- Storage layer ---
    # Default: SQLite at data/cti.db (zero-setup development).
    # Production should set DATABASE_URL=postgresql+asyncpg://user:pass@host:port/db.
    DATABASE_URL: str = Field(
        default=f"sqlite+aiosqlite:///{_REPO_ROOT / 'data' / 'cti.db'!s}",
        description="SQLAlchemy async URL: sqlite+aiosqlite or postgresql+asyncpg",
    )

    # Local filesystem replaces MinIO/S3 in development; STORAGE_BACKEND=s3 swaps later.
    STORAGE_BACKEND: Literal["local", "s3"] = "local"
    STORAGE_LOCAL_DIR: Path = Field(
        default=_REPO_ROOT / "data" / "raw",
        description="Where raw report files are stored when STORAGE_BACKEND=local",
    )
    S3_ENDPOINT: str | None = None
    S3_BUCKET: str = "cti-reports"
    S3_ACCESS_KEY: SecretStr | None = None
    S3_SECRET_KEY: SecretStr | None = None
    S3_REGION: str = "us-east-1"

    # --- Job queue (deferred to Phase 7+; Phase 1 uses FastAPI BackgroundTasks) ---
    REDIS_URL: str = "redis://localhost:6379/0"
    JOB_QUEUE_BACKEND: Literal["background_tasks", "rq"] = "background_tasks"

    # --- LLM (Phase 3+) ---
    LLM_PROVIDER: Literal["openai", "anthropic", "azure", "local"] = "openai"
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_TEMPERATURE: float = 0.1
    LLM_MAX_TOKENS: int = 4096
    OPENAI_API_KEY: SecretStr | None = None
    ANTHROPIC_API_KEY: SecretStr | None = None
    ANTHROPIC_AUTH_TOKEN: SecretStr | None = None
    ANTHROPIC_BASE_URL: str | None = None
    ANTHROPIC_DEFAULT_SONNET_MODEL: str = "kr/claude-sonnet-4.6"
    ANTHROPIC_DEFAULT_OPUS_MODEL: str = "kr/claude-opus-4.7"
    ANTHROPIC_DEFAULT_HAIKU_MODEL: str = "kr/claude-haiku-4.5"
    LOCAL_LLM_BASE_URL: str = "http://localhost:11434/v1"
    LOCAL_LLM_MODEL: str = "llama3.1:8b-instruct"

    # --- OpenCTI / MISP / TAXII (Phase 8+) ---
    OPENCTI_URL: str | None = None
    OPENCTI_TOKEN: SecretStr | None = None
    MISP_URL: str | None = None
    MISP_API_KEY: SecretStr | None = None
    TAXII_SERVER_URL: str | None = None

    # --- Security policy ---
    ALLOW_EXTERNAL_LLM: bool = False
    REDACT_BEFORE_LLM: bool = True
    ENABLE_AUDIT_LOG: bool = True

    # --- Cost cap (matches .claude/hooks/cost-guard.cjs) ---
    CK_LLM_COST_CAP_USD: float = 90.0

    # --- API runtime ---
    DEBUG: bool = False
    TRUST_PROXY_HEADERS: bool = False
    MAX_CONCURRENT_PIPELINES: int = Field(default=3, ge=1, le=32)


settings = Settings()
"""Process-wide settings singleton."""


__all__ = ["Settings", "settings"]
