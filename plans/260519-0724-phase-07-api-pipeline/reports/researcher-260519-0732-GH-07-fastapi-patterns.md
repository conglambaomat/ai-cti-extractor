# FastAPI Service Architecture — Phase 07 Research Report

**Date:** 2026-05-19
**Researcher:** researcher agent
**Scope:** Application factory, DI, BackgroundTasks, lifespan, router layout, storage abstraction

---

## 1. Executive Summary

- **Use `create_app(settings)`** — module-level `app = FastAPI()` breaks test isolation; factory + DI override is the only clean path for pytest with overridden settings/DB.
- **`get_db` must be a FastAPI `Depends` generator, not the existing `asynccontextmanager`** — the existing `app/db/session.py::get_session` is a context manager suited for scripts/workers; routers need a `yield`-based dependency so FastAPI owns commit/rollback within the request lifecycle.
- **BackgroundTasks is adequate for Phase 7 but has three hard limits** — no persistence across restarts, no error propagation to caller, blocks uvicorn worker if task is CPU-bound. Document the migration signal clearly.
- **Lifespan replaces `@app.on_event`** — `@asynccontextmanager async def lifespan(app)` is the only non-deprecated startup/shutdown pattern as of FastAPI 0.93+.
- **`StorageBackend` Protocol with local + S3 impls** — design the interface S3-compatible now so Phase 8 MinIO swap is a one-line config change, not a refactor.

---

## 2. App Factory Pattern

### Why factory over module-level

Module-level `app = FastAPI()` means the engine and sessionmaker are created at import time using the real `settings`. Tests that need `DATABASE_URL=sqlite+aiosqlite:///:memory:` must monkey-patch before import — fragile and order-dependent. A factory receives `Settings` explicitly, creates the engine inside, and `app.dependency_overrides` can inject a test session factory cleanly.

### Recommended pattern

```python
# app/main.py  (~60 LOC)
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.responses import ORJSONResponse
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.core.exceptions import AppError
from app.core.logging import configure_logging, get_logger
from app.api.errors import app_error_handler, unhandled_error_handler
from app.api.routers import health, ingest, documents, extractions, stix


def _make_engine(s: Settings) -> AsyncEngine:
    """Mirrors app/db/session.py logic but scoped to this app instance."""
    if s.DATABASE_URL.startswith("sqlite"):
        return create_async_engine(
            s.DATABASE_URL, future=True, connect_args={"check_same_thread": False}
        )
    return create_async_engine(
        s.DATABASE_URL, future=True, pool_size=5, max_overflow=10, pool_pre_ping=True
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or Settings()
    configure_logging()
    log = get_logger(__name__)

    engine = _make_engine(cfg)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # --- startup ---
        log.info("startup", env=cfg.APP_ENV, db=cfg.DATABASE_URL.split("@")[-1])
        await _run_migrations(engine, cfg)
        # Stash engine + factory in app.state for DI
        app.state.engine = engine
        app.state.session_factory = session_factory
        app.state.settings = cfg
        yield
        # --- shutdown ---
        await engine.dispose()
        log.info("shutdown.complete")

    app = FastAPI(
        title="CTI Extractor API",
        version="0.1.0",
        default_response_class=ORJSONResponse,
        lifespan=lifespan,
    )

    # Error handlers
    app.add_exception_handler(AppError, app_error_handler)          # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_error_handler)   # type: ignore[arg-type]

    # Routers
    app.include_router(health.router)
    app.include_router(ingest.router,      prefix="/ingest",       tags=["ingest"])
    app.include_router(documents.router,   prefix="/documents",    tags=["documents"])
    app.include_router(extractions.router, prefix="/extractions",  tags=["extractions"])
    app.include_router(stix.router,        prefix="/stix",         tags=["stix"])

    return app


# Entry point for uvicorn: `uvicorn app.main:app`
app = create_app()
```

Key points:
- `engine` and `session_factory` live on `app.state` — DI dependencies read from `request.app.state`, not module globals.
- `_make_engine` is a thin wrapper; it does NOT import from `app.db.session` to avoid the module-level singleton. The existing `app/db/session.py` singleton stays for scripts/workers/tests that don't go through FastAPI.
- `ORJSONResponse` as default is ~3× faster than stdlib JSON for large STIX bundles.

---

## 3. Dependency Injection Patterns

### 3.1 `get_db` — async session per request

The existing `app/db/session.py::get_session` is an `asynccontextmanager` — correct for scripts but **not** a FastAPI dependency. FastAPI dependencies use `yield`, not `async with`.

