"""Storage abstraction — S3-compatible Protocol shape.

Phase 07 ships a local-filesystem implementation; Phase 08+ swaps in MinIO/S3
without touching call sites. Key convention: ``"{document_id}/raw"`` (no
leading slash). Path traversal is rejected at the boundary.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from app.core.exceptions import AppError


class StorageError(AppError):
    """Storage backend failure (path-traversal, missing key, IO error)."""


class ObjectMeta(BaseModel):
    """Lightweight metadata returned by storage backends."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    size: int
    etag: str
    content_type: str


@runtime_checkable
class StorageBackend(Protocol):
    """Async, S3-shaped object storage."""

    async def put_object(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> ObjectMeta: ...

    async def get_object(self, key: str) -> bytes: ...

    async def head_object(self, key: str) -> ObjectMeta: ...

    async def delete_object(self, key: str) -> None: ...


__all__ = ["ObjectMeta", "StorageBackend", "StorageError"]
