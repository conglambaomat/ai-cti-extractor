"""Audit log hash chain helpers.

Append-only writes serialized via an asyncio.Lock (sufficient for SQLite
single-writer; Postgres deployments can swap for ``SELECT ... FOR UPDATE``
without changing the public API).

Public:
    append(session, *, actor, action, target_type, target_id, payload) -> AuditLog
    verify_chain(session) -> tuple[bool, int]   # (ok, rows_checked)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuditChainError
from app.db.models.audit_log import GENESIS_HASH, AuditLog

_lock = asyncio.Lock()


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _next_hash(prev_hash: str, payload: dict[str, Any]) -> str:
    seed = prev_hash + "|" + _canonical_json(payload)
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


async def append(
    session: AsyncSession,
    *,
    actor: str,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> AuditLog:
    """Append a row, computing ``hash`` from the current chain head."""
    payload = payload or {}

    async with _lock:
        latest = (await session.execute(select(AuditLog).order_by(desc(AuditLog.id)).limit(1))).scalar_one_or_none()
        prev_hash = latest.hash if latest is not None else GENESIS_HASH

        row = AuditLog(
            prev_hash=prev_hash,
            hash=_next_hash(prev_hash, payload),
            actor=actor,
            action=action,
            target_type=target_type,
            target_id=target_id,
            payload=payload,
        )
        session.add(row)
        await session.flush()
        return row


async def verify_chain(session: AsyncSession) -> tuple[bool, int]:
    """Walk every row in id order, recompute hashes, return (ok, count).

    Raises :class:`AuditChainError` on the first mismatch with the row id.
    """
    rows = (await session.execute(select(AuditLog).order_by(AuditLog.id))).scalars().all()
    expected_prev = GENESIS_HASH
    for row in rows:
        if row.prev_hash != expected_prev:
            msg = f"audit row id={row.id}: prev_hash {row.prev_hash} != expected {expected_prev}"
            raise AuditChainError(msg)
        recomputed = _next_hash(row.prev_hash, row.payload)
        if row.hash != recomputed:
            msg = f"audit row id={row.id}: hash {row.hash} != recomputed {recomputed}"
            raise AuditChainError(msg)
        expected_prev = row.hash
    return True, len(rows)


__all__ = ["append", "verify_chain"]
