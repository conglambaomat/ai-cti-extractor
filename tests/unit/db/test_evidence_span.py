"""Tests for EvidenceSpan.evidence_id schema-side identity column."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Base
from app.db.models.chunk import Chunk
from app.db.models.document import Document
from app.db.models.evidence_span import EvidenceSpan


@pytest.fixture()
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _make_chunk(session: AsyncSession) -> str:
    doc = Document(
        source_uri="file:///r.md", sha256="b" * 64, language="en", status="pending"
    )
    session.add(doc)
    await session.flush()
    chunk = Chunk(
        document_id=doc.id,
        text="alpha beta gamma",
        char_start=0,
        char_end=16,
        token_count=3,
    )
    session.add(chunk)
    await session.flush()
    return chunk.id


async def test_evidence_id_persisted_and_unique(session: AsyncSession) -> None:
    chunk_id = await _make_chunk(session)
    e = EvidenceSpan(
        evidence_id="e-0123456789abcdef",
        chunk_id=chunk_id,
        text_span="alpha",
        char_start=0,
        char_end=5,
    )
    session.add(e)
    await session.commit()

    rows = (await session.execute(select(EvidenceSpan))).scalars().all()
    assert len(rows) == 1
    assert rows[0].evidence_id == "e-0123456789abcdef"


async def test_evidence_id_uniqueness_enforced(session: AsyncSession) -> None:
    chunk_id = await _make_chunk(session)
    session.add(
        EvidenceSpan(
            evidence_id="e-dup",
            chunk_id=chunk_id,
            text_span="a",
            char_start=0,
            char_end=1,
        )
    )
    await session.commit()
    session.add(
        EvidenceSpan(
            evidence_id="e-dup",
            chunk_id=chunk_id,
            text_span="b",
            char_start=2,
            char_end=3,
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()
