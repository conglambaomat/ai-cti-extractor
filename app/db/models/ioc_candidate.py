"""IocCandidate — extracted indicator with evidence references."""

from __future__ import annotations

from sqlalchemy import JSON, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, TimestampMixin, UuidMixin


class IocCandidate(UuidMixin, TimestampMixin, Base):
    __tablename__ = "ioc_candidates"

    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    value: Mapped[str] = mapped_column(String(2048), nullable=False)
    normalized: Mapped[str] = mapped_column(String(2048), nullable=False)
    # JSON list of evidence_span ids; SQLite-friendly. Postgres can later
    # migrate to ARRAY(UUID) for index efficiency without changing the
    # Python interface.
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    confidence: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False)
    extractor: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (Index("ix_ioc_doc_type_norm", "document_id", "type", "normalized", unique=True),)
