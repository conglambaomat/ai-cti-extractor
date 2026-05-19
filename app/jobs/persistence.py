"""Persistence helpers for the pipeline orchestrator.

Each function takes an :class:`AsyncSession` and writes one phase's output.
Bulk inserts dedupe via ``insert_ignore`` so re-runs are idempotent.
Upstream callers commit between phases — these helpers do not commit.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.chunk import Chunk as ChunkRow
from app.db.models.document import Document
from app.db.models.evidence_span import EvidenceSpan
from app.db.models.ioc_candidate import IocCandidate as IocRow
from app.db.models.model_run import ModelRun
from app.db.models.stix_object import StixObject
from app.db.upsert import insert_ignore
from app.ingestion.types import Chunk as ChunkSchema
from app.ingestion.types import ParsedDocument
from app.schemas.evidence import Evidence
from app.schemas.ioc import IocCandidate as IocSchema


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def update_doc_after_parse(
    session: AsyncSession, document_id: str, parsed: ParsedDocument
) -> None:
    doc = await session.get(Document, document_id)
    if doc is None:
        return
    title = parsed.metadata.get("title")
    if title and not doc.title:
        doc.title = title[:1024]
    doc.language = parsed.language
    doc.source_format = parsed.source_format
    doc.status = "parsed"
    await session.flush()


async def persist_chunks(
    session: AsyncSession, document_id: str, chunks: list[ChunkSchema]
) -> dict[str, str]:
    """Insert Chunk rows; return mapping schema_chunk_id -> db_chunk_id."""
    mapping: dict[str, str] = {}
    if not chunks:
        return mapping
    rows: list[dict[str, Any]] = []
    for c in chunks:
        # Deterministic UUID derived from schema chunk_id so re-runs stable.
        db_id = str(uuid.uuid5(uuid.NAMESPACE_OID, c.chunk_id))
        mapping[c.chunk_id] = db_id
        rows.append({
            "id": db_id,
            "document_id": document_id,
            "section": c.section,
            "page": c.page,
            "text": c.text,
            "char_start": c.char_start,
            "char_end": c.char_end,
            "token_count": c.token_count,
            "created_at": _utcnow(),
            "updated_at": _utcnow(),
        })
    stmt = insert_ignore(
        session, ChunkRow.__table__, rows, index_elements=["id"]
    )
    await session.execute(stmt)
    await session.flush()
    return mapping


async def persist_evidence(
    session: AsyncSession,
    evidence: list[Evidence],
    chunk_id_map: dict[str, str],
) -> None:
    if not evidence:
        return
    rows: list[dict[str, Any]] = []
    for ev in evidence:
        db_chunk_id = chunk_id_map.get(ev.chunk_id)
        if db_chunk_id is None:
            continue
        # PK derived from evidence_id for deterministic re-runs
        db_id = str(uuid.uuid5(uuid.NAMESPACE_OID, ev.evidence_id))
        rows.append({
            "id": db_id,
            "evidence_id": ev.evidence_id,
            "chunk_id": db_chunk_id,
            "text_span": ev.text_span,
            "char_start": ev.char_start,
            "char_end": ev.char_end,
            "created_at": _utcnow(),
            "updated_at": _utcnow(),
        })
    stmt = insert_ignore(
        session, EvidenceSpan.__table__, rows, index_elements=["evidence_id"]
    )
    await session.execute(stmt)
    await session.flush()


async def persist_iocs(
    session: AsyncSession, document_id: str, iocs: list[IocSchema]
) -> None:
    if not iocs:
        return
    rows: list[dict[str, Any]] = []
    for ioc in iocs:
        rows.append({
            "id": str(uuid.uuid4()),
            "document_id": document_id,
            "type": ioc.type.value,
            "value": ioc.value,
            "normalized": ioc.normalized,
            "evidence_ids": list(ioc.evidence_ids),
            "confidence": float(ioc.confidence),
            "extractor": ioc.extractor,
            "created_at": _utcnow(),
            "updated_at": _utcnow(),
        })
    stmt = insert_ignore(
        session,
        IocRow.__table__,
        rows,
        index_elements=["document_id", "type", "normalized"],
    )
    await session.execute(stmt)
    await session.flush()


async def persist_stix(
    session: AsyncSession, document_id: str, bundle_dict: dict[str, Any]
) -> None:
    """Insert one StixObject row per object in the bundle."""
    objs = bundle_dict.get("objects", []) or []
    if not objs:
        return
    rows: list[dict[str, Any]] = []
    for obj in objs:
        if not isinstance(obj, dict):
            continue
        obj_id = str(obj.get("id") or "")
        obj_type = str(obj.get("type") or "")
        if not obj_id or not obj_type:
            continue
        canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"))
        import hashlib
        h = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        rows.append({
            "id": str(uuid.uuid5(uuid.NAMESPACE_OID, obj_id)),
            "type": obj_type,
            "stix_id": obj_id,
            "document_id": document_id,
            "json": obj,
            "hash": h,
            "version": 1,
            "created_at": _utcnow(),
            "updated_at": _utcnow(),
        })
    stmt = insert_ignore(
        session, StixObject.__table__, rows, index_elements=["stix_id"]
    )
    await session.execute(stmt)
    await session.flush()


async def record_model_run(
    session: AsyncSession,
    *,
    document_id: str,
    model: str,
    version: str,
    input_hash: str,
    output_hash: str | None,
    started_at: datetime,
    ended_at: datetime,
    cost_usd: float | None = None,
) -> None:
    session.add(
        ModelRun(
            document_id=document_id,
            model=model,
            version=version,
            input_hash=input_hash,
            output_hash=output_hash,
            started_at=started_at,
            ended_at=ended_at,
            cost_usd=cost_usd,
        )
    )
    await session.flush()


async def set_document_status(
    session: AsyncSession, document_id: str, status: str
) -> None:
    doc = await session.get(Document, document_id)
    if doc is None:
        return
    doc.status = status
    await session.flush()


__all__ = [
    "persist_chunks",
    "persist_evidence",
    "persist_iocs",
    "persist_stix",
    "record_model_run",
    "set_document_status",
    "update_doc_after_parse",
]
