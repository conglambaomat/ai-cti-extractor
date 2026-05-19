---
phase: 4
title: "App factory + lifespan + dependency injection"
status: pending
priority: P1
effort: "1.5h"
dependencies: [2, 3]
---

# Phase 04: App factory & DI

## Overview

`create_app(settings)` factory with closure-captured lifespan. DI via `request.app.state` for testable overrides. No module-level singletons in HTTP path.

## Files

```
app/
├── main.py                         # create_app, lifespan, module-level `app`
└── api/
    └── deps.py                     # get_db, get_settings, get_storage + Annotated aliases
```

## Architecture

### `app/main.py` (~120 LOC)

```python
def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or get_settings_singleton()  # module-level Settings()
    configure_logging()

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = _make_engine(cfg)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        await _ensure_schema(engine, cfg)  # SQLite → create_all; Postgres → alembic later
        storage = _make_storage(cfg)
        app.state.engine = engine
        app.state.session_factory = session_factory
        app.state.storage = storage
        app.state.settings = cfg
        app.state.pipeline_semaphore = asyncio.Semaphore(cfg.MAX_CONCURRENT_PIPELINES)
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(
        title="CTI Extractor API",
        version="0.1.0",
        lifespan=_lifespan,
    )
    app.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(app)

    # Routers (Phase 05)
    app.include_router(health.router)
    app.include_router(ingest.router, prefix="/ingest", tags=["ingest"])
    app.include_router(documents.router, prefix="/documents", tags=["documents"])
    app.include_router(extractions.router, prefix="/extractions", tags=["extractions"])
    app.include_router(stix.router, prefix="/stix", tags=["stix"])
    return app


app = create_app()  # uvicorn entrypoint
```

### `app/api/deps.py` (~80 LOC)

```python
async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
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
```

## Related Code Files

- Create: `app/main.py` (~120 LOC)
- Create: `app/api/deps.py` (~80 LOC)
- Create: `tests/unit/api/test_app_factory.py`
- Modify: `pyproject.toml` (`fastapi[standard]>=0.115`, `httpx>=0.27` dev dep)

## Implementation Steps

1. `_make_engine(cfg)` mirrors `app/db/session._build_engine` logic but local.
2. `_ensure_schema(engine, cfg)` runs `Base.metadata.create_all` for SQLite.
3. `_make_storage(cfg)` returns `LocalStorageBackend(cfg.STORAGE_LOCAL_DIR)` for `local`, raises NotImplementedError for `s3` (Phase 08).
4. Tests:
   - `create_app(test_settings)` returns FastAPI instance
   - lifespan startup creates engine, sets state, runs create_all
   - `get_db` yields session, commits on success, rolls back on exception
   - `app.dependency_overrides[get_db]` works (injecting test session)

## Success Criteria

- [ ] `from app.main import app` succeeds; uvicorn boots
- [ ] `GET /openapi.json` returns 200 (FastAPI serves docs)
- [ ] DI override pattern verified by test
- [ ] mypy --strict clean
