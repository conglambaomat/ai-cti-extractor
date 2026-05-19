"""Export — record of a STIX bundle pushed to OpenCTI / MISP / TAXII."""

from __future__ import annotations

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, TimestampMixin, UuidMixin


class Export(UuidMixin, TimestampMixin, Base):
    __tablename__ = "exports"

    target_system: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    bundle_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    response: Mapped[dict[str, object] | None] = mapped_column(JSON)
    exported_by: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="submitted")
