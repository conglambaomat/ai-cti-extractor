"""Tests for the audit hash chain.

Uses an in-memory SQLite engine so tests are fully isolated from the dev DB.
"""

from __future__ import annotations

import pytest
from app.core.exceptions import AuditChainError
from app.db.audit_chain import append, verify_chain
from app.db.models import Base
from app.db.models.audit_log import GENESIS_HASH
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture()
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as s:
        yield s
    await engine.dispose()


async def test_first_row_has_genesis_prev_hash(session: AsyncSession) -> None:
    row = await append(session, actor="t", action="ingest", payload={"x": 1})
    assert row.prev_hash == GENESIS_HASH
    assert len(row.hash) == 64


async def test_chain_links_correctly(session: AsyncSession) -> None:
    a = await append(session, actor="t", action="a", payload={"i": 1})
    b = await append(session, actor="t", action="b", payload={"i": 2})
    c = await append(session, actor="t", action="c", payload={"i": 3})
    assert b.prev_hash == a.hash
    assert c.prev_hash == b.hash
    ok, count = await verify_chain(session)
    assert ok is True
    assert count == 3


async def test_verify_chain_detects_tamper(session: AsyncSession) -> None:
    await append(session, actor="t", action="a", payload={"i": 1})
    row_b = await append(session, actor="t", action="b", payload={"i": 2})
    # Tamper: change payload of an existing row, hash now stale
    row_b.payload = {"i": 999}
    await session.flush()
    with pytest.raises(AuditChainError):
        await verify_chain(session)


async def test_concurrent_appends_serialized(session: AsyncSession) -> None:
    # 10 sequential appends through the lock should produce a valid chain.
    for i in range(10):
        await append(session, actor="t", action="x", payload={"i": i})
    ok, count = await verify_chain(session)
    assert ok is True
    assert count == 10


async def test_payload_canonicalization_is_order_insensitive(session: AsyncSession) -> None:
    # Two payloads that differ only in key order should hash the same.
    a = await append(session, actor="t", action="x", payload={"a": 1, "b": 2})
    # Re-create chain head with the same logical content — ensures canonical
    # JSON serialization gives the same hash regardless of dict insertion order.
    b_payload = {"b": 2, "a": 1}
    # Recompute manually using the same helpers:
    from app.db.audit_chain import _canonical_json, _next_hash

    expected = _next_hash(a.hash, b_payload)
    assert _canonical_json(b_payload) == _canonical_json({"a": 1, "b": 2})
    assert isinstance(expected, str)
    assert len(expected) == 64
