"""Document — top-level row per ingested threat report."""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, TimestampMixin, UuidMixin


class Document(UuidMixin, TimestampMixin, Base):
    __tablename__ = "documents"

    source_uri: Mapped[str] = mapped_column(String(2048), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(1024))
    language: Mapped[str] = mapped_column(String(8), default="en", nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(128))
    source_format: Mapped[str | None] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)
