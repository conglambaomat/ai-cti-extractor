"""StixObject + StixRelationship — persisted STIX 2.1 layer."""

from __future__ import annotations

from sqlalchemy import JSON, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, TimestampMixin, UuidMixin


class StixObject(UuidMixin, TimestampMixin, Base):
    __tablename__ = "stix_objects"

    type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    stix_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    document_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class StixRelationship(UuidMixin, TimestampMixin, Base):
    __tablename__ = "stix_relationships"

    source_ref: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_ref: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    relationship_type: Mapped[str] = mapped_column(String(64), nullable=False)
    document_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
