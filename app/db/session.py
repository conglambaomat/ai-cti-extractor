"""Async SQLAlchemy engine + session factory.

Yields per-request sessions via :func:`get_session`. Workers / scripts
should also use this; do not instantiate sessions ad hoc.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings


def _ensure_sqlite_parent_dir(url: str) -> None:
    """Create the SQLite db's parent dir if missing (smoother dev UX)."""
    if not url.startswith("sqlite"):
        return
    db_path = url.split("///", 1)[-1]
    if not db_path or db_path == ":memory:":
        return
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)


def _build_engine() -> AsyncEngine:
    url = settings.DATABASE_URL
    _ensure_sqlite_parent_dir(url)
    # SQLite: pool config differs from server DBs; aiosqlite supports a
    # NullPool internally so we keep the connect_args minimal.
    if url.startswith("sqlite"):
        return create_async_engine(
            url,
            future=True,
            echo=False,
            connect_args={"check_same_thread": False},
        )
    # Postgres / others: standard pool sizes for a single FastAPI instance.
    return create_async_engine(
        url,
        future=True,
        echo=False,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
    )


engine: AsyncEngine = _build_engine()
"""Process-wide async engine."""


SessionFactory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield a session and ensure cleanup.

    Usage::

        async with get_session() as session:
            ...
    """
    async with SessionFactory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        else:
            await session.commit()


__all__ = ["SessionFactory", "engine", "get_session"]
