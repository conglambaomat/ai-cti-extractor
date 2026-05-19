"""EvidenceSpan — exact byte-offset citation inside a chunk."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, TimestampMixin, UuidMixin


class EvidenceSpan(UuidMixin, TimestampMixin, Base):
    __tablename__ = "evidence_spans"

    chunk_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    text_span: Mapped[str] = mapped_column(Text, nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