```python
# app/api/deps.py
from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.storage.backend import StorageBackend, LocalStorageBackend


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a per-request AsyncSession. Commit on success, rollback on error."""
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
    """Return the Settings instance stored at app startup."""
    return request.app.state.settings  # type: ignore[no-any-return]


def get_storage(request: Request) -> StorageBackend:
    """Return the StorageBackend stored at app startup."""
    return request.app.state.storage  # type: ignore[no-any-return]


# Annotated aliases — use these in route signatures
DbSession  = Annotated[AsyncSession, Depends(get_db)]
AppSettings = Annotated[Settings,    Depends(get_settings)]
Storage     = Annotated[StorageBackend, Depends(get_storage)]
```

Usage in a router:

```python
@router.get("/{doc_id}", response_model=DocumentResponse)
async def get_document(doc_id: str, db: DbSession, cfg: AppSettings) -> DocumentResponse:
    ...
```

### 3.2 Why `request.app.state` over module globals

- Module globals (`engine`, `SessionFactory` in `session.py`) are created at import time with real settings. Tests that override `DATABASE_URL` after import are broken.
- `app.state` is set inside `lifespan` after `create_app` receives the `Settings` instance — tests call `create_app(test_settings)` and get a clean engine.
- `app.dependency_overrides[get_db] = override_get_db` in conftest.py replaces the session for the entire test app without touching module state.

### 3.3 Settings injection

`get_settings` reads from `app.state` (set in lifespan). Do NOT use `@lru_cache` on a `Settings()` constructor inside a dependency — that defeats the factory pattern. The singleton is `app.state.settings`, not a module-level import.

For code outside request context (background tasks, workers), `from app.core.config import settings` is still fine — that's the module-level singleton for non-HTTP paths.

### 3.4 Storage injection

`get_storage` follows the same `app.state` pattern. The backend is constructed in `lifespan` based on `cfg.STORAGE_BACKEND`:

```python
# inside lifespan, before yield:
if cfg.STORAGE_BACKEND == "local":
    app.state.storage = LocalStorageBackend(cfg.STORAGE_LOCAL_DIR)
else:
    app.state.storage = S3StorageBackend(cfg)  # Phase 8+
```

---

## 4. BackgroundTasks Design

### How it works

FastAPI `BackgroundTasks` runs callables **after the response is sent**, in the same event loop iteration as the request handler. They are not threads — they run in the asyncio event loop. Async callables run natively; sync callables are run in a threadpool via `asyncio.run_in_executor`.

### Correct usage for Phase 7

```python
# app/api/routers/ingest.py
from fastapi import BackgroundTasks

@router.post("/", response_model=IngestResponse, status_code=202)
async def ingest_document(
    background_tasks: BackgroundTasks,
    db: DbSession,
    storage: Storage,
    payload: IngestRequest,
) -> IngestResponse:
    doc = await _persist_document(db, storage, payload)
    background_tasks.add_task(_run_pipeline, doc.id, storage)
    return IngestResponse(document_id=doc.id, status="queued")


async def _run_pipeline(doc_id: str, storage: StorageBackend) -> None:
    """Runs after response. Gets its own DB session — NOT the request session."""
    from app.core.config import settings
    from app.db.session import get_session  # module-level singleton is fine here

    async with get_session() as session:
        await process_document(doc_id, session, storage)
```

**Critical**: the background task must open its own DB session. The request session (`db: DbSession`) is committed and closed when the response is sent — before the background task runs. Passing the request session to a background task is a use-after-close bug.

### Pitfalls and limits

| Pitfall | Detail | Mitigation |
|---|---|---|
| No persistence | Tasks are in-process. Restart = lost queue. | Acceptable for Phase 7 dev; document migration signal |
| No error propagation | Exceptions in background tasks are logged but not surfaced to the caller. The 202 response is already sent. | Wrap task body in try/except, write failure status to DB |
| Blocks event loop if CPU-bound | Sync tasks run in threadpool but async tasks run in the event loop. A CPU-heavy extraction step blocks all other requests. | Keep background task as thin orchestrator; push CPU work to `asyncio.to_thread` or `run_in_executor` |
| No retry | No built-in retry on failure. | Write `status="failed"` to `documents.status`; expose a `POST /documents/{id}/extract` re-trigger endpoint |
| No visibility | No queue depth metric, no job ID. | Write `status` transitions to `documents` table; poll via `GET /documents/{id}` |
| Concurrency unbounded | 100 simultaneous uploads = 100 concurrent pipeline runs. | Add a semaphore in `_run_pipeline` or limit via `settings.MAX_CONCURRENT_PIPELINES` |

