"""Local filesystem implementation of the StorageBackend Protocol.

Stores objects as files under a root directory. Suitable for development
and small single-node deployments. Phase 08 swaps to MinIO/S3 by setting
``settings.STORAGE_BACKEND="s3"``.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import aiofiles
import aiofiles.os

from app.storage.backend import ObjectMeta, StorageError


class LocalStorageBackend:
    """Filesystem-backed StorageBackend.

    Path traversal (``../``, absolute keys) is rejected at the boundary —
    keys are user-supplied, so this is mandatory.
    """

    def __init__(self, root: Path) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _safe_path(self, key: str) -> Path:
        if not key:
            raise StorageError("storage key is empty")
        if key.startswith(("/", "\\")):
            raise StorageError(f"absolute key rejected: {key!r}")
        if ".." in Path(key).parts:
            raise StorageError(f"key contains parent ref: {key!r}")
        resolved = (self._root / key).resolve()
        # Ensure resolved still inside root (defense-in-depth)
        try:
            resolved.relative_to(self._root)
        except ValueError as exc:
            raise StorageError(f"key escapes storage root: {key!r}") from exc
        return resolved

    @staticmethod
    def _md5(data: bytes) -> str:
        # Non-cryptographic — used as ETag, mirrors S3 behavior.
        return hashlib.md5(data, usedforsecurity=False).hexdigest()

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
        return ObjectMeta(
            key=key, size=len(data), etag=self._md5(data), content_type=content_type
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
        async with aiofiles.open(path, "rb") as f:
            data = await f.read()
        return ObjectMeta(
            key=key,
            size=size,
            etag=self._md5(data),
            content_type="application/octet-stream",
        )

    async def delete_object(self, key: str) -> None:
        path = self._safe_path(key)
        if path.exists():
            await aiofiles.os.remove(path)


__all__ = ["LocalStorageBackend"]
