"""Request-scoped FastAPI dependencies.

These read from ``request.app.state``, set during the lifespan span by
:func:`app.main.create_app`. Annotated aliases keep router signatures terse.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.storage.backend import StorageBackend


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a per-request AsyncSession with commit/rollback semantics."""
    factory = request.app.state.session_factory
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        else:
            await session.commit()


def get_settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


def get_storage(request: Request) -> StorageBackend:
    return request.app.state.storage  # type: ignore[no-any-return]


def get_pipeline_semaphore(request: Request) -> asyncio.Semaphore:
    return request.app.state.pipeline_semaphore  # type: ignore[no-any-return]


DbSession = Annotated[AsyncSession, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]
Storage = Annotated[StorageBackend, Depends(get_storage)]
PipelineSemaphore = Annotated[asyncio.Semaphore, Depends(get_pipeline_semaphore)]


__all__ = [
    "AppSettings",
    "DbSession",
    "PipelineSemaphore",
    "Storage",
    "get_db",
    "get_pipeline_semaphore",
    "get_settings",
    "get_storage",
]
