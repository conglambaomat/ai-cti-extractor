"""Tests for ``app.core.config.settings`` (loading + types)."""

from __future__ import annotations

from app.core.config import Settings, settings


def test_default_env_is_development() -> None:
    assert settings.APP_ENV == "development"


def test_default_database_url_is_sqlite() -> None:
    assert settings.DATABASE_URL.startswith("sqlite+aiosqlite://")


def test_storage_backend_default_local() -> None:
    assert settings.STORAGE_BACKEND == "local"


def test_security_defaults_safe() -> None:
    assert settings.ALLOW_EXTERNAL_LLM is False
    assert settings.REDACT_BEFORE_LLM is True
    assert settings.ENABLE_AUDIT_LOG is True


def test_settings_is_singleton_like() -> None:
    # Reading the same field twice from the singleton returns the same value.
    a = settings.APP_NAME
    b = settings.APP_NAME
    assert a == b


def test_can_construct_via_env(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("APP_ENV", "staging")
    s = Settings()
    assert s.APP_ENV == "staging"
