---
phase: 2
title: "Storage Protocol + LocalStorageBackend"
status: pending
priority: P1
effort: "1h"
dependencies: [1]
---

# Phase 02: Storage abstraction

## Overview

S3-compatible storage Protocol + local filesystem implementation. Phase 08 swaps to MinIO with zero call-site changes.

## Requirements

- `put_object(key, data, content_type) -> ObjectMeta`
- `get_object(key) -> bytes`
- `head_object(key) -> ObjectMeta`
- `delete_object(key) -> None`
- Path-traversal guard mandatory
- Async I/O via `aiofiles`

## Architecture

### Files

```
app/storage/
├── __init__.py
├── backend.py          # Protocol + ObjectMeta + StorageError
└── local.py            # LocalStorageBackend
```

### `app/storage/backend.py`
```python
"""Storage abstraction — S3-compatible Protocol shape.

Local impl in local.py; S3/MinIO impl deferred to Phase 08.
Key convention: "{doc_id}/{filename}" (no leading slash).
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from app.core.exceptions import AppError


class StorageError(AppError):
    """Storage backend failure (path-traversal, missing key, IO error)."""


class ObjectMeta(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    key: str
    size: int
    etag: str  # md5 hex (local) or S3 ETag
    content_type: str


@runtime_checkable
class StorageBackend(Protocol):
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

### `app/storage/local.py`
```python
"""Local filesystem StorageBackend implementation."""
from __future__ import annotations

import hashlib
from pathlib import Path

import aiofiles
import aiofiles.os

from app.storage.backend import ObjectMeta, StorageError


class LocalStorageBackend:
    """Stores objects under root dir. Compatible with StorageBackend Protocol."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _safe_path(self, key: str) -> Path:
        if not key or key.startswith("/") or ".." in Path(key).parts:
            raise StorageError(f"invalid key: {key!r}")
        resolved = (self._root / key).resolve()
        if not str(resolved).startswith(str(self._root)):
            raise StorageError(f"key {key!r} escapes storage root")
        return resolved

    async def put_object(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> ObjectMeta:
        path = self._safe_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(path, "wb") as f:
            await f.write(data)
        etag = hashlib.md5(data, usedforsecurity=False).hexdigest()  # noqa: S324
        return ObjectMeta(
            key=key, size=len(data), etag=etag, content_type=content_type
        )

    async def get_object(self, key: str) -> bytes:
        path = self._safe_path(key)
        if not path.exists():
            raise StorageError(f"object not found: {key!r}")
        async with aiofiles.open(path, "rb") as f:
            return await f.read()

    async def head_object(self, key: str) -> ObjectMeta:
        path = self._safe_path(key)
        if not path.exists():
            raise StorageError(f"object not found: {key!r}")
        size = path.stat().st_size
        # local etag: md5 of content (acceptable for dev; <50MB files)
        async with aiofiles.open(path, "rb") as f:
            data = await f.read()
        etag = hashlib.md5(data, usedforsecurity=False).hexdigest()  # noqa: S324
        return ObjectMeta(
            key=key, size=size, etag=etag,
            content_type="application/octet-stream",
        )

    async def delete_object(self, key: str) -> None:
        path = self._safe_path(key)
        if path.exists():
            await aiofiles.os.remove(path)
```

## Related Code Files

- Create: `app/storage/__init__.py`
- Create: `app/storage/backend.py` (~50 LOC)
- Create: `app/storage/local.py` (~80 LOC)
- Modify: `pyproject.toml` (add `aiofiles>=23` dep)
- Create: `tests/unit/storage/test_local.py`

## Implementation Steps

1. Add `aiofiles` to runtime deps in `pyproject.toml`. Run `uv sync`.
2. Write `backend.py` (Protocol + ObjectMeta + StorageError).
3. Write `local.py`. Implement all four methods.
4. Tests:
   - put → head returns correct size + etag
   - put → get round-trips bytes exactly
   - delete then get raises StorageError
   - path traversal `../etc/passwd` raises StorageError
   - `/abs/path` key raises StorageError
   - empty key raises StorageError
5. mypy --strict clean.

## Success Criteria

- [ ] `isinstance(LocalStorageBackend(tmp), StorageBackend)` True
- [ ] All 6+ unit tests pass
- [ ] Path traversal blocked
- [ ] mypy + ruff + bandit clean
