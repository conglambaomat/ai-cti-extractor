"""Tests for the dialect-portable upsert helper."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Base
from app.db.models.document import Document
from app.db.upsert import insert_ignore


@pytest.fixture()
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as s:
        yield s
    await engine.dispose()


async def test_insert_ignore_dedupes_by_index_elements(session: AsyncSession) -> None:
    row = {
        "id": "00000000-0000-0000-0000-000000000001",
        "source_uri": "file:///r.md",
        "sha256": "a" * 64,
        "language": "en",
        "status": "pending",
    }
    stmt = insert_ignore(
        session, Document.__table__, [row], index_elements=["sha256"]
    )
    await session.execute(stmt)
    await session.commit()

    # Re-issue same row; ON CONFLICT DO NOTHING should make this a no-op
    dup = {**row, "id": "00000000-0000-0000-0000-000000000002"}
    stmt2 = insert_ignore(
        session, Document.__table__, [dup], index_elements=["sha256"]
    )
    await session.execute(stmt2)
    await session.commit()

    rows = (await session.execute(select(Document))).scalars().all()
    assert len(rows) == 1
    assert rows[0].id == "00000000-0000-0000-0000-000000000001"


async def test_insert_ignore_returns_statement_object(
    session: AsyncSession,
) -> None:
    # Sanity: helper returns an Insert; executing on empty rows is caller's risk.
    # SQLAlchemy with empty values list builds a no-op-ish stmt; assert no crash
    # at construction time with one row.
    stmt = insert_ignore(
        session,
        Document.__table__,
        [
            {
                "id": "00000000-0000-0000-0000-000000000099",
                "source_uri": "file:///x.md",
                "sha256": "z" * 64,
                "language": "en",
                "status": "pending",
            }
        ],
        index_elements=["sha256"],
    )
    assert stmt is not None
    assert hasattr(stmt, "compile")