### Migration signal — when BackgroundTasks is no longer adequate

Migrate to RQ (already in `settings.JOB_QUEUE_BACKEND`) when **any** of:
- Pipeline failures are lost across restarts (first production incident)
- Need retry-with-backoff (LLM rate limits in Phase 3)
- Need distributed workers (Phase 3 encoder inference is slow)
- Queue depth monitoring required for SLA

The `settings.JOB_QUEUE_BACKEND` toggle is already wired. Phase 7 ships `"background_tasks"`; Phase 3 flips to `"rq"`. The `_run_pipeline` function signature stays identical — only the dispatch layer changes.

---

## 5. Lifespan Management

### Full lifespan with migration + storage init

```python
# app/main.py — lifespan section (expanded)
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.core.logging import get_logger
from app.storage.backend import LocalStorageBackend, S3StorageBackend


async def _run_migrations(engine: AsyncEngine, cfg: Settings) -> None:
    """Run alembic upgrade head (or create_all for SQLite dev)."""
    log = get_logger(__name__)
    if cfg.DATABASE_URL.startswith("sqlite"):
        # Dev shortcut: create_all is idempotent and avoids alembic dep at startup
        from app.db.models.base import Base
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        log.info("db.create_all.done")
    else:
        # Production: run alembic programmatically
        import subprocess  # noqa: S404
        result = subprocess.run(  # noqa: S603
            ["alembic", "upgrade", "head"],
            capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            log.error("alembic.upgrade.failed", stderr=result.stderr)
            raise RuntimeError(f"alembic upgrade head failed: {result.stderr}")
        log.info("alembic.upgrade.done")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    cfg: Settings = app.state.settings  # set by create_app before lifespan runs
    log = get_logger(__name__)

    # 1. Engine + session factory
    engine = _make_engine(cfg)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # 2. Migrations
    await _run_migrations(engine, cfg)

    # 3. Storage backend
    if cfg.STORAGE_BACKEND == "local":
        storage = LocalStorageBackend(cfg.STORAGE_LOCAL_DIR)
    else:
        storage = S3StorageBackend(cfg)

    # 4. Stash on app.state for DI
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.storage = storage

    log.info("app.ready", env=cfg.APP_ENV)
    yield

    # 5. Graceful shutdown
    await engine.dispose()
    log.info("app.shutdown")
```

Notes:
- `alembic upgrade head` via subprocess is the simplest correct approach for production. Alembic's Python API (`alembic.config.Config` + `command.upgrade`) is an alternative but adds import complexity for marginal gain.
- For SQLite dev, `create_all` is idempotent and avoids requiring alembic to be configured before first run.
- `app.state.settings` must be set **before** `lifespan` is called. In `create_app`, set it before constructing `FastAPI(lifespan=lifespan)` via a closure or by setting it on a pre-constructed state object.

Cleaner closure approach (avoids the pre-set problem):

```python
def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or Settings()

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        # cfg is captured from the outer scope — no app.state pre-set needed
        engine = _make_engine(cfg)
        ...
        yield
        await engine.dispose()

    return FastAPI(lifespan=_lifespan, ...)
```

This is the recommended approach — `cfg` is captured by closure, no pre-set required.

---

## 6. Router Skeleton

### File layout

```
app/api/
├── __init__.py
├── deps.py              # get_db, get_settings, get_storage, Annotated aliases
├── errors.py            # app_error_handler, unhandled_error_handler → RFC 7807
├── routers/
│   ├── __init__.py
│   ├── health.py        # GET /health
│   ├── ingest.py        # POST /ingest
│   ├── documents.py     # GET /documents/{id}, GET /documents/{id}/chunks
│   ├── extractions.py   # GET /extractions/{id}, POST /extractions/{id}/rerun
│   └── stix.py          # POST /stix/validate
```

### Router conventions

**health.py** — no auth, no DB, pure liveness + readiness:
```python
router = APIRouter(tags=["health"])

class HealthResponse(BaseModel):
    status: Literal["ok"]
    env: str

@router.get("/health", response_model=HealthResponse)
async def health(cfg: AppSettings) -> HealthResponse:
    return HealthResponse(status="ok", env=cfg.APP_ENV)
```

