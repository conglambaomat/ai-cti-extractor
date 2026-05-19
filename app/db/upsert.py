"""Dialect-portable ``INSERT ... ON CONFLICT DO NOTHING`` helper.

SQLite today, Postgres in Phase 08+. Centralizes the dialect import so call
sites stay clean and a future driver swap is a one-file change.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession


def insert_ignore(
    session: AsyncSession,
    table: Any,
    rows: list[dict[str, Any]],
    *,
    index_elements: list[str],
) -> Insert:
    """Build dialect-correct INSERT...ON CONFLICT DO NOTHING.

    Caller still executes via ``await session.execute(stmt)``.
    """
    bind = session.get_bind()
    dialect = bind.dialect.name
    builder = sqlite_insert if dialect == "sqlite" else pg_insert
    return builder(table).values(rows).on_conflict_do_nothing(
        index_elements=index_elements
    )


__all__ = ["insert_ignore"]
