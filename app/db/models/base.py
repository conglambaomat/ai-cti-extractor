"""SQLAlchemy 2.0 declarative base + cross-cutting columns.

Every model inherits from :class:`Base`. UUID and timestamps are wired in
via :class:`UuidMixin` and :class:`TimestampMixin` so individual models
stay focused on domain fields.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, ClassVar

from sqlalchemy import DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Project base. SQLAlchemy 2.0 typed declarative."""

    type_annotation_map: ClassVar[dict[Any, Any]] = {}


class UuidMixin:
    """Adds a string UUID primary key (``CHAR(36)``) portable across SQLite + Postgres.

    Postgres-only deployments can later migrate to ``UUID`` native via
    Alembic + ``op.alter_column`` if performance demands it; the column
    name remains ``id``.
    """

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )


class TimestampMixin:
    """``created_at`` + ``updated_at`` columns, always UTC."""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


__all__ = ["Base", "TimestampMixin", "UuidMixin"]
