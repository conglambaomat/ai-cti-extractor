"""Pytest configuration and shared fixtures.

Loaded automatically by pytest at session start. Keep cross-cutting concerns
here (event loop, env vars, fixture roots); domain fixtures go under
``tests/fixtures/``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_FIXTURES = _REPO_ROOT / "tests" / "fixtures"


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Absolute path to the repository root."""
    return _REPO_ROOT


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    """Absolute path to ``tests/fixtures/``."""
    return _FIXTURES


def pytest_configure(config: pytest.Config) -> None:
    """Set safe defaults for tests that read env-driven config."""
    os.environ.setdefault("APP_ENV", "development")
    os.environ.setdefault("LOG_LEVEL", "WARNING")
    # Default to in-memory SQLite for unit tests; integration tests opt in
    # by overriding these in their own fixtures.
    os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
    os.environ.setdefault("S3_ENDPOINT", "http://localhost:9000")
    os.environ.setdefault("S3_BUCKET", "cti-test")
    os.environ.setdefault("S3_ACCESS_KEY", "test")
    os.environ.setdefault("S3_SECRET_KEY", "test")
    os.environ.setdefault("SECRET_KEY", "test-secret-not-for-production")