**ingest.py** — 202 Accepted, background task dispatch:
```python
router = APIRouter(tags=["ingest"])

class IngestResponse(BaseModel):
    document_id: str
    status: Literal["queued"]

@router.post("/", response_model=IngestResponse, status_code=202)
async def ingest(
    background_tasks: BackgroundTasks,
    db: DbSession,
    storage: Storage,
    file: UploadFile | None = None,
    url: str | None = None,
) -> IngestResponse: ...
```

**documents.py**:
```python
router = APIRouter(tags=["documents"])

@router.get("/{doc_id}", response_model=DocumentResponse)
async def get_document(doc_id: str, db: DbSession) -> DocumentResponse: ...

@router.post("/{doc_id}/extract", response_model=ExtractResponse, status_code=202)
async def trigger_extract(
    doc_id: str,
    background_tasks: BackgroundTasks,
    db: DbSession,
    storage: Storage,
) -> ExtractResponse: ...
```

**extractions.py**:
```python
router = APIRouter(tags=["extractions"])

@router.get("/{doc_id}", response_model=IntermediateCTIResponse)
async def get_extraction(doc_id: str, db: DbSession) -> IntermediateCTIResponse: ...
```

**stix.py**:
```python
router = APIRouter(tags=["stix"])

class StixValidateRequest(BaseModel):
    bundle: dict[str, Any]

@router.post("/validate", response_model=ValidationResult)
async def validate_stix(body: StixValidateRequest) -> ValidationResult: ...
```

### Error handler (RFC 7807 problem+json)

```python
# app/api/errors.py
from fastapi import Request
from fastapi.responses import ORJSONResponse
from app.core.exceptions import (
    AppError, IngestionError, ExtractionError,
    StixError, ExportError, AuditChainError,
)

_STATUS_MAP: dict[type[AppError], int] = {
    IngestionError: 422,
    ExtractionError: 422,
    StixError: 422,
    ExportError: 502,
    AuditChainError: 500,
}

async def app_error_handler(request: Request, exc: AppError) -> ORJSONResponse:
    status = next(
        (v for k, v in _STATUS_MAP.items() if isinstance(exc, k)), 500
    )
    return ORJSONResponse(
        status_code=status,
        content={"type": type(exc).__name__, "detail": str(exc)},
    )

async def unhandled_error_handler(request: Request, exc: Exception) -> ORJSONResponse:
    get_logger(__name__).exception("unhandled_error", exc_info=exc)
    return ORJSONResponse(status_code=500, content={"type": "InternalError", "detail": "unexpected error"})
```

---

## 7. Storage Protocol Design

### Protocol definition

```python
# app/storage/backend.py  (~120 LOC)
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel


class ObjectMeta(BaseModel):
    """Metadata returned by head_object."""
    key: str
    size: int
    etag: str          # md5 hex for local; ETag header for S3
    content_type: str


@runtime_checkable
class StorageBackend(Protocol):
    """S3-compatible storage abstraction.

    Implementations: LocalStorageBackend (dev), S3StorageBackend (Phase 8+).
    Key convention: "{doc_id}/{filename}" — no leading slash.
    """

    async def put_object(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> ObjectMeta: ...

    async def get_object(self, key: str) -> bytes: ...

    async def head_object(self, key: str) -> ObjectMeta: ...

    async def delete_object(self, key: str) -> None: ...
```

### Local filesystem implementation

```python
# app/storage/local.py  (~80 LOC)
from __future__ import annotations

import hashlib
from pathlib import Path

import aiofiles
import aiofiles.os

from app.storage.backend import ObjectMeta
from app.core.exceptions import AppError


class StorageKeyError(AppError):
    """Object not found at key."""


class LocalStorageBackend:
    """Stores objects as files under a root directory.

    Directory structure mirrors the key: root / key.
    Compatible with the StorageBackend Protocol.
    """

    def __init__(self, root: Path) -> None:
        self._root = root
        root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Prevent path traversal
        resolved = (self._root / key).resolve()
        if not str(resolved).startswith(str(self._root.resolve())):
            msg = f"key {key!r} escapes storage root"
            raise StorageKeyError(msg)
        return resolved

    async def put_object(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> ObjectMeta:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(path, "wb") as f:
            await f.write(data)
        etag = hashlib.md5(data, usedforsecurity=False).hexdigest()  # noqa: S324
        return ObjectMeta(key=key, size=len(data), etag=etag, content_type=content_type)

    async def get_object(self, key: str) -> bytes:
        path = self._path(key)
        if not path.exists():
            raise StorageKeyError(f"object not found: {key!r}")
        async with aiofiles.open(path, "rb") as f:
            return await f.read()

    async def head_object(self, key: str) -> ObjectMeta:
        path = self._path(key)
        if not path.exists():
            raise StorageKeyError(f"object not found: {key!r}")
        data = await self.get_object(key)  # small files; acceptable for dev
        etag = hashlib.md5(data, usedforsecurity=False).hexdigest()  # noqa: S324
        return ObjectMeta(key=key, size=path.stat().st_size, etag=etag, content_type="application/octet-stream")

    async def delete_object(self, key: str) -> None:
        path = self._path(key)
        if path.exists():
            await aiofiles.os.remove(path)
```

