"""FastAPI application factory.

The HTTP surface is built fresh per call so tests can inject overridden
``Settings`` and replace dependencies without touching module globals. The
module-level ``app`` is the production entrypoint for ``uvicorn app.main:app``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from app.api.exception_handlers import register_exception_handlers
from app.api.middleware.correlation_id import CorrelationIdMiddleware
from app.core.config import Settings
from app.core.config import settings as default_settings
from app.core.logging import configure_logging, get_logger
from app.db.models import Base
from app.db.session import _ensure_sqlite_parent_dir
from app.storage.backend import StorageBackend
from app.storage.local import LocalStorageBackend


def _make_engine(cfg: Settings) -> AsyncEngine:
    url = cfg.DATABASE_URL
    _ensure_sqlite_parent_dir(url)
    if url.startswith("sqlite"):
        return create_async_engine(
            url,
            future=True,
            echo=False,
            connect_args={"check_same_thread": False},
        )
    return create_async_engine(
        url,
        future=True,
        echo=False,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
    )


def _make_storage(cfg: Settings) -> StorageBackend:
    if cfg.STORAGE_BACKEND == "local":
        return LocalStorageBackend(cfg.STORAGE_LOCAL_DIR)
    raise NotImplementedError(
        "S3 backend lands in Phase 08; set STORAGE_BACKEND=local for now"
    )


async def _ensure_schema(engine: AsyncEngine, cfg: Settings) -> None:
    """SQLite dev: create_all. Postgres: alembic (deferred to Phase 08)."""
    if cfg.DATABASE_URL.startswith("sqlite"):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build a FastAPI app bound to ``settings``.

    Engine, sessionmaker, storage, and pipeline semaphore live on
    ``app.state`` so every dependency reads from the per-app instance.
    """
    cfg = settings or default_settings
    configure_logging()
    log = get_logger(__name__)

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = _make_engine(cfg)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        await _ensure_schema(engine, cfg)
        storage = _make_storage(cfg)

        app.state.engine = engine
        app.state.session_factory = session_factory
        app.state.storage = storage
        app.state.settings = cfg
        app.state.pipeline_semaphore = asyncio.Semaphore(
            cfg.MAX_CONCURRENT_PIPELINES
        )

        log.info(
            "app.ready",
            env=cfg.APP_ENV,
            db=cfg.DATABASE_URL.rsplit("@", 1)[-1],
            storage=cfg.STORAGE_BACKEND,
        )
        try:
            yield
        finally:
            await engine.dispose()
            log.info("app.shutdown")

    app = FastAPI(
        title="AI-Assisted CTI Extractor API",
        version="0.1.0",
        lifespan=_lifespan,
    )

    app.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(app)

    # Routers wired in Phase 05
    from app.api.routers import documents, extractions, health, ingest, stix

    app.include_router(health.router, tags=["health"])
    app.include_router(ingest.router, prefix="/ingest", tags=["ingest"])
    app.include_router(documents.router, prefix="/documents", tags=["documents"])
    app.include_router(
        extractions.router, prefix="/extractions", tags=["extractions"]
    )
    app.include_router(stix.router, prefix="/stix", tags=["stix"])

    return app


app = create_app()


__all__ = ["app", "create_app"]
