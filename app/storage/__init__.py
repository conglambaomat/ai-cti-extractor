"""Object storage abstraction (Phase 07 = local FS, Phase 08+ = MinIO/S3)."""

from __future__ import annotations

from app.storage.backend import ObjectMeta, StorageBackend, StorageError
from app.storage.local import LocalStorageBackend

__all__ = ["LocalStorageBackend", "ObjectMeta", "StorageBackend", "StorageError"]
