"""AuditLog — append-only ledger with hash chain for tamper evidence.

Each row stores ``hash = sha256(prev_hash || canonical_json(payload))``.
The chain is rebuilt and verified on startup via :func:`verify_chain`.
Append goes through :func:`append` which serializes by acquiring a lock
on the most recent row before computing and inserting the new hash.

For SQLite (single-writer model), an application-level :class:`asyncio.Lock`
is sufficient. For Postgres, the same code path uses ``SELECT ... FOR
UPDATE`` to serialize multi-writer access.
"""

from __future__ import annotations

from sqlalchemy import JSON, BigInteger, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base, TimestampMixin


class AuditLog(TimestampMixin, Base):
    __tablename__ = "audit_logs"

    # SQLite's autoincrement only works with INTEGER (the implicit ROWID
    # alias). On Postgres we keep BIGINT for room. with_variant gives both.
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_type: Mapped[str | None] = mapped_column(String(32), index=True)
    target_id: Mapped[str | None] = mapped_column(String(64), index=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (Index("ix_audit_target", "target_type", "target_id"),)


# Genesis hash used for the very first audit row.
GENESIS_HASH = "0" * 64


__all__ = ["GENESIS_HASH", "AuditLog"]