### S3 stub (Phase 8+)

```python
# app/storage/s3.py — stub, implement in Phase 8
class S3StorageBackend:
    """MinIO/S3 backend. Implements StorageBackend Protocol."""
    def __init__(self, cfg: Settings) -> None: ...
    async def put_object(self, key: str, data: bytes, content_type: str = ...) -> ObjectMeta: ...
    async def get_object(self, key: str) -> bytes: ...
    async def head_object(self, key: str) -> ObjectMeta: ...
    async def delete_object(self, key: str) -> None: ...
```

### Why this shape

- `put_object / get_object / head_object / delete_object` maps 1:1 to boto3/aiobotocore S3 method names — Phase 8 swap is mechanical.
- `ObjectMeta` is a Pydantic model so callers get typed metadata without `dict` access.
- Path traversal guard in `LocalStorageBackend._path` is mandatory — keys come from user-supplied filenames.
- `aiofiles` for async I/O — already in the Python ecosystem, no new top-level dep if added to `pyproject.toml`.

---

## 8. Risks & Architectural Notes

| Risk | Severity | Mitigation |
|---|---|---|
| `app/db/session.py` module-level `engine` conflicts with factory engine | Medium | Keep `session.py` for scripts/workers; factory creates its own engine. Two engines for same SQLite file is safe (aiosqlite serializes writes). Document the split. |
| Background task opens session from module-level `SessionFactory` (not factory's) | High | Explicitly import `get_session` from `app.db.session` in background tasks — that's the correct path for non-request code. Add a comment warning against using the request `db` session. |
| `mypy --strict` on `Protocol` with `runtime_checkable` | Low | `runtime_checkable` only checks method presence, not signatures. Add `# type: ignore[misc]` only if mypy complains about the Protocol class itself; all call sites will be fully typed. |
| `head_object` reads full file for local impl | Low | Acceptable for dev (reports are ≤50MB). Phase 8 S3 impl uses `HeadObject` API which is O(1). |
| `alembic upgrade head` via subprocess in lifespan | Medium | Fails silently if alembic.ini is missing. Add explicit check for `alembic.ini` existence before subprocess call. For SQLite dev, `create_all` path avoids this entirely. |
| Unbounded concurrent background pipelines | Medium | Add `asyncio.Semaphore(settings.MAX_CONCURRENT_PIPELINES)` in `_run_pipeline`. Default 3 for dev. |

---

## Unresolved Questions

1. **Auth middleware** — `system-architecture.md` §5 says "all endpoints require JWT auth except /health". Phase 7 plan must decide: implement JWT now or stub with a `X-API-Key` header check? JWT adds `python-jose` or `authlib` dep. Recommend `X-API-Key` stub for Phase 7, full JWT in Phase 8.
2. **`aiofiles` dep** — not in current `pyproject.toml`. Needs to be added. Alternative: `asyncio.to_thread(path.write_bytes, data)` avoids the dep but is less idiomatic.
3. **`ORJSONResponse` dep** — requires `orjson`. Not confirmed in `pyproject.toml`. If not present, fall back to `JSONResponse` (stdlib) with no code change needed — just remove the `default_response_class` line.
4. **`documents.status` state machine** — background task writes `status` transitions (`pending → processing → done / failed`). The exact states and transitions need to be defined in the phase plan before implementation.
5. **`POST /ingest` multipart vs JSON** — spec says "multipart or `{ url }`". FastAPI handles both but they need separate request models or a union. Decide before implementing the router.
6. **`StorageKeyError` subclass** — currently inherits `AppError` directly. Should it be `IngestionError`? Depends on whether storage failures during ingest should return 422 or 500. Recommend 500 (infrastructure failure, not user error) — add `StorageError(AppError)` to `exceptions.py`.
