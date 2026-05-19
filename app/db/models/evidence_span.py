"""EvidenceSpan — exact byte-offset citation inside a chunk."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, TimestampMixin, UuidMixin


class EvidenceSpan(UuidMixin, TimestampMixin, Base):
    __tablename__ = "evidence_spans"

    # Deterministic schema-side id from app.schemas.evidence (e-{sha256[:16+]}).
    # Distinct from the UUID PK so DB FKs stay UUID while extractor output keys
    # remain content-addressable across re-runs.
    evidence_id: Mapped[str] = mapped_column(
        String(96), unique=True, nullable=False, index=True
    )
    chunk_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    text_span: Mapped[str] = mapped_column(Text, nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
