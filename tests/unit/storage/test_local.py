"""Tests for LocalStorageBackend.

Covers happy path, round-trip integrity, deletion, and path-traversal guards.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.storage.backend import StorageBackend, StorageError
from app.storage.local import LocalStorageBackend


@pytest.fixture()
def storage(tmp_path: Path) -> LocalStorageBackend:
    return LocalStorageBackend(tmp_path / "storage")


async def test_put_then_get_roundtrips_exactly(
    storage: LocalStorageBackend,
) -> None:
    payload = b"hello world\x00\xff binary safe"
    meta = await storage.put_object(
        "doc-1/raw", payload, content_type="application/pdf"
    )
    assert meta.key == "doc-1/raw"
    assert meta.size == len(payload)
    assert len(meta.etag) == 32
    assert meta.content_type == "application/pdf"

    fetched = await storage.get_object("doc-1/raw")
    assert fetched == payload


async def test_head_returns_size_and_etag(storage: LocalStorageBackend) -> None:
    payload = b"abc"
    await storage.put_object("doc-2/raw", payload)
    meta = await storage.head_object("doc-2/raw")
    assert meta.size == 3
    assert len(meta.etag) == 32


async def test_get_missing_key_raises(storage: LocalStorageBackend) -> None:
    with pytest.raises(StorageError):
        await storage.get_object("nope/raw")


async def test_delete_removes_object(storage: LocalStorageBackend) -> None:
    await storage.put_object("doc-3/raw", b"x")
    await storage.delete_object("doc-3/raw")
    with pytest.raises(StorageError):
        await storage.get_object("doc-3/raw")


async def test_delete_missing_is_noop(storage: LocalStorageBackend) -> None:
    # Idempotent
    await storage.delete_object("never-existed/raw")


async def test_path_traversal_rejected(storage: LocalStorageBackend) -> None:
    with pytest.raises(StorageError):
        await storage.put_object("../etc/passwd", b"bad")


async def test_absolute_key_rejected(storage: LocalStorageBackend) -> None:
    with pytest.raises(StorageError):
        await storage.put_object("/abs/path", b"bad")


async def test_empty_key_rejected(storage: LocalStorageBackend) -> None:
    with pytest.raises(StorageError):
        await storage.put_object("", b"bad")


async def test_protocol_compliance(storage: LocalStorageBackend) -> None:
    assert isinstance(storage, StorageBackend)
